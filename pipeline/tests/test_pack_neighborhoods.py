"""Neighborhoods and the city boundary in packs (schema v3) and in build-pack. Synthetic data only."""

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from test_boundaries import rect
from test_matcher import GRID, PROJ

from streetfill.boundaries import area_lengths, assign_areas
from streetfill.cli import main
from streetfill.matcher import Matcher
from streetfill.pack import write_pack

FIXTURE = Path(__file__).parent / "fixtures" / "mini_area.json"
CITY = rect("17", -150, -60, 330, 150)
HOODS = [rect("west", -150, -60, 100, 150), rect("east", 100, -60, 250, 150)]  # x > 250 is in neither


@pytest.fixture()
def split():
    return assign_areas(GRID, city=CITY, neighborhoods=HOODS, projection=PROJ)


def rows(pack, sql):
    con = sqlite3.connect(pack)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def test_pack_stores_neighborhoods_and_their_lengths(split, tmp_path):
    pack = tmp_path / "p.sqlite"
    meta = write_pack(split, pack, city=CITY, city_source="test", neighborhoods=HOODS, neighborhood_source="test")
    assert meta["schema_version"] == "6" and meta["neighborhood_count"] == "2"
    assert (meta["city_id"], meta["city_name"]) == ("17", "17".title())

    lengths = area_lengths(split)
    hoods = rows(pack, "SELECT id, key, name, street_length_m, path_length_m FROM neighborhoods ORDER BY id")
    assert [(i, k) for i, k, *_ in hoods] == [(1, "west"), (2, "east")]
    for _, key, _, street_m, path_m in hoods:
        assert street_m == pytest.approx(lengths[key]) and path_m == 0
    assert float(meta["unassigned_street_length_m"]) == pytest.approx(lengths[None], abs=0.01)  # meta rounds to 1 cm
    total = sum(h[3] for h in hoods) + float(meta["unassigned_street_length_m"])
    assert total == pytest.approx(float(meta["street_length_m"]), abs=0.01)  # neighborhoods sum to the city

    # every edge's neighborhood_id matches the network, NULL where it is in none
    by_key = {k: i for i, k, *_ in hoods}
    stored = dict(rows(pack, "SELECT id, neighborhood_id FROM edges"))
    assert stored == {e.id: by_key.get(e.neighborhood) for e in split.edges}
    assert None in stored.values()

    ring = json.loads(rows(pack, "SELECT rings FROM neighborhoods WHERE key = 'west'")[0][0])[0]
    lat, lon = PROJ.to_latlon((-150, -60))
    assert ring[0] == [round(lon, 7), round(lat, 7)]  # GeoJSON order
    assert json.loads(meta["city_rings"])[0][0] == ring[0]

    Matcher.from_pack(pack)  # the matcher still reads a v3 pack


def test_pack_without_boundaries(tmp_path):
    meta = write_pack(GRID, tmp_path / "p.sqlite")
    assert meta["neighborhood_count"] == "0" and "city_name" not in meta
    assert rows(tmp_path / "p.sqlite", "SELECT count(*) FROM edges WHERE neighborhood_id IS NOT NULL") == [(0,)]


def test_unknown_neighborhood_is_rejected(split, tmp_path):
    with pytest.raises(ValueError, match="unknown neighborhoods"):
        write_pack(split, tmp_path / "p.sqlite", neighborhoods=HOODS[:1])
    with pytest.raises(ValueError, match="duplicate"):
        write_pack(split, tmp_path / "p.sqlite", neighborhoods=[HOODS[0], replace(HOODS[1], id="west")])


# --- build-pack -------------------------------------------------------------------

def box(south, west, north, east, **props):
    ring = [[west, south], [east, south], [east, north], [west, north], [west, south]]
    return {"type": "Feature", "properties": props, "geometry": {"type": "Polygon", "coordinates": [ring]}}


def collection(*features):
    return json.dumps({"type": "FeatureCollection", "features": list(features)})


def test_build_pack_with_city_and_neighborhoods(tmp_path, capsys):
    # the fixture spans latitude 41.894 to 41.907; the city keeps the part south of 41.902
    city = tmp_path / "city.geojson"
    city.write_text(collection(box(41.89, -87.66, 41.902, -87.64, name="Test City")))
    hoods = tmp_path / "hoods.geojson"
    hoods.write_text(
        collection(
            box(41.89, -87.66, 41.898, -87.64, area_num="1", community="South Side"),
            box(41.898, -87.66, 41.91, -87.64, area_num="2", community="North Side"),
        )
    )
    out = tmp_path / "pack.sqlite"
    args = ["build-pack", "--osm-json", str(FIXTURE), "--out", str(out), "--city", str(city),
            "--neighborhoods", str(hoods), "--neighborhood-id-property", "area_num",
            "--neighborhood-name-property", "community", "--neighborhood-source", "test data"]
    assert main(args) == 0
    printed = capsys.readouterr().out
    assert "clipped to Test City" in printed and "2 neighborhoods; 0.0% of street length" in printed

    assert rows(out, "SELECT key, name FROM neighborhoods ORDER BY id") == [("1", "South Side"), ("2", "North Side")]
    meta = dict(rows(out, "SELECT key, value FROM meta"))
    assert meta["city_name"] == "Test City" and meta["neighborhood_source"] == "test data"
    assert rows(out, "SELECT count(*) FROM edges WHERE layer = 'street' AND neighborhood_id IS NULL") == [(0,)]

    from streetfill.pack import decode_geometry

    lats = [lat for (blob,) in rows(out, "SELECT geometry FROM edges") for lat, _ in decode_geometry(blob)]
    assert max(lats) <= 41.902 + 1e-7 and min(lats) >= 41.894 - 1e-9


def test_build_pack_rejects_bad_boundaries(tmp_path, capsys):
    bad = tmp_path / "bad.geojson"
    bad.write_text(collection({"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [0, 0]}}))
    assert main(["build-pack", "--osm-json", str(FIXTURE), "--out", str(tmp_path / "p"), "--city", str(bad)]) == 2
    assert "Polygon" in capsys.readouterr().err
    far = tmp_path / "far.geojson"
    far.write_text(collection(box(10, 10, 11, 11)))
    assert main(["build-pack", "--osm-json", str(FIXTURE), "--out", str(tmp_path / "p"), "--city", str(far)]) == 1
    assert "inside the city boundary" in capsys.readouterr().err
