"""Edge cost terms from plan 6.2, and the routes they produce. Synthetic data only."""

import pytest
from test_path_matching import make
from test_routing_graph import graph_of, node_at

from streetfill.costs import (
    MIN_FACTOR,
    Preferences,
    coverage_from_result,
    factor,
    make_cost,
    newness_term,
    quiet_term,
    scenery_term,
    terrain_term,
)
from streetfill.routing import GraphEdge
from streetfill.scenery import BEACH, HIGHLIGHT, PARK, WATER


def edge(highway="residential", layer="street", length=100.0, gain=None, loss=None, scenery=0, eid=1, pack_id=1):
    return GraphEdge(eid, 0, 1, length, highway, layer, gain_m=gain, loss_m=loss, scenery=scenery, pack_id=pack_id)


def test_terrain():
    steep = edge(gain=6.0, loss=0.0)  # 6% grade
    gentle = edge(gain=1.0, loss=0.0)  # 1%, under the 1.5% allowance
    assert terrain_term(steep, -1.0) == pytest.approx(0.25 * 4.5)
    assert terrain_term(steep, -0.5) == pytest.approx(0.125 * 4.5)
    assert terrain_term(gentle, -1.0) == 0
    assert terrain_term(steep, 1.0) == pytest.approx(-0.5 * 6 / 8)
    assert terrain_term(edge(gain=12.0, loss=0.0), 1.0) == pytest.approx(-0.5)  # capped at 8%
    assert terrain_term(steep, 0.0) == 0 and terrain_term(edge(), -1.0) == 0  # rolling; no elevation
    assert terrain_term(edge(gain=0.0, loss=6.0), -1.0) == terrain_term(steep, -1.0)  # |rise|: same both ways


def test_quiet():
    assert quiet_term(edge("primary"), False) == pytest.approx(0.15)
    assert quiet_term(edge("primary"), True) == pytest.approx(0.75)
    assert quiet_term(edge("trunk"), True) == pytest.approx(0.75)
    assert quiet_term(edge("secondary"), False) == 0 and quiet_term(edge("secondary"), True) == pytest.approx(0.3)
    assert quiet_term(edge("steps", "steps"), False) == pytest.approx(1.0)
    assert quiet_term(edge("residential"), True) == 0 and quiet_term(edge("footway", "path"), True) == 0


def test_newness():
    cov = {1: 0.0, 2: 1.0, 3: 0.5}
    assert newness_term(edge(pack_id=1), 1.0, cov) == pytest.approx(0.8)  # never run
    assert newness_term(edge(pack_id=2), 1.0, cov) == pytest.approx(-0.2)  # fully run: a small penalty
    assert newness_term(edge(pack_id=3), 0.5, cov) == pytest.approx(0.5 * (0.4 - 0.1))
    assert newness_term(edge(pack_id=99), 1.0, cov) == pytest.approx(0.8)  # not in coverage = never run
    assert newness_term(edge("steps", "steps"), 1.0, {}) == 0
    assert newness_term(edge("connector", "connector", pack_id=None), 1.0, {}) == 0
    assert newness_term(edge(), 0.0, {}) == 0


def test_scenery():
    e = edge(scenery=WATER | PARK)
    assert scenery_term(e, WATER) == 0.5
    assert scenery_term(e, WATER | PARK) == 0.8  # capped
    assert scenery_term(e, BEACH | HIGHLIGHT) == 0
    assert scenery_term(e, 0) == 0


def test_factor_combines_and_floors():
    prefs = Preferences(terrain=1.0, newness=1.0, scenery=WATER | PARK)
    wild = edge(gain=10.0, loss=0.0, scenery=WATER | PARK)  # hilly bonus, new, scenic
    assert factor(wild, prefs) == MIN_FACTOR  # 1 − 0.5 − 0.8 − 0.8 is below the floor
    assert factor(edge(), Preferences()) == 1.0
    assert factor(edge(eid=7), Preferences(), used={7}) == pytest.approx(3.0)
    assert factor(edge(eid=7), Preferences(), used={7}, reuse_penalty=1.0) == pytest.approx(2.0)
    cost = make_cost(Preferences())
    assert cost(edge(length=250.0), True) == pytest.approx(250.0) == cost(edge(length=250.0), False)
    with pytest.raises(ValueError):
        Preferences(terrain=2.0)
    with pytest.raises(ValueError):
        Preferences(newness=-0.1)


def test_coverage_from_result():
    assert coverage_from_result({"edges": {"1": [3, 4], "2": [0, 0]}}) == {1: 0.75, 2: 0.0}


# --- the routes the terms produce ---------------------------------------------------

# Two ways from west to east: a direct primary road, and a residential detour 25% longer.
TWO_WAYS = make([
    (1, {"highway": "primary", "name": "Big Road"}, [(0, 0), (400, 0)]),
    (2, {"highway": "residential", "name": "Side Street"}, [(0, 0), (0, 50), (400, 50), (400, 0)]),
])


def route_streets(g, a, b, cost):
    r = g.shortest_path(a, b, cost, min_factor=MIN_FACTOR)
    return {g.edges[e].highway for e, _ in r.arcs}


def test_quiet_streets_take_the_side_street(tmp_path):
    g = graph_of(TWO_WAYS, tmp_path)
    a, b = node_at(g, (0, 0)), node_at(g, (400, 0))
    assert route_streets(g, a, b, make_cost(Preferences())) == {"primary"}
    assert route_streets(g, a, b, make_cost(Preferences(quiet=True))) == {"residential"}


def test_newness_prefers_streets_not_run_yet(tmp_path):
    g = graph_of(TWO_WAYS, tmp_path)
    a, b = node_at(g, (0, 0)), node_at(g, (400, 0))
    big = next(e.pack_id for e in g.edges.values() if e.highway == "primary")
    coverage = {big: 1.0}  # the big road has been run; the side street has not
    assert route_streets(g, a, b, make_cost(Preferences(newness=0.0), coverage)) == {"primary"}
    assert route_streets(g, a, b, make_cost(Preferences(newness=1.0), coverage)) == {"residential"}


def test_scenery_and_terrain_change_the_route(tmp_path):
    g = graph_of(TWO_WAYS, tmp_path)
    a, b = node_at(g, (0, 0)), node_at(g, (400, 0))
    for e in g.edges.values():
        if e.highway == "residential":
            e.scenery = WATER
        else:
            e.gain_m, e.loss_m = 24.0, 0.0  # a 6% climb on the big road
    assert route_streets(g, a, b, make_cost(Preferences(scenery=WATER))) == {"residential"}
    assert route_streets(g, a, b, make_cost(Preferences(terrain=-1.0))) == {"residential"}
    assert route_streets(g, a, b, make_cost(Preferences(terrain=1.0))) == {"primary"}


def test_reuse_penalty_avoids_edges_already_in_the_route(tmp_path):
    g = graph_of(TWO_WAYS, tmp_path)
    a, b = node_at(g, (0, 0)), node_at(g, (400, 0))
    out = g.shortest_path(a, b, make_cost(Preferences()), min_factor=MIN_FACTOR)
    used = {e for e, _ in out.arcs}
    back = g.shortest_path(b, a, make_cost(Preferences(), used=used), min_factor=MIN_FACTOR)
    assert not used & {e for e, _ in back.arcs}  # the loop comes home a different way
