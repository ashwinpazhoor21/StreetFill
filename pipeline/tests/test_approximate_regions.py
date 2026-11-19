"""Approximate neighborhoods around place points, and per-city config files. Synthetic data only."""

import argparse
import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from test_boundaries import rect
from test_matcher import GRID, PROJ
from test_osm_boundaries import city_tags, member, relation, ring

from streetfill.boundaries import area_lengths, assign_areas, total_length
from streetfill.cli import CITY_CONFIG_KEYS, apply_city_config, build_parser, main
from streetfill.osm_boundaries import PlacePoint, approximate_regions, place_points

FIXTURE = Path(__file__).parent / "fixtures" / "mini_area.json"
CITIES = Path(__file__).parent.parent / "cities"
CITY = rect("city", -150, -60, 330, 150)


def site(i, name, x, y, kind="neighbourhood"):
    return PlacePoint(f"node/{i}", name, kind, PROJ.to_latlon((x, y)))


def shoelace(ring_latlon):
    xy = [PROJ.to_xy(p) for p in ring_latlon]
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(xy, xy[1:]))) / 2


def contains(area, p):
    from streetfill.boundaries import _BoundaryIndex

    return bool(_BoundaryIndex([area], PROJ).areas_at(p))


def test_voronoi_cells_tile_the_city_box():
    sites = [site(1, "A", -100, 0), site(2, "B", 100, 100), site(3, "C", 250, -20), site(4, "Far", 5000, 0)]
    regions, kind = approximate_regions(sites, CITY, pad_m=0)
    assert kind == "place=neighbourhood points"
    assert [r.name for r in regions] == ["A", "B", "C"]  # Far is outside the city
    for r, s in zip(regions, sites):
        assert contains(r, PROJ.to_xy(s.point))
    assert sum(shoelace(r.rings[0]) for r in regions) == pytest.approx(480 * 210, rel=1e-6)


def test_regions_split_the_network_and_sum_to_the_city():
    sites = [site(1, "A", -100, 0), site(2, "B", 100, 100), site(3, "C", 250, -20)]
    regions, _ = approximate_regions(sites, CITY)
    out = assign_areas(GRID, city=CITY, neighborhoods=regions, projection=PROJ)
    lengths = area_lengths(out)
    assert None not in lengths and set(lengths) == {"node/1", "node/2", "node/3"}
    assert sum(lengths.values()) == pytest.approx(total_length(out), rel=1e-12)


def test_kind_preference_and_duplicates():
    sites = [site(1, "Lone", 0, 0), site(2, "S1", -100, 0, "suburb"), site(3, "S2", 200, 0, "suburb"),
             site(4, "S2 again", 200, 0, "suburb")]
    regions, kind = approximate_regions(sites, CITY)
    assert kind == "place=suburb points"  # one neighbourhood is not enough
    assert [r.name for r in regions] == ["S1", "S2"]  # a second place at the same point is dropped
    assert approximate_regions(sites[:1], CITY) == ([], None)


def test_place_points_from_overpass():
    doc = {"elements": [
        {"type": "node", "id": 9, "lat": 41.9, "lon": -87.6, "tags": {"place": "suburb", "name": "Nine"}},
        {"type": "node", "id": 3, "lat": 41.8, "lon": -87.6, "tags": {"place": "neighbourhood", "name": "Three"}},
        {"type": "node", "id": 4, "lat": 41.8, "lon": -87.6, "tags": {"place": "neighbourhood"}},  # no name
        {"type": "node", "id": 5, "lat": 41.8, "lon": -87.6, "tags": {"place": "city", "name": "Big"}},
    ]}
    assert [(p.id, p.kind) for p in place_points(doc)] == [("node/3", "neighbourhood"), ("node/9", "suburb")]


# --- build-pack -------------------------------------------------------------------

def points_doc():
    nodes = [(1, 41.896, -87.648, "South"), (2, 41.900, -87.648, "North")]
    return {"elements": [
        relation(100, city_tags("Test City"), member(ring(41.89, 41.902))),
        *({"type": "node", "id": i, "lat": lat, "lon": lon, "tags": {"place": "neighbourhood", "name": n}}
          for i, lat, lon, n in nodes),
    ]}


def build(tmp_path, *extra):
    b = tmp_path / "b.json"
    b.write_text(json.dumps(points_doc()))
    out = tmp_path / "pack.sqlite"
    rc = main(["build-pack", "--osm-json", str(FIXTURE), "--out", str(out), "--osm-boundaries", str(b), *extra])
    return rc, out


def test_build_pack_falls_back_to_approximate_regions(tmp_path, capsys):
    rc, out = build(tmp_path)
    assert rc == 0
    assert "approximate neighborhoods around OpenStreetMap place=neighbourhood points: 2" in capsys.readouterr().out
    con = sqlite3.connect(out)
    assert [n for (n,) in con.execute("SELECT name FROM neighborhoods ORDER BY id")] == ["South", "North"]
    meta = dict(con.execute("SELECT key, value FROM meta"))
    assert meta["neighborhood_source"] == "OpenStreetMap place=neighbourhood points, approximate regions"
    assert float(meta["unassigned_street_length_m"]) == 0


def test_approximate_regions_can_be_turned_off(tmp_path, capsys):
    rc, out = build(tmp_path, "--no-approximate-regions")
    assert rc == 0
    assert "the pack has none" in capsys.readouterr().err
    assert sqlite3.connect(out).execute("SELECT count(*) FROM neighborhoods").fetchone() == (0,)


# --- city config ------------------------------------------------------------------

def test_city_config_fills_unset_options(tmp_path, capsys):
    shutil.copy(FIXTURE, tmp_path / "area.json")
    (tmp_path / "b.json").write_text(json.dumps(points_doc()))
    cfg = tmp_path / "town.json"
    cfg.write_text(json.dumps({"name": "Config Town", "osm_json": "area.json", "osm_boundaries": "b.json",
                               "neighborhood_source": "from config"}))
    out = tmp_path / "pack.sqlite"
    assert main(["build-pack", "--city-config", str(cfg), "--out", str(out), "--city-name", "Cli Town"]) == 0
    meta = dict(sqlite3.connect(out).execute("SELECT key, value FROM meta"))
    assert meta["city_name"] == "Cli Town"  # the command line wins
    assert meta["neighborhood_source"] == "from config"  # relative paths resolved next to the config

    cfg.write_text(json.dumps({"nmae": "typo"}))
    assert main(["build-pack", "--city-config", str(cfg), "--out", str(out)]) == 2
    assert "unknown keys ['nmae']" in capsys.readouterr().err


def test_shipped_city_configs_are_valid():
    configs = sorted(CITIES.glob("*.json"))
    assert configs, "expected at least the launch city"
    for path in configs:
        cfg = json.loads(path.read_text())
        assert set(cfg) <= CITY_CONFIG_KEYS.keys() | {"comment"}
        args = build_parser().parse_args(["build-pack", "--city-config", str(path), "--out", "x"])
        apply_city_config(args)
        assert args.bbox and args.admin_level == "8" and isinstance(args, argparse.Namespace)
