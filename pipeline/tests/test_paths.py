"""Path and trail layer (plan 5.2). Synthetic data only."""

import pytest

from streetfill.geo import LocalProjection
from streetfill.matcher import Matcher
from streetfill.network import build_network
from streetfill.osm import OsmData, Way, way_layer
from streetfill.overpass import build_query
from streetfill.pack import write_pack

PROJ = LocalProjection(41.9, -87.65)


@pytest.mark.parametrize(
    "tags, layer",
    [
        ({"highway": "residential"}, "street"),
        ({"highway": "footway"}, "path"),
        ({"highway": "path"}, "path"),
        ({"highway": "track"}, "path"),
        ({"highway": "cycleway"}, "path"),  # no foot tag: open, the usual US default
        ({"highway": "cycleway", "foot": "designated"}, "path"),
        ({"highway": "bridleway", "foot": "yes"}, "path"),
        ({"highway": "steps"}, "steps"),
        ({"highway": "footway", "footway": "sidewalk"}, None),
        ({"highway": "footway", "footway": "crossing"}, None),
        ({"highway": "path", "footway": "sidewalk"}, None),
        ({"highway": "cycleway", "foot": "no"}, None),
        ({"highway": "bridleway"}, None),
        ({"highway": "footway", "access": "private"}, None),
        ({"highway": "footway", "tunnel": "yes"}, None),
        ({"highway": "footway", "indoor": "yes"}, None),
        ({"highway": "footway", "area": "yes"}, None),
        ({"highway": "steps", "access": "no"}, None),
        ({"highway": "service"}, None),
    ],
)
def test_way_layer(tags, layer):
    assert way_layer(tags) == layer


def make(lines):
    nodes, ways, ids = {}, [], {}
    for way_id, tags, pts in lines:
        nids = []
        for xy in pts:
            if xy not in ids:
                ids[xy] = len(ids) + 1
                nodes[ids[xy]] = PROJ.to_latlon(xy)
            nids.append(ids[xy])
        ways.append(Way(way_id, tuple(nids), tags))
    return OsmData(nodes, ways)


# A lakefront drive with a named trail beside it, a connector path that touches the
# drive mid-block, a footway crossing the trail, steps, and a sidewalk.
LAKEFRONT = make(
    [
        (1, {"highway": "secondary", "name": "Lake Drive"}, [(0, 0), (100, 0), (200, 0)]),
        (2, {"highway": "cycleway", "name": "Lakefront Trail", "foot": "designated"}, [(0, 25), (100, 25), (200, 25)]),
        (3, {"highway": "cycleway", "name": "lakefront  trail"}, [(200, 25), (300, 25)]),
        (4, {"highway": "footway"}, [(100, 0), (100, 25), (100, 60)]),
        (5, {"highway": "steps"}, [(100, 60), (110, 70)]),
        (6, {"highway": "footway", "footway": "sidewalk"}, [(0, -8), (200, -8)]),
        (7, {"highway": "path", "name": "Lake Drive"}, [(300, 25), (400, 25)]),
    ]
)


def edges_of(net, way_id):
    return [(e.from_node, e.to_node) for e in net.edges if e.way_id == way_id]


def test_paths_do_not_split_streets():
    net = build_network(LAKEFRONT)
    assert edges_of(net, 1) == [(1, 3)]  # the connector touching node 2 leaves the street whole
    assert [e.layer for e in net.edges if e.way_id == 1] == ["street"]


def test_paths_split_at_paths_and_streets():
    net = build_network(LAKEFRONT)
    assert len(edges_of(net, 2)) == 2  # split where the connector crosses the trail
    assert len(edges_of(net, 4)) == 2  # split at the trail; ends at the street and the steps


def test_named_paths_become_trails_and_never_merge_with_streets():
    net = build_network(LAKEFRONT)
    keys = {s.key: s for s in net.streets}
    trail = keys["trail:lakefront trail"]
    assert trail.layer == "path" and trail.name == "Lakefront Trail"
    assert len(trail.edge_ids) == 3  # both OSM ways, case and spacing ignored
    assert keys["name:lake drive"].layer == "street"
    assert keys["trail:lake drive"].layer == "path"  # same name, different layer
    assert keys["path:way:4"].name is None
    assert keys["steps:way:5"].layer == "steps"
    assert not any(k.endswith(":6") for k in keys)  # sidewalk left out


def test_layer_filter():
    net = build_network(LAKEFRONT, layers=("street",))
    assert {e.layer for e in net.edges} == {"street"}
    assert len(net.streets) == 1


def test_pack_layers_and_matcher_layers(tmp_path):
    net = build_network(LAKEFRONT)
    meta = write_pack(net, tmp_path / "p.sqlite")
    street_m = sum(e.length_m for e in net.edges if e.layer == "street")
    path_m = sum(e.length_m for e in net.edges if e.layer == "path")
    assert float(meta["street_length_m"]) == pytest.approx(street_m, abs=0.01)
    assert float(meta["path_length_m"]) == pytest.approx(path_m, abs=0.01)
    assert float(meta["total_length_m"]) > street_m + path_m  # steps count in total only
    m = Matcher.from_pack(tmp_path / "p.sqlite")
    assert {e.layer for e in m.edges.values()} == {"street", "path"}
    assert "steps" not in {e.highway for e in m.edges.values()}  # routable only, never matched


def test_overpass_query_includes_paths():
    q = build_query((41.89, -87.66, 41.91, -87.64))
    for cls in ("footway", "path", "cycleway", "track", "bridleway", "steps", "residential"):
        assert cls in q
    assert "motorway" not in q and "service" not in q
