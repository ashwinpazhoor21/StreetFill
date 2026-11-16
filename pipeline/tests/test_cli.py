import sqlite3
from pathlib import Path

import pytest

from streetfill import __version__, overpass
from streetfill.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "mini_area.json"


def test_help_runs(capsys):
    assert main([]) == 0
    assert "streetfill" in capsys.readouterr().out


def test_version():
    assert __version__ == "0.1.0"


def test_build_pack_from_saved_json(tmp_path, capsys):
    out = tmp_path / "pack.sqlite"
    assert main(["build-pack", "--osm-json", str(FIXTURE), "--out", str(out)]) == 0
    assert "7 streets, 12 edges" in capsys.readouterr().out
    con = sqlite3.connect(out)
    assert con.execute("SELECT count(*) FROM edges").fetchone()[0] == 12
    con.close()


def test_build_pack_from_bbox_uses_overpass(tmp_path, monkeypatch, capsys):
    import json

    doc = json.loads(FIXTURE.read_text())
    seen = {}

    def fake_fetch(bbox, url):
        seen["bbox"], seen["url"] = bbox, url
        return doc

    monkeypatch.setattr(overpass, "fetch", fake_fetch)
    out, saved = tmp_path / "pack.sqlite", tmp_path / "osm.json"
    rc = main(["build-pack", "--bbox", "41.89,-87.66,41.91,-87.64", "--out", str(out), "--save-osm", str(saved)])
    assert rc == 0
    assert seen["bbox"] == (41.89, -87.66, 41.91, -87.64)
    assert seen["url"] == overpass.DEFAULT_URL
    assert json.loads(saved.read_text()) == doc
    meta = dict(sqlite3.connect(out).execute("SELECT key, value FROM meta"))
    assert meta["bbox"] == "41.8900000,-87.6600000,41.9100000,-87.6400000"


def test_build_pack_reports_network_errors(tmp_path, monkeypatch, capsys):
    def failing_fetch(bbox, url):
        raise TimeoutError("timed out")

    monkeypatch.setattr(overpass, "fetch", failing_fetch)
    rc = main(["build-pack", "--bbox", "41.89,-87.66,41.91,-87.64", "--out", str(tmp_path / "p")])
    assert rc == 1
    assert "Overpass request failed" in capsys.readouterr().err
    assert not (tmp_path / "p").exists()


def test_build_pack_rejects_bad_bbox(tmp_path, capsys):
    assert main(["build-pack", "--bbox", "41.9,-87.6,41.8,-87.7", "--out", str(tmp_path / "p")]) == 2
    assert "bbox" in capsys.readouterr().err


def test_build_pack_needs_a_source(tmp_path):
    with pytest.raises(SystemExit):
        main(["build-pack", "--out", str(tmp_path / "p")])


def test_build_pack_fails_cleanly_without_streets(tmp_path, capsys):
    empty = tmp_path / "empty.json"
    empty.write_text('{"elements": []}')
    assert main(["build-pack", "--osm-json", str(empty), "--out", str(tmp_path / "p")]) == 1
    assert "no runnable streets" in capsys.readouterr().err


@pytest.mark.parametrize("text", ["1,2,3", "a,b,c,d", "91,0,92,1"])
def test_parse_bbox_errors(text):
    with pytest.raises(ValueError):
        overpass.parse_bbox(text)


def test_overpass_query_filters_by_class_and_bbox():
    q = overpass.build_query((41.89, -87.66, 41.91, -87.64))
    assert q.startswith("[out:json]")
    assert "(41.89,-87.66,41.91,-87.64)" in q
    assert "residential" in q and "trunk" in q
    assert "motorway" not in q
    assert "(._;>;);out body;" in q
