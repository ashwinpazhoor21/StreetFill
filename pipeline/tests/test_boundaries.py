"""Clipping to a city boundary and splitting by neighborhood (plan 5.6). Synthetic shapes only."""

import json

import pytest
from test_matcher import GRID, PROJ, make_network

from streetfill.boundaries import (
    Area,
    _BoundaryIndex,
    _cut_positions,
    area_from_geojson,
    area_lengths,
    assign_areas,
    load_areas,
    total_length,
)


def rect(area_id, x0, y0, x1, y1, holes=()):
    def ring(a, b, c, d):
        return tuple(PROJ.to_latlon(p) for p in [(a, b), (c, b), (c, d), (a, d), (a, b)])

    return Area(area_id, area_id.title(), (ring(x0, y0, x1, y1), *(ring(*h) for h in holes)))


def xy(p):
    x, y = PROJ.to_xy(p)
    return round(x, 3), round(y, 3)


def assign(net, **kw):
    return assign_areas(net, projection=PROJ, **kw)


CITY = rect("city", 0, -100, 200, 100)
WEST, EAST = rect("west", 0, -100, 100, 100), rect("east", 100, -100, 200, 100)


def test_edge_is_cut_where_it_crosses_the_city_boundary():
    net = make_network([(1, "Long Road", "residential", [(-100, 0), (300, 0)])])
    out = assign(net, city=CITY)
    (e,) = out.edges
    assert xy(e.coords[0]) == (0, 0) and xy(e.coords[-1]) == (200, 0)
    assert e.length_m == pytest.approx(200, rel=1e-6)
    assert e.from_node < 0 and e.to_node < 0  # new nodes at the crossings
    assert out.streets[0].length_m == pytest.approx(200, rel=1e-6)
    assert out.streets[0].edge_ids == [1]


def test_edges_and_streets_outside_the_city_are_dropped():
    net = make_network(
        [
            (1, "Inside Street", "residential", [(20, 20), (180, 20)]),
            (2, "Outside Street", "residential", [(20, 500), (180, 500)]),
        ]
    )
    out = assign(net, city=CITY)
    assert [s.name for s in out.streets] == ["Inside Street"]
    (e,) = out.edges
    assert e.node_ids == net.edges[0].node_ids  # untouched edges keep their OSM nodes
    assert e.neighborhood is None


def test_neighborhoods_split_edges_and_sum_to_the_city_total():
    net = make_network([(1, "Long Road", "residential", [(-100, 0), (300, 0)])])
    out = assign(net, city=CITY, neighborhoods=[WEST, EAST])
    west, east = out.edges
    assert (west.neighborhood, east.neighborhood) == ("west", "east")
    assert west.length_m == pytest.approx(100, rel=1e-6) and east.length_m == pytest.approx(100, rel=1e-6)
    assert west.to_node == east.from_node < 0  # the two pieces share the new node
    assert [e.id for e in out.edges] == [1, 2]
    lengths = area_lengths(out)
    assert None not in lengths
    assert sum(lengths.values()) == pytest.approx(total_length(out), rel=1e-12)


def test_way_weaving_in_and_out():
    pts = [(-50, 0), (50, 0), (50, 150), (150, 150), (150, 0), (250, 0)]  # leaves the city at y=100
    net = make_network([(1, "Loop Road", "residential", pts)])
    out = assign(net, city=CITY)
    assert len(out.edges) == 2
    assert sum(e.length_m for e in out.edges) == pytest.approx(50 + 100 + 100 + 50, rel=1e-6)


def test_holes_are_outside():
    city = rect("city", 0, -100, 200, 100, holes=[(80, -20, 120, 20)])  # a park in the middle
    net = make_network([(1, "Long Road", "residential", [(0.5, 0), (199.5, 0)])])
    out = assign(net, city=city)
    assert len(out.edges) == 2
    assert sum(e.length_m for e in out.edges) == pytest.approx(199 - 40, rel=1e-6)


def test_touching_a_boundary_at_a_vertex_does_not_split():
    net = make_network([(1, "Vee Street", "residential", [(50, 50), (100, 0), (50, -50)])])
    out = assign(net, city=CITY, neighborhoods=[WEST, EAST])
    (e,) = out.edges
    assert e.neighborhood == "west"
    assert e.node_ids == net.edges[0].node_ids


