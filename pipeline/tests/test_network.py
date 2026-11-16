from pathlib import Path

import pytest

from streetfill.geo import haversine_m
from streetfill.network import build_network, normalize_name
from streetfill.osm import OsmData, Way, load_overpass_file

FIXTURE = Path(__file__).parent / "fixtures" / "mini_area.json"


@pytest.fixture(scope="module")
def net():
    return build_network(load_overpass_file(FIXTURE))


def edge_nodes(net, way_id):
    return [(e.from_node, e.to_node) for e in net.edges if e.way_id == way_id]


def streets_by_key(net):
    return {s.key: s for s in net.streets}


def test_edge_count(net):
    assert len(net.edges) == 12
    assert [e.id for e in net.edges] == list(range(1, 13))


def test_splits_at_intersection_with_another_street(net):
    # Oak Street (way 100) is crossed by Elm Avenue at node 2 and continues as way 101 at node 3.
    assert edge_nodes(net, 100) == [(1, 2), (2, 3)]
    assert edge_nodes(net, 200) == [(5, 2), (2, 6)]


def test_excluded_ways_do_not_split(net):
    # The alley (way 300) crosses Oak Street at node 10, which stays a shape point.
    oak_first = next(e for e in net.edges if e.way_id == 100)
    assert oak_first.node_ids == [1, 10, 2]


def test_closed_way_is_one_loop_edge(net):
    assert edge_nodes(net, 313) == [(31, 31)]


def test_way_crossing_itself_splits_at_the_repeated_node(net):
    assert edge_nodes(net, 315) == [(40, 41), (41, 41)]


def test_missing_node_splits_instead_of_bridging(net):
    assert edge_nodes(net, 314) == [(34, 35), (36, 37)]


def test_named_ways_group_into_one_street(net):
    streets = streets_by_key(net)
    oak = streets["name:oak street"]
    assert oak.name == "Oak Street"
    assert len(oak.edge_ids) == 3
    assert oak.length_m == pytest.approx(sum(e.length_m for e in net.edges if e.street_key == oak.key))


def test_unnamed_way_is_its_own_street(net):
    streets = streets_by_key(net)
    assert streets["way:307"].name is None
    assert len(streets["way:307"].edge_ids) == 1


def test_street_keys_and_classes(net):
    streets = streets_by_key(net)
    assert set(streets) == {
        "name:oak street",
        "name:elm avenue",
        "name:lake shore drive",
        "name:circle court",
        "name:gap lane",
        "name:loop road",
        "way:307",
    }
    assert streets["name:lake shore drive"].highway == "trunk"
    assert streets["name:elm avenue"].highway == "tertiary"


def test_edge_length_matches_geometry(net):
    for e in net.edges:
        expected = sum(haversine_m(a, b) for a, b in zip(e.coords, e.coords[1:]))
        assert e.length_m == pytest.approx(expected)
        assert e.length_m > 0


def test_street_takes_the_highest_class_of_its_ways():
    nodes = {1: (0.0, 0.0), 2: (0.0, 0.001), 3: (0.0, 0.002)}
    ways = [
        Way(1, (1, 2), {"highway": "residential", "name": "Main St"}),
        Way(2, (2, 3), {"highway": "secondary", "name": "main  st"}),
    ]
    net = build_network(OsmData(nodes, ways))
    assert len(net.streets) == 1
    assert net.streets[0].highway == "secondary"
    assert net.streets[0].name == "Main St"


def test_zero_length_edges_are_dropped():
    nodes = {1: (0.0, 0.0), 2: (0.0, 0.0)}
    net = build_network(OsmData(nodes, [Way(1, (1, 2), {"highway": "residential"})]))
    assert net.edges == []
    assert net.streets == []


def test_output_is_deterministic():
    data = load_overpass_file(FIXTURE)
    a = build_network(data)
    data.ways.reverse()
    b = build_network(data)
    assert [(e.way_id, e.node_ids) for e in a.edges] == [(e.way_id, e.node_ids) for e in b.edges]


def test_normalize_name():
    assert normalize_name("  North   Clark Street ") == "north clark street"
