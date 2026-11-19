"""Boundaries from OpenStreetMap: ring assembly, city and neighborhood selection. Synthetic data only."""

import json
import sqlite3
from pathlib import Path

import pytest

from streetfill import overpass
from streetfill.cli import main
from streetfill.osm_boundaries import assemble_rings, find_city, find_neighborhoods, osm_areas

FIXTURE = Path(__file__).parent / "fixtures" / "mini_area.json"  # lat 41.894-41.907, lon -87.65 to -87.6461
W, E = -87.66, -87.64


def pt(lat, lon):
    return {"lat": lat, "lon": lon}


def ring(south, north, west=W, east=E):
    return [pt(south, west), pt(south, east), pt(north, east), pt(north, west), pt(south, west)]


def relation(rid, tags, *members):
    return {"type": "relation", "id": rid, "tags": tags, "members": list(members)}


def member(geom, role="outer", ref=0):
    return {"type": "way", "ref": ref, "role": role, "geometry": geom}


def place_way(wid, kind, name, south, north):
    return {"type": "way", "id": wid, "tags": {"place": kind, "name": name}, "geometry": ring(south, north)}


def city_tags(name, level="8"):
    return {"type": "boundary", "boundary": "administrative", "admin_level": level, "name": name}


def boundary_doc():
    city = ring(41.89, 41.902)
    return {
        "elements": [
            # the city outline in two pieces, the second one reversed
            relation(100, city_tags("Test City"), member(city[:3], ref=1), member(list(reversed(city[2:])), ref=2)),
            relation(101, city_tags("Other Town"), member(ring(42.0, 42.1))),
            relation(102, {"type": "boundary", "boundary": "administrative", "admin_level": "8"},
                     member(ring(41.0, 41.1)[:3])),  # broken: does not close
            relation(103, {"type": "multipolygon", "place": "suburb", "name": "Whole Side"},
                     member(ring(41.89, 41.902)), member(ring(41.895, 41.896, -87.649, -87.648), role="inner")),
            place_way(10, "neighbourhood", "South End", 41.89, 41.898),
            place_way(11, "neighbourhood", "North End", 41.898, 41.902),
            place_way(12, "neighbourhood", "Elsewhere", 42.0, 42.05),
        ]
    }


def test_assemble_rings_joins_reversed_pieces():
    a, b, c, d = (0, 0), (0, 1), (1, 1), (1, 0)
    (r,) = assemble_rings([[a, b], [c, b], [c, d], [d, a]])  # the second piece runs backwards
    assert r == (a, b, c, d, a)
    with pytest.raises(ValueError, match="does not close"):
        assemble_rings([[a, b], [b, c]])
    # a closed way touching an open piece stays a ring of its own
    loop = [b, (5, 5), (5, 6), b]
    rings = assemble_rings([[a, b], loop, [b, c, d, a]])
    assert rings == [(a, b, c, d, a), tuple(loop)]


def test_osm_areas_skip_broken_relations_and_keep_holes():
    areas = {a.area.id: a for a in osm_areas(boundary_doc())}
    assert "relation/102" not in areas
    assert areas["relation/100"].area.name == "Test City" and len(areas["relation/100"].area.rings) == 1
    assert len(areas["relation/103"].area.rings) == 2  # outer plus the inner hole
    assert areas["way/10"].area.name == "South End"


def test_osm_areas_without_inline_geometry():
    nodes = [(1, 41.0, -87.0), (2, 41.0, -86.9), (3, 41.1, -86.9), (4, 41.1, -87.0)]
    doc = {
        "elements": [
            *({"type": "node", "id": i, "lat": lat, "lon": lon} for i, lat, lon in nodes),
            {"type": "way", "id": 7, "nodes": [1, 2, 3]},
            {"type": "way", "id": 8, "nodes": [3, 4, 1]},
            {"type": "relation", "id": 9, "tags": city_tags("Plain"),
             "members": [{"type": "way", "ref": 7, "role": "outer"}, {"type": "way", "ref": 8, "role": "outer"}]},
        ]
    }
    (area,) = [a.area for a in osm_areas(doc)]
    assert area.id == "relation/9" and len(area.rings[0]) == 5


def test_find_city_by_point_or_name():
    areas = osm_areas(boundary_doc())
    assert find_city(areas, point=(41.9, -87.648)).name == "Test City"
    assert find_city(areas, name="other town").name == "Other Town"
    assert find_city(areas, point=(45.0, -80.0)) is None
    assert find_city(areas, admin_level="9", point=(41.9, -87.648)) is None