def test_without_a_city_everything_is_kept():
    net = make_network([(1, "Long Road", "residential", [(-100, 0), (300, 0)])])
    out = assign(net, neighborhoods=[WEST])
    assert [e.neighborhood for e in out.edges] == [None, "west", None]
    assert total_length(out) == pytest.approx(400, rel=1e-6)


def test_overlapping_neighborhoods_first_one_wins():
    net = make_network([(1, "Short Road", "residential", [(20, 0), (80, 0)])])
    out = assign(net, neighborhoods=[rect("a", 0, -50, 100, 50), rect("b", 0, -100, 200, 100)])
    assert [e.neighborhood for e in out.edges] == ["a"]


def test_grid_tiles_conserve_length():
    # 3 x 2 tiles not aligned with the grid's streets, covering the whole city
    city = rect("city", -150, -60, 330, 150)
    xs, ys = [-150, 10, 170, 330], [-60, 40, 150]
    tiles = [rect(f"t{i}{j}", xs[i], ys[j], xs[i + 1], ys[j + 1]) for i in range(3) for j in range(2)]
    clipped = assign(GRID, city=city)
    split = assign(GRID, city=city, neighborhoods=tiles)
    assert len(split.edges) > len(clipped.edges)
    assert total_length(split) == pytest.approx(total_length(clipped), rel=1e-9)
    lengths = area_lengths(split)
    assert None not in lengths and len(lengths) == 6
    assert sum(lengths.values()) == pytest.approx(total_length(split), rel=1e-12)
    for s in split.streets:
        assert s.length_m == pytest.approx(sum(e.length_m for e in split.edges if e.id in s.edge_ids))
    # deterministic: the same input gives the same output
    again = assign(GRID, city=city, neighborhoods=tiles)
    assert [(e.id, e.node_ids, e.neighborhood) for e in again.edges] == [
        (e.id, e.node_ids, e.neighborhood) for e in split.edges
    ]
    new_nodes = [n for e in split.edges for n in (e.from_node, e.to_node) if n < 0]
    assert new_nodes and all(n < 0 for n in new_nodes)


def test_load_areas_from_geojson(tmp_path):
    square = [[[-87.66, 41.89], [-87.64, 41.89], [-87.64, 41.91], [-87.66, 41.91], [-87.66, 41.89]]]
    doc = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"id": 8, "name": "Lincoln Park"},
             "geometry": {"type": "Polygon", "coordinates": square}},
            {"type": "Feature", "properties": {},
             "geometry": {"type": "MultiPolygon", "coordinates": [square, square]}},
        ],
    }
    path = tmp_path / "hoods.geojson"
    path.write_text(json.dumps(doc))
    a, b = load_areas(path)
    assert (a.id, a.name) == ("8", "Lincoln Park")
    assert a.rings[0][0] == (41.89, -87.66)  # GeoJSON is lon, lat
    assert (b.id, b.name, len(b.rings)) == ("2", "2", 2)

    doc["features"][1]["properties"] = {"id": 8}
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="duplicate"):
        load_areas(path)
    with pytest.raises(ValueError, match="Polygon"):
        area_from_geojson({"type": "Point", "coordinates": [0, 0]}, "x")


def test_crossing_at_a_boundary_vertex_makes_no_sliver():
    # both ring segments meeting at a vertex report (almost) the same crossing
    pts = [(13.7, 0), (100, 71.3), (186.1, 0), (100, -63.9), (13.7, 0)]
    diamond = Area("d", "D", (tuple(PROJ.to_latlon(p) for p in pts),))
    for y in (0.0, 1e-9):
        net = make_network([(1, "Long Road", "residential", [(-50.3, y), (250.9, y)])])
        out = assign(net, city=diamond)
        assert len(out.edges) == 1
        assert out.edges[0].length_m == pytest.approx(186.1 - 13.7, rel=1e-6)
        out = assign(net, neighborhoods=[diamond])
        assert [e.neighborhood for e in out.edges] == [None, "d", None]
        assert min(e.length_m for e in out.edges) > 1
        line_xy = [PROJ.to_xy(p) for p in net.edges[0].coords]
        assert len(_cut_positions(line_xy, _BoundaryIndex([diamond], PROJ))) == 2  # one cut per vertex
