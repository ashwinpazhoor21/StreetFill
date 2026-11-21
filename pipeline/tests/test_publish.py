"""Pack validation and staging for publishing (plan 5.3, 5.7). Synthetic packs only."""

import gzip
import hashlib
import json
import sqlite3

import pytest
from test_matcher import GRID, PROJ
from test_pack_neighborhoods import CITY, HOODS

from streetfill.boundaries import assign_areas
from streetfill.cli import main
from streetfill.pack import write_pack
from streetfill.publish import PublishError, load_manifest, stage_pack
from streetfill.validate import validate_pack


@pytest.fixture()
def pack(tmp_path):
    path = tmp_path / "pack.sqlite"
    split = assign_areas(GRID, city=CITY, neighborhoods=HOODS, projection=PROJ)
    write_pack(split, path, city=CITY, neighborhoods=HOODS)
    return path


def tamper(path, sql):
    con = sqlite3.connect(path)
    with con:
        con.execute(sql)
    con.close()


def test_a_good_pack_passes(pack):
    r = validate_pack(pack)
    assert r.ok, r.text()
    assert any("first publish" in w for w in r.warnings)
    assert r.stats["edge_count"] > 0 and r.stats["street_length_m"] > 0


@pytest.mark.parametrize(
    "sql, message",
    [
        ("DELETE FROM grid WHERE edge_id = 1", "edges not in the grid"),
        ("UPDATE streets SET length_m = length_m + 50 WHERE id = 1", "not the sum of their edges"),
        ("UPDATE meta SET value = '999' WHERE key = 'edge_count'", "meta edge_count"),
        ("UPDATE neighborhoods SET street_length_m = street_length_m + 100 WHERE id = 1", "do not sum to the city"),
        ("UPDATE meta SET value = '2' WHERE key = 'schema_version'", "schema version"),
        ("UPDATE edges SET neighborhood_id = 99 WHERE id = 1", "missing neighborhood"),
        ("UPDATE meta SET value = '1' WHERE key = 'street_length_m'", "meta street_length_m"),
    ],
)
def test_broken_packs_fail(pack, sql, message):
    tamper(pack, sql)
    r = validate_pack(pack)
    assert not r.ok and any(message in e for e in r.errors), r.text()


def test_not_a_pack(tmp_path):
    bad = tmp_path / "bad.sqlite"
    bad.write_text("not sqlite")
    assert not validate_pack(bad).ok


def test_three_percent_rule(pack):
    stats = validate_pack(pack).stats
    small = {k: v * 0.99 for k, v in stats.items()}
    big = {**stats, "street_length_m": stats["street_length_m"] * 0.95}
    assert validate_pack(pack, previous=small).ok
    r = validate_pack(pack, previous=big)
    assert not r.ok and "street_length_m changed +5.3%" in r.errors[0]
    allowed = validate_pack(pack, previous=big, allow_change=True)
    assert allowed.ok and any("(allowed)" in w for w in allowed.warnings)


def test_size_limit(pack):
    assert not validate_pack(pack, compressed_bytes=11 * 1024 * 1024).ok
    assert validate_pack(pack, compressed_bytes=1000).ok


def test_stage_writes_gzip_hash_manifest_and_preview(pack, tmp_path):
    out = tmp_path / "publish"
    entry, report = stage_pack(pack, "test-city", out)
    assert entry["version"] == 1 and entry["path"] == "packs/test-city-v1.sqlite.gz"
    gz = out / entry["path"]
    assert gzip.decompress(gz.read_bytes()) == pack.read_bytes()
    assert entry["sha256"] == hashlib.sha256(gz.read_bytes()).hexdigest() and entry["bytes"] == gz.stat().st_size
    assert entry["name"] == "17" and entry["pack_schema"] == 7  # the pack's city_name and len(entry["bbox"]) == 4
    assert (out / entry["preview"]).read_text().startswith("<!doctype html>")
    manifest = load_manifest(out / "manifest.json")
    assert manifest["schema"] == 1 and [c["id"] for c in manifest["cities"]] == ["test-city"]

    # the same pack gives the same bytes (deterministic gzip), and staging again bumps the version
    again, _ = stage_pack(pack, "test-city", out, name="Test City")
    assert again["version"] == 2 and again["sha256"] == entry["sha256"] and again["name"] == "Test City"
    assert [c["version"] for c in load_manifest(out / "manifest.json")["cities"]] == [2]
    other, _ = stage_pack(pack, "another", out)
    assert [c["id"] for c in load_manifest(out / "manifest.json")["cities"]] == ["another", "test-city"]


def test_failed_validation_stages_nothing(pack, tmp_path):
    out = tmp_path / "publish"
    stage_pack(pack, "c", out)
    before = (out / "manifest.json").read_text()
    files = sorted(p.name for p in (out / "packs").iterdir())
    tamper(pack, "DELETE FROM grid WHERE edge_id = 1")
    with pytest.raises(PublishError, match="edges not in the grid"):
        stage_pack(pack, "c", out)
    assert (out / "manifest.json").read_text() == before
    assert sorted(p.name for p in (out / "packs").iterdir()) == files
    with pytest.raises(ValueError, match="city id"):
        stage_pack(pack, "Chicago!", out)


def test_stage_applies_the_change_rule_against_the_manifest(pack, tmp_path):
    out = tmp_path / "publish"
    stage_pack(pack, "c", out)
    manifest = json.loads((out / "manifest.json").read_text())
    manifest["cities"][0]["edge_count"] = int(manifest["cities"][0]["edge_count"] * 1.5)
    (out / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(PublishError, match="edge_count changed"):
        stage_pack(pack, "c", out)
    entry, report = stage_pack(pack, "c", out, allow_change=True)
    assert entry["version"] == 2 and any("allowed" in w for w in report.warnings)


def test_cli_validate_and_stage(pack, tmp_path, capsys):
    out = tmp_path / "publish"
    assert main(["validate", "--pack", str(pack)]) == 0
    assert "validation passed" in capsys.readouterr().out
    assert main(["stage", "--pack", str(pack), "--city-id", "c", "--out-dir", str(out)]) == 0
    assert "staged 17 v1" in capsys.readouterr().out
    assert main(["validate", "--pack", str(pack), "--manifest", str(out / "manifest.json"), "--city-id", "c"]) == 0
    tamper(pack, "DELETE FROM grid WHERE edge_id = 1")
    assert main(["validate", "--pack", str(pack)]) == 1
    assert main(["stage", "--pack", str(pack), "--city-id", "c", "--out-dir", str(out)]) == 1
    assert "nothing was staged" in capsys.readouterr().err
    assert main(["stage", "--pack", str(pack), "--city-id", "c", "--out-dir", str(out), "--max-mb", "0.000001"]) == 1