def test_find_neighborhoods_inside_the_city():
    areas = osm_areas(boundary_doc())
    city = find_city(areas, point=(41.9, -87.648))
    hoods, kind = find_neighborhoods(areas, city)
    assert kind == "place=neighbourhood"
    assert [h.name for h in hoods] == ["South End", "North End"]  # Elsewhere is outside the city

    # one neighbourhood is not enough, and neither is one suburb
    sparse = [a for a in areas if a.area.id != "way/11"]
    assert find_neighborhoods(sparse, city) == ([], None)
    # with two suburbs, those are used
    extra = osm_areas({"elements": [place_way(20, "suburb", "Lower Side", 41.89, 41.895)]})
    hoods, kind = find_neighborhoods(sparse + extra, city)
    assert kind == "place=suburb" and sorted(h.name for h in hoods) == ["Lower Side", "Whole Side"]
    assert find_neighborhoods([a for a in areas if a.area.id == "relation/100"], city) == ([], None)


def test_inside_point_handles_concave_shapes():
    # a U shape whose vertex mean falls in the notch, outside the polygon
    u = [pt(0, 0), pt(0, 3), pt(3, 3), pt(3, 2), pt(1, 2), pt(1, 1), pt(3, 1), pt(3, 0), pt(0, 0)]
    city = {"type": "way", "id": 1, "tags": city_tags("Big", "8"), "geometry": ring(-1, 4, -1, 4)}
    hoods = [
        {"type": "way", "id": 2, "tags": {"place": "neighbourhood", "name": "U"}, "geometry": u},
        {"type": "way", "id": 3, "tags": {"place": "neighbourhood", "name": "Box"}, "geometry": ring(3.5, 3.9, 3.5, 3.9)},
    ]
    areas = osm_areas({"elements": [city, *hoods]})
    big = next(a.area for a in areas if a.area.name == "Big")
    found, _ = find_neighborhoods(areas, big)
    assert [h.name for h in found] == ["U", "Box"]


# --- build-pack -------------------------------------------------------------------

def run_build(tmp_path, *extra):
    bdoc = tmp_path / "boundaries.json"
    bdoc.write_text(json.dumps(boundary_doc()))
    out = tmp_path / "pack.sqlite"
    rc = main(["build-pack", "--osm-json", str(FIXTURE), "--out", str(out), "--osm-boundaries", str(bdoc), *extra])
    con = sqlite3.connect(out) if rc == 0 else None
    return rc, con


def test_build_pack_takes_city_and_neighborhoods_from_osm(tmp_path, capsys):
    rc, con = run_build(tmp_path)
    assert rc == 0
    printed = capsys.readouterr().out
    assert "neighborhoods from OpenStreetMap: 2 (place=neighbourhood)" in printed
    assert "clipped to Test City" in printed
    meta = dict(con.execute("SELECT key, value FROM meta"))
    assert meta["city_source"] == "OpenStreetMap (relation/100)"
    assert meta["neighborhood_source"] == "OpenStreetMap (place=neighbourhood)"
    assert con.execute("SELECT key, name FROM neighborhoods ORDER BY id").fetchall() == [
        ("way/10", "South End"),
        ("way/11", "North End"),
    ]


def test_geojson_options_take_precedence_over_osm(tmp_path, capsys):
    hoods = tmp_path / "official.geojson"
    coords = [[[W, 41.89], [E, 41.89], [E, 41.91], [W, 41.91], [W, 41.89]]]
    hoods.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"id": "A", "name": "All"},
         "geometry": {"type": "Polygon", "coordinates": coords}}]}))
    rc, con = run_build(tmp_path, "--neighborhoods", str(hoods), "--neighborhood-source", "city open data")
    assert rc == 0
    assert con.execute("SELECT key FROM neighborhoods").fetchall() == [("A",)]
    meta = dict(con.execute("SELECT key, value FROM meta"))
    assert meta["neighborhood_source"] == "city open data" and meta["city_name"] == "Test City"


def test_build_pack_without_a_matching_city_warns(tmp_path, capsys):
    rc, con = run_build(tmp_path, "--city-osm-name", "Nowhere")
    assert rc == 0
    assert "no OSM admin_level=8 boundary named 'Nowhere'" in capsys.readouterr().err
    assert "city_name" not in dict(con.execute("SELECT key, value FROM meta"))


def test_fetch_boundaries_with_bbox(tmp_path, monkeypatch, capsys):
    streets = json.loads(FIXTURE.read_text())
    calls = []

    def fake_fetch(bbox, url, query=None):
        calls.append(query)
        return boundary_doc() if query else streets

    monkeypatch.setattr(overpass, "fetch", fake_fetch)
    saved = tmp_path / "b.json"
    rc = main(["build-pack", "--bbox", "41.894,-87.65,41.907,-87.6461", "--out", str(tmp_path / "p.sqlite"),
               "--fetch-boundaries", "--save-boundaries", str(saved)])
    assert rc == 0
    assert calls[0] is None and "out geom" in calls[1]
    assert json.loads(saved.read_text()) == boundary_doc()


def test_boundary_query(capsys):
    assert main(["boundary-query", "--bbox", "41.89,-87.66,41.91,-87.64"]) == 0
    q = capsys.readouterr().out
    assert '"admin_level"~"^(8|9|10)$"' in q and "(41.89,-87.66,41.91,-87.64)" in q and "out geom" in q
