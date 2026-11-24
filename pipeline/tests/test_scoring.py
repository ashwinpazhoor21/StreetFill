"""Scoring routes and choosing three (plan 6.4). Synthetic networks only."""

import pytest
from test_loops import START, city  # noqa: F401  (the 4 x 4 km grid fixture)
from test_matcher import PROJ
from test_path_matching import make
from test_routing_graph import graph_of, node_at

from streetfill.costs import Preferences
from streetfill.highlights import Highlight
from streetfill.pack import write_pack
from streetfill.routing import Graph
from streetfill.loops import Candidate
from streetfill.scenery import PARK, WATER
from streetfill.scoring import (
    MAX_OVERLAP,
    Choice,
    HighlightPoint,
    best_routes,
    choose,
    load_highlights,
    overlap,
    score_route,
    terrain_miss,
)

# a 300 x 200 m block: a square of streets with a dead end off the north-east corner
BLOCK = make([
    (1, {"highway": "residential", "name": "South"}, [(0, 0), (300, 0)]),
    (2, {"highway": "residential", "name": "East"}, [(300, 0), (300, 200)]),
    (3, {"highway": "residential", "name": "North"}, [(300, 200), (0, 200)]),
    (4, {"highway": "residential", "name": "West"}, [(0, 200), (0, 0)]),
    (5, {"highway": "residential", "name": "Dead End"}, [(300, 200), (400, 200)]),
])
LOOP_M = 1000.0


@pytest.fixture
def block(tmp_path):
    return graph_of(BLOCK, tmp_path)


def walk(g, points):
    """The arcs of the shortest walk through the given points, in order."""
    arcs = []
    for a, b in zip(points, points[1:]):
        arcs += g.shortest_path(node_at(g, a), node_at(g, b)).arcs
    return arcs


def around(g):
    return walk(g, [(0, 0), (300, 0), (300, 200), (0, 200), (0, 0)])


def test_a_clean_loop_of_the_right_length_scores_zero(block):
    s = score_route(block, around(block), LOOP_M)
    assert s.length_m == pytest.approx(LOOP_M, abs=0.5)
    assert s.turns == 3 and s.dead_end_spurs == 0 and s.repeated_share == 0
    assert s.total == pytest.approx(0, abs=0.01)  # 3 turns in 0.62 mi is under 8 per mile
    assert score_route(block, around(block), 1100).terms["distance"] == pytest.approx(3 * 100 / 1100, abs=0.01)


def test_a_dead_end_spur_is_penalised(block):
    arcs = walk(block, [(0, 0), (300, 0), (300, 200), (400, 200), (300, 200), (0, 200), (0, 0)])
    s = score_route(block, arcs, 1200)
    assert s.dead_end_spurs == 1 and s.terms["spurs"] == 1.0
    assert s.repeated_share == pytest.approx(100 / 1200, abs=0.001)
    assert s.turns == 3  # the U-turn is a spur, not a turn


def edge_between(g, a, b):
    ends = {node_at(g, a), node_at(g, b)}
    return next(e for e in g.edges.values() if {e.u, e.v} == ends)


def test_new_share_follows_the_slider(block):
    south = edge_between(block, (0, 0), (300, 0)).pack_id
    coverage = {south: 1.0}  # South has been run: 300 of the 1,000 m
    s = score_route(block, around(block), LOOP_M, Preferences(newness=1.0), coverage)
    assert s.new_share == pytest.approx(0.7, abs=0.001)
    assert s.terms["newness"] == pytest.approx(2 * 0.3, abs=0.01)
    assert score_route(block, around(block), LOOP_M, Preferences(newness=0.7), coverage).terms["newness"] == pytest.approx(0, abs=0.01)
    assert score_route(block, around(block), LOOP_M, Preferences(), coverage).terms["newness"] == 0  # no preference
    assert score_route(block, around(block), LOOP_M, Preferences(newness=1.0), {south: 0.4}).new_share == pytest.approx(1.0)


def test_terrain_bands():
    assert terrain_miss(10, -1) == 0 and terrain_miss(40, -1) == pytest.approx(25 / 50)
    assert terrain_miss(30, 0) == 0 and terrain_miss(5, 0) == pytest.approx(10 / 50) and terrain_miss(80, 0) == pytest.approx(30 / 50)
    assert terrain_miss(60, 1) == 0 and terrain_miss(20, 1) == pytest.approx(30 / 50)
    assert terrain_miss(None, 1) == 0  # no elevation data


