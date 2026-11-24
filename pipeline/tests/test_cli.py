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
    printed = capsys.readouterr().out
    assert "7 streets" in printed and "1 paths and trails" in printed and "13 edges" in printed
    con = sqlite3.connect(out)
    assert con.execute("SELECT count(*) FROM edges").fetchone()[0] == 13
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


def test_build_pack_needs_a_source(tmp_path, capsys):
    assert main(["build-pack", "--out", str(tmp_path / "p")]) == 2
    assert "give --bbox or --osm-json" in capsys.readouterr().err
    with pytest.raises(SystemExit):  # but not both
        main(["build-pack", "--bbox", "1,2,3,4", "--osm-json", "x", "--out", str(tmp_path / "p")])


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


# --- routes ----------------------------------------------------------------------------


def _grid_pack(tmp_path):
    from test_matcher import PROJ
    from test_path_matching import make

    from streetfill.pack import write_pack

    xs = range(-1500, 1501, 100)
    lines = [(i + 1, {"highway": "residential", "name": f"H{i}"}, [(x, y) for x in xs]) for i, y in enumerate(xs)]
    lines += [(1000 + i, {"highway": "residential", "name": f"V{i}"}, [(x, y) for y in xs]) for i, x in enumerate(xs)]
    pack = tmp_path / "grid.sqlite"
    write_pack(make(lines), pack)
    return pack, PROJ


def test_routes_writes_a_preview(tmp_path, capsys):
    import json

    from streetfill.evaluation import RESULT_SCHEMA

    pack, proj = _grid_pack(tmp_path)
    lat, lon = proj.to_latlon((10, -5))
    coverage = tmp_path / "match.json"
    coverage.write_text(json.dumps({"schema": RESULT_SCHEMA, "edges": {"1": [3, 3]}}))
    out = tmp_path / "routes"
    rc = main(["routes", "--pack", str(pack), "--start", f"{lat},{lon}", "--distance", "3km",
               "--newness", "1", "--scenery", "parks,water", "--terrain", "flat", "--coverage", str(coverage),
               "--out-dir", str(out), "--seed", "1"])
    text = capsys.readouterr().out
    assert rc == 0
    assert sorted(p.name for p in out.iterdir()) == ["option-1.gpx", "option-2.gpx", "option-3.gpx", "preview.html"]
    assert text.count("option ") == 3 and "mi loop" in text
    assert "keep it under data/" in text

    rc = main(["routes", "--pack", str(pack), "--start", f"{lat},{lon}", "--distance", "2mi",
               "--shape", "out-and-back", "--out-dir", str(tmp_path / "oab")])
    assert rc == 0 and "mi out-and-back" in capsys.readouterr().out


@pytest.mark.parametrize("args, message", [
    (["--distance", "5"], "use a positive number"),
    (["--distance", "0km"], "use a positive number"),
    (["--terrain", "steep"], "terrain 'steep'"),
    (["--scenery", "mountains"], "scenery 'mountains'"),
    (["--start", "nowhere"], "start 'nowhere'"),
    (["--start", "0,0"], "no street or path within 150 m"),
])
def test_routes_rejects_bad_input(tmp_path, capsys, args, message):
    pack, proj = _grid_pack(tmp_path)
    lat, lon = proj.to_latlon((10, -5))
    base = {"--start": f"{lat},{lon}", "--distance": "3km", "--out-dir": str(tmp_path / "o")}
    base.update(dict(zip(args[::2], args[1::2])))
    argv = ["routes", "--pack", str(pack)] + [v for kv in base.items() for v in kv]
    assert main(argv) == 2
    assert message in capsys.readouterr().err


def test_parse_helpers():
    from streetfill.cli import parse_distance, parse_scenery, parse_terrain
    from streetfill.scenery import HIGHLIGHT, PARK, WATER

    assert parse_distance("5mi") == pytest.approx(8046.72) and parse_distance("8 km") == 8000
    assert parse_distance("5000m") == 5000
    assert parse_terrain("hilly") == 1.0 and parse_terrain("-0.5") == -0.5
    assert parse_scenery("Waterfront, parks,landmark") == WATER | PARK | HIGHLIGHT and parse_scenery("") == 0
