from pathlib import Path

import pytest

from streetfill.osm import is_street, load_overpass_file, parse_overpass, street_ways

FIXTURE = Path(__file__).parent / "fixtures" / "mini_area.json"


@pytest.fixture(scope="module")
def data():
    return load_overpass_file(FIXTURE)


def test_parse_reads_nodes_and_ways(data):
    assert len(data.nodes) == 39
    assert len(data.ways) == 19
    assert data.nodes[1] == pytest.approx((41.9, -87.65))


def test_parse_ignores_relations_and_nodes_without_coordinates():
    doc = {
        "elements": [
            {"type": "node", "id": 1, "lat": 1.0, "lon": 2.0},
            {"type": "node", "id": 2},
            {"type": "relation", "id": 3, "members": []},
        ]
    }
    parsed = parse_overpass(doc)
    assert parsed.nodes == {1: (1.0, 2.0)}
    assert parsed.ways == []


def test_fixture_street_ways(data):
    kept = {w.id for w in street_ways(data)}
    assert kept == {100, 101, 200, 304, 307, 313, 314, 315}


@pytest.mark.parametrize(
    "highway",
    ["primary", "secondary", "tertiary", "unclassified", "residential", "living_street", "pedestrian"],
)
def test_included_classes(highway):
    assert is_street({"highway": highway})


@pytest.mark.parametrize(
    "tags",
    [
        {"highway": "motorway"},
        {"highway": "primary_link"},
        {"highway": "service"},
        {"highway": "footway"},
        {"highway": "path"},
        {"highway": "construction"},
        {"highway": "trunk"},
        {"highway": "trunk", "foot": "no"},
        {"highway": "residential", "foot": "no"},
        {"highway": "residential", "access": "private"},
        {"highway": "residential", "tunnel": "yes"},
        {"highway": "residential", "tunnel": "building_passage"},
        {"highway": "residential", "layer": "-1"},
        {"highway": "residential", "construction": "yes"},
        {"highway": "pedestrian", "area": "yes"},
        {},
    ],
)
def test_excluded(tags):
    assert not is_street(tags)


@pytest.mark.parametrize(
    "tags",
    [
        {"highway": "trunk", "foot": "yes"},
        {"highway": "trunk", "foot": "designated"},
        {"highway": "residential", "access": "private", "foot": "yes"},
        {"highway": "residential", "tunnel": "no"},
        {"highway": "residential", "layer": "1", "bridge": "yes"},
        {"highway": "residential", "layer": "not-a-number"},
    ],
)
def test_included_edge_cases(tags):
    assert is_street(tags)