def test_terrain_from_the_route(block):
    for e in block.edges.values():
        e.gain_m, e.loss_m = 2.0, 2.0  # 8 m of climb on the 1 km loop: about 42 ft/mi, rolling
    s = score_route(block, around(block), LOOP_M, Preferences(terrain=1.0))
    assert s.gain_m == pytest.approx(8.0)
    assert s.gain_ft_per_mi == pytest.approx(8 * 3.28084 / (LOOP_M / 1609.344), rel=1e-3)
    assert s.terms["terrain"] == pytest.approx(1.5 * (50 - s.gain_ft_per_mi) / 50, rel=1e-3)
    assert score_route(block, around(block), LOOP_M, Preferences(terrain=0.0)).terms["terrain"] == 0


def test_scenery_and_highlights(block):
    edge_between(block, (0, 0), (300, 0)).scenery = WATER
    s = score_route(block, around(block), LOOP_M, Preferences(scenery=WATER | PARK))
    assert s.scenery_share == pytest.approx(0.3, abs=0.001) and s.terms["scenery"] == pytest.approx(-0.3, abs=0.001)
    assert score_route(block, around(block), LOOP_M).scenery_share == 0  # no chip selected

    def at(i, xy):
        return HighlightPoint(i, f"H{i}", "landmark", xy)

    # the graph's projection differs from the tests', so place highlights through lat/lon
    def xy(p):
        return block.projection.to_xy(PROJ.to_latlon(p))

    hs = [at(1, xy((150, -50))), at(2, xy((300, 100))), at(3, xy((150, 100))), at(4, xy((150, 270))),
          at(5, xy((-70, 100))), at(6, xy((-60, 50)))]
    s = score_route(block, around(block), LOOP_M, highlights=hs)
    # in route order; 3 is mid-block, 100 m from every street; 4 is 70 m north of North
    assert s.highlights == [1, 2, 4, 5, 6]
    assert s.terms["highlights"] == pytest.approx(-0.9)  # capped at three


def test_highlights_load_from_the_pack(tmp_path):
    path = tmp_path / "h.sqlite"
    h = Highlight("node/1", "Fountain", "landmark", PROJ.to_latlon((150, -50)), 0.0, 60.0, None, 1.0)
    write_pack(BLOCK, path, highlights=[h])
    g = Graph.from_pack(path)
    (hp,) = load_highlights(path, g.projection)
    assert hp.name == "Fountain" and hp.category == "landmark"
    assert score_route(g, around(g), LOOP_M, highlights=[hp]).highlights == [hp.id]


def cand(g, edges, score):
    c = Candidate(0.0, [], [], sum(e.length_m for e in edges), 0.0, 1, 0.0, {e.id for e in edges})
    s = score_route(g, [], 1.0)
    s.total = score
    return Choice(c, s)


def test_choose_skips_routes_that_overlap(block):
    south, east = edge_between(block, (0, 0), (300, 0)), edge_between(block, (300, 0), (300, 200))
    north, west = edge_between(block, (300, 200), (0, 200)), edge_between(block, (0, 200), (0, 0))
    dead = edge_between(block, (300, 200), (400, 200))
    a = cand(block, [south, east, north, west], 1.0)
    b = cand(block, [south, east, north, west], 2.0)  # the same loop
    c = cand(block, [dead, north], 3.0)  # 300 of its 400 m are on the first loop: 75%
    d = cand(block, [dead], 4.0)  # nothing shared
    assert overlap(block, a.candidate, c.candidate) == pytest.approx(0.75, abs=0.001)
    assert [x.score.total for x in choose(block, [d, c, b, a])] == [1.0, 4.0]  # fewer than three is fine


def test_best_routes_on_the_grid(city):  # noqa: F811
    chosen = best_routes(city, START, 5000, seed=1)
    assert len(chosen) == 3
    totals = [c.score.total for c in chosen]
    assert totals == sorted(totals)
    for i, a in enumerate(chosen):
        assert a.candidate.fits()
        for b in chosen[i + 1:]:
            assert overlap(city, a.candidate, b.candidate) < MAX_OVERLAP
