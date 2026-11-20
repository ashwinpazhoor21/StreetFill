"""Named highlights from OpenStreetMap (plan F5, 6.6). Synthetic features only."""

import json
import sqlite3
from pathlib import Path

import pytest
from test_matcher import GRID, PROJ

from streetfill.cli import main
from streetfill.highlights import category, extract, score
from streetfill.overpass import build_feature_query
from streetfill.pack import write_pack

FIXTURE = Path(__file__).parent / "fixtures" / "mini_area.json"


def geom(*xy):
    return [dict(zip(("lat", "lon"), PROJ.to_latlon(p))) for p in xy]


def square(x, y, side):
    return geom((x, y), (x + side, y), (x + side, y + side), (x, y + side), (x, y))


def node(nid, x, y, **tags):
    lat, lon = PROJ.to_latlon((x, y))
    return {"type": "node", "id": nid, "lat": lat, "lon": lon, "tags": tags}


def way(wid, geometry, **tags):
    return {"type": "way", "id": wid, "geometry": geometry, "tags": tags}


def doc(*elements):
    return {"elements": list(elements)}


def by_name(highlights):
    return {h.name: h for h in highlights}


def test_categories():
    assert category({"natural": "beach"}) == "beach"
    assert category({"leisure": "park"}) == "park"
    assert category({"man_made": "pier"}) == category({"amenity": "fountain"}) == "water"
    assert category({"historic": "memorial"}) == "historic"
    assert category({"historic": "no", "tourism": "museum"}) == "landmark"
    for t in ("attraction", "viewpoint", "artwork", "museum"):
        assert category({"tourism": t}) == "landmark"
    assert category({"man_made": "lighthouse"}) == category({"bridge:name": "X"}) == "landmark"
    assert category({"tourism": "hotel"}) is None and category({"amenity": "cafe"}) is None


def test_points_sizes_and_radii():
    hs = by_name(extract(doc(
        way(1, square(0, 0, 200), natural="beach", name="Oak Beach"),  # 4 ha polygon
        way(2, square(500, 0, 150), leisure="park", name="Big Park"),  # 2.25 ha
        way(3, square(900, 0, 50), leisure="park", name="Pocket Park"),  # 0.25 ha: too small
        way(4, geom((0, 300), (0, 500)), man_made="pier", name="Navy Pier"),  # a 200 m line
        node(5, 50, 50, tourism="artwork", name="Cloud Sculpture"),
        node(6, 60, 60, tourism="artwork"),  # unnamed: skipped
    )))
    assert set(hs) == {"Oak Beach", "Big Park", "Navy Pier", "Cloud Sculpture"}
    beach = hs["Oak Beach"]
    assert beach.size_m2 == pytest.approx(40_000, rel=1e-3) and beach.radius_m == 150
    x, y = PROJ.to_xy(beach.point)
    assert 0 < x < 200 and 0 < y < 200  # a point inside the polygon
    pier = hs["Navy Pier"]
    assert PROJ.to_xy(pier.point) == pytest.approx((0, 400), abs=0.1)  # the line's midpoint
    assert pier.size_m2 == pytest.approx(2000, rel=1e-3) and pier.radius_m == 60 and pier.category == "water"
    assert hs["Cloud Sculpture"].size_m2 == 0 and hs["Big Park"].radius_m == 150


def test_multipolygon_park_with_a_hole():
    rel = {
        "type": "relation", "id": 9, "tags": {"type": "multipolygon", "leisure": "park", "name": "Ring Park"},
        "members": [
            {"type": "way", "ref": 1, "role": "outer", "geometry": square(0, 0, 300)},
            {"type": "way", "ref": 2, "role": "inner", "geometry": square(100, 100, 100)},
        ],
    }
    (h,) = extract(doc(rel))
    assert h.osm_id == "relation/9" and h.size_m2 == pytest.approx(80_000, rel=1e-3)
    x, y = PROJ.to_xy(h.point)
    assert not (100 < x < 200 and 100 < y < 200)  # not in the hole


