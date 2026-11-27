"""Neighborhood annotation: new neighborhoods and expected gain (plan 6.5, issue #50). Synthetic data only."""

import pytest
from test_pack_neighborhoods import CITY, HOODS, split  # noqa: F401  (the split GRID fixture)
from test_routing_graph import node_at
from test_scoring import LOOP_M, around, block  # noqa: F401  (the 300 x 200 m block fixture)

from streetfill.annotation import NeighborhoodCoverage, load_neighborhood_names
from streetfill.loops import Candidate
from streetfill.pack import write_pack
from streetfill.preview import build_preview
from streetfill.scoring import Choice, score_route

NAMES = {1: "Southside", 2: "Northside"}


def edge_between(g, a, b):
    ends = {node_at(g, a), node_at(g, b)}
    return next(e for e in g.edges.values() if {e.u, e.v} == ends)


def zone(g):
    """South and East in Southside (500 m); North, West and the dead end in Northside (600 m)."""
    south, east = edge_between(g, (0, 0), (300, 0)), edge_between(g, (300, 0), (300, 200))
    for e in g.edges.values():
        e.neighborhood_id = 1 if e in (south, east) else 2
    return south


def test_gains_before_and_after(block):
    south = zone(block)
    hoods = NeighborhoodCoverage(block, {south.pack_id: 1.0}, NAMES)
    gains = hoods.gains(around(block))
    assert [g.name for g in gains] == ["Southside", "Northside"]  # the order the route enters them
    s, n = gains
    assert (s.new, n.new) == (False, True)
    assert s.before == pytest.approx(300 / 500, abs=1e-3) and s.after == pytest.approx(1.0)
    assert n.before == 0 and n.after == pytest.approx(500 / 600, abs=1e-3)  # the dead end is not on the route
    assert s.route_m == pytest.approx(500, abs=0.5) and n.gain == pytest.approx(n.after)


def test_partial_coverage_and_repeats(block):
    south = zone(block)
    hoods = NeighborhoodCoverage(block, {south.pack_id: 0.5})
    arcs = around(block) + around(block)  # twice round: each piece counts once
    (s, n) = hoods.gains(arcs)
    assert s.name == "Neighborhood 1"  # no names given
    assert s.before == pytest.approx(150 / 500, abs=1e-3) and s.after == pytest.approx(1.0)
    assert s.route_m == pytest.approx(500, abs=0.5)


def test_paths_and_unzoned_edges_do_not_count(block):
    zone(block)
    for e in block.edges.values():
        if e.neighborhood_id == 2:
            e.neighborhood_id = None  # outside every neighborhood
    (s,) = NeighborhoodCoverage(block, {}).gains(around(block))
    assert s.id == 1 and s.new
    for e in block.edges.values():
        e.layer = "path"
    assert NeighborhoodCoverage(block, {}).gains(around(block)) == []


def test_names_from_the_pack(split, tmp_path):  # noqa: F811
    pack = tmp_path / "p.sqlite"
    write_pack(split, pack, city=CITY, neighborhoods=HOODS)
    names = load_neighborhood_names(pack)
    assert sorted(names) == [1, 2] and all(isinstance(v, str) and v for v in names.values())


def test_preview_shows_neighborhoods(block):
    south = zone(block)
    coverage = {south.pack_id: 1.0}
    arcs = around(block)
    c = Candidate(0.0, [node_at(block, (0, 0))], arcs, LOOP_M, 0.0, 1, 0.0, {e for e, _ in arcs})
    page = build_preview(block, [Choice(c, score_route(block, arcs, LOOP_M))], LOOP_M, coverage, neighborhoods=NAMES)
    assert "Southside" in page and "60.0% → 100.0%" in page and "+40.0 pts" in page
    assert "Northside <b>new</b>" in page and "0.0% → 83.3%" in page
    assert "Neighborhood 1" in build_preview(block, [Choice(c, score_route(block, arcs, LOOP_M))], LOOP_M)  # no names
    for e in block.edges.values():
        e.neighborhood_id = None  # a pack built without neighborhoods
    assert "No neighborhood data" in build_preview(block, [Choice(c, score_route(block, arcs, LOOP_M))], LOOP_M)
