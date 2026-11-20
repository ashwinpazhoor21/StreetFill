"""Scenery flags per edge (plan 6.6). Synthetic features only."""

import json
import sqlite3
import time
from pathlib import Path

import pytest
from test_highlights import doc, geom, node, square, way
from test_matcher import PROJ, make_network

from streetfill.cli import main
from streetfill.scenery import (
    BEACH,
    HIGHLIGHT,
    PARK,
    WATER,
    _segment_distance,
    add_scenery,
    flag_names,
    scenery_features,
)

FIXTURE = Path(__file__).parent / "fixtures" / "mini_area.json"


def flags_by_street(net):
    return {e.street_key.split(":", 1)[1]: e.scenery for e in net.edges}


def street(i, name, y, x0=0, x1=100):
    return (i, name, "residential", [(x0, y), (x1, y)])


def test_segment_distance():
    assert _segment_distance((0, 0), (10, 0), (5, -5), (5, 5)) == 0  # crossing
    assert _segment_distance((0, 0), (10, 0), (0, 3), (10, 3)) == pytest.approx(3)  # parallel
    assert _segment_distance((0, 0), (10, 0), (13, 4), (20, 4)) == pytest.approx(5)  # end to end
    assert _segment_distance((0, 0), (10, 0), (4, 0), (6, 0)) == 0  # collinear overlap
    assert _segment_distance((0, 0), (10, 0), (5, 2), (5, 2)) == pytest.approx(2)  # a point


def test_thresholds_per_kind():
    # a park from y=0 to 200; streets above it at increasing distance
    park_doc = doc(way(1, square(0, 0, 200), leisure="park"))
    polygons, coast = scenery_features(park_doc)
    net = make_network([street(1, "Inside", 100), street(2, "Near", 249), street(3, "Far", 251, 0, 200)])
    flags = flags_by_street(add_scenery(net, polygons, coast, projection=PROJ))
    assert flags == {"inside": PARK, "near": PARK, "far": 0}  # park counts within 50 m


def test_water_beach_coastline_and_highlights():
    features = doc(
        way(1, square(0, 1000, 500), natural="water"),  # a lake
        way(2, square(0, 2000, 100), natural="beach"),  # unnamed beaches count
        way(3, geom((0, 3000), (1000, 3000)), natural="coastline"),
        way(4, square(0, 4000, 50), leisure="garden"),  # not scenery
    )
    polygons, coast = scenery_features(features)
    assert [len(polygons[k]) for k in (WATER, BEACH, PARK)] == [1, 1, 0] and len(coast) == 1
    net = make_network(
        [
            street(1, "Lake Shore", 920),  # 80 m from the lake
            street(2, "Lake Far", 890),  # 110 m
            street(3, "Beach Walk", 1960),  # 40 m from the beach, 460 m from the lake
            street(4, "Coast Road", 3090),  # 90 m from the coastline
            street(5, "Garden Row", 4025),  # inside a garden: nothing
            street(6, "Statue Lane", 5000),
        ]
    )
    statue = PROJ.to_latlon((50, 5070))
    flags = flags_by_street(add_scenery(net, polygons, coast, [statue], projection=PROJ))
    assert flags == {
        "lake shore": WATER,
        "lake far": 0,
        "beach walk": BEACH,
        "coast road": WATER,
        "garden row": 0,
        "statue lane": HIGHLIGHT,
    }
    assert flag_names(WATER | HIGHLIGHT) == ["water", "highlight"]


def test_pier_inside_the_lake_and_overlapping_parks():
    features = doc(
        way(1, square(0, 0, 2000), natural="water"),
        way(2, square(5000, 0, 300), leisure="park"),
        way(3, square(5100, 100, 300), leisure="park"),  # overlaps the first park
    )
    polygons, coast = scenery_features(features)
    net = make_network([street(1, "Pier", 1000, 900, 1100), street(2, "Overlap", 250, 5150, 5250)])
    flags = flags_by_street(add_scenery(net, polygons, coast, projection=PROJ))
    assert flags == {"pier": WATER, "overlap": PARK}  # far from any outline, but inside


def test_pack_and_build_pack(tmp_path, capsys):
    lat, lon = 41.9, -87.648  # inside the fixture's area
    d = 0.003
    ring = [{"lat": lat - d, "lon": lon - d}, {"lat": lat - d, "lon": lon + d}, {"lat": lat + d, "lon": lon + d},
            {"lat": lat + d, "lon": lon - d}, {"lat": lat - d, "lon": lon - d}]
    features = tmp_path / "features.json"
    features.write_text(json.dumps({"elements": [{"type": "way", "id": 1, "geometry": ring,
                                                  "tags": {"leisure": "park", "name": "Middle Park"}}]}))
    out = tmp_path / "pack.sqlite"
    assert main(["build-pack", "--osm-json", str(FIXTURE), "--out", str(out), "--osm-features", str(features)]) == 0
    printed = capsys.readouterr().out
    assert "scenery flags:" in printed and "park" in printed
    con = sqlite3.connect(out)
    flagged = con.execute("SELECT count(*) FROM edges WHERE scenery & 4").fetchone()[0]
    assert flagged > 0
    meta = dict(con.execute("SELECT key, value FROM meta"))
    assert meta["schema_version"] == "6" and int(meta["scenery_edges"]) >= flagged
    assert con.execute("SELECT count(*) FROM highlights WHERE category = 'park'").fetchone()[0] == 1


def test_city_sized_input_is_fast():
    # a 12 x 12 km grid of streets 100 m apart (about 29,000 edges), a 2,000-vertex lake shore and 400 parks
    xs = range(0, 12001, 100)
    lines = [(i + 1, f"H{i}", "residential", [(x, i * 100) for x in xs]) for i in range(121)]
    lines += [(1000 + i, f"V{i}", "residential", [(i * 100, y) for y in xs]) for i in range(121)]
    net = make_network(lines)
    assert len(net.edges) > 28000
    shore = [(x * 6.0, 6000 + 300 * ((x % 7) - 3) / 3) for x in range(2001)]
    lake = shore + [(12000, 20000), (0, 20000), shore[0]]
    feats = [way(1, geom(*lake), natural="water")]
    feats += [way(10 + k, square((k % 20) * 600 + 50, (k // 20) * 300 + 20, 60), leisure="park") for k in range(400)]
    polygons, coast = scenery_features(doc(*feats))
    start = time.perf_counter()
    out = add_scenery(net, polygons, coast, projection=PROJ)
    elapsed = time.perf_counter() - start
    assert sum(1 for e in out.edges if e.scenery & WATER) > 0
    assert elapsed < 20, f"{len(net.edges)} edges took {elapsed:.1f}s"