def test_score_order_limit_and_duplicates():
    hs = extract(doc(
        node(1, 0, 0, tourism="museum", name="Art Museum"),
        way(2, square(-20, -20, 40), tourism="museum", name="Art  museum", wikidata="Q1"),  # same place, better
        node(3, 5000, 0, tourism="museum", name="Art Museum"),  # same name, far away: a different place
        node(4, 100, 0, historic="monument", name="Old Gate", image="https://example.org/x.jpg"),
        node(5, 200, 0, tourism="viewpoint", name="Lookout"),
    ))
    # node/1 is the same museum as way/2 (name compared ignoring case and spacing) and is merged into it;
    # node/3 has the same name 5 km away, so it is a different place. Ties are ordered by id.
    assert [h.osm_id for h in hs] == ["way/2", "node/4", "node/3", "node/5"]
    assert hs[0].wikidata == "Q1" and hs[0].score > hs[1].score > hs[-1].score
    assert len(extract(doc(*(node(i, i * 300, 0, tourism="artwork", name=f"A{i}") for i in range(10))), limit=3)) == 3
    assert score(1_000_000, {}) == 1.0 and score(0, {"wikidata": "Q", "wikimedia_commons": "File:x"}) == 3.0


def test_only_inside_the_city():
    from test_boundaries import rect

    hs = extract(doc(node(1, 50, 50, tourism="artwork", name="In"), node(2, 5000, 50, tourism="artwork", name="Out")),
                 city=rect("c", 0, 0, 1000, 1000))
    assert [h.name for h in hs] == ["In"]


def test_pack_stores_highlights(tmp_path):
    hs = extract(doc(way(1, square(0, 0, 200), natural="beach", name="Oak Beach", wikidata="Q7"),
                     node(2, 50, 50, tourism="artwork", name="Cloud")))
    pack = tmp_path / "p.sqlite"
    meta = write_pack(GRID, pack, highlights=hs, highlight_source="OpenStreetMap")
    assert meta["schema_version"] == "7" and meta["highlight_count"] == "2"
    con = sqlite3.connect(pack)
    rows = con.execute("SELECT id, osm_id, name, category, radius_m, wikidata, photo_url FROM highlights ORDER BY id").fetchall()
    assert rows == [(1, "way/1", "Oak Beach", "beach", 150.0, "Q7", None), (2, "node/2", "Cloud", "landmark", 60.0, None, None)]
    with pytest.raises(sqlite3.IntegrityError):  # a photo is never stored without its author and licence
        con.execute("UPDATE highlights SET photo_url = 'https://cdn.example/x.jpg' WHERE id = 1")


def test_build_pack_with_features(tmp_path, capsys):
    features = tmp_path / "features.json"
    lat, lon = 41.9, -87.648  # inside the fixture's area
    features.write_text(json.dumps(doc(
        {"type": "node", "id": 1, "lat": lat, "lon": lon, "tags": {"tourism": "artwork", "name": "Cloud"}},
        {"type": "node", "id": 2, "lat": lat, "lon": lon + 0.001, "tags": {"historic": "memorial", "name": "Stone"}},
    )))
    out = tmp_path / "pack.sqlite"
    assert main(["build-pack", "--osm-json", str(FIXTURE), "--out", str(out), "--osm-features", str(features)]) == 0
    assert "2 highlights (1 historic, 1 landmark); photos not resolved yet" in capsys.readouterr().out
    meta = dict(sqlite3.connect(out).execute("SELECT key, value FROM meta"))
    assert meta["highlight_count"] == "2" and meta["highlight_source"] == "OpenStreetMap"
    assert main(["build-pack", "--osm-json", str(FIXTURE), "--out", str(out)]) == 0
    assert dict(sqlite3.connect(out).execute("SELECT key, value FROM meta"))["highlight_count"] == "0"


def test_feature_query(capsys):
    q = build_feature_query((41.89, -87.66, 41.91, -87.64))
    assert q.endswith("out geom;") and '["natural"="beach"]["name"]' in q and "way[\"bridge:name\"]" in q
    assert main(["feature-query", "--bbox", "41.89,-87.66,41.91,-87.64"]) == 0
    assert capsys.readouterr().out.strip() == q
