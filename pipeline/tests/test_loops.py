"""Candidate loops (plan 6.3). A synthetic street grid only."""

import math
import time

import pytest
from test_path_matching import make
from test_routing_graph import graph_of

from streetfill.costs import Preferences
from streetfill.geo import haversine_m
from streetfill.loops import AREA_PAD_M, generate_candidates
from test_matcher import PROJ


@pytest.fixture(scope="module")
def city(tmp_path_factory):
    # a 4 x 4 km grid of streets 100 m apart; the start is in the middle
    xs = range(-2000, 2001, 100)
    lines = [(i + 1, {"highway": "residential", "name": f"H{i}"}, [(x, y) for x in xs]) for i, y in enumerate(xs)]
    lines += [(1000 + i, {"highway": "residential", "name": f"V{i}"}, [(x, y) for y in xs]) for i, x in enumerate(xs)]
    return graph_of(make(lines), tmp_path_factory.mktemp("loops"))


START = PROJ.to_latlon((10, -5))


def closed(g, cand):
    """The arcs form one continuous walk from the start back to the start."""
    at = cand.waypoints[0]
    for eid, fwd in cand.arcs:
        e = g.edges[eid]
        here, there = (e.u, e.v) if fwd else (e.v, e.u)
        if here != at:
            return False
        at = there
    return at == cand.waypoints[0]


def test_loops_hit_the_distance_and_come_home(city):
    cands = generate_candidates(city, START, 5000, seed=1)
    assert len(cands) >= 20  # one per bearing, minus duplicates
    assert all(closed(city, c) for c in cands)
    fitting = [c for c in cands if c.fits()]
    assert len(fitting) >= 0.8 * len(cands), [round(c.distance_error, 3) for c in cands]
    for c in cands:
        assert c.length_m == pytest.approx(sum(city.edges[e].length_m for e, _ in c.arcs))


def test_loops_avoid_repeating_streets(city):
    for c in generate_candidates(city, START, 5000, seed=2):
        # on an open grid the reuse penalty keeps almost every edge to one pass
        assert len(c.edge_ids) >= 0.9 * len(c.arcs)


def test_waypoints_spread_around_the_start(city):
    cands = generate_candidates(city, START, 5000, seed=3)
    bearings = sorted(c.bearing_deg for c in cands)
    gaps = [b - a for a, b in zip(bearings, bearings[1:])] + [360 - bearings[-1] + bearings[0]]
    assert max(gaps) < 30  # 24 bearings, 15° apart, plus up to ±5° of jitter each


def test_same_seed_same_loops(city):
    a = [c.arcs for c in generate_candidates(city, START, 4000, seed=7)]
    b = [c.arcs for c in generate_candidates(city, START, 4000, seed=7)]
    c = [c.arcs for c in generate_candidates(city, START, 4000, seed=8)]
    assert a == b and a != c


def test_search_stays_near_the_start(city):
    start_node = city.nearest_node(START)
    limit = 3000 / 2 + AREA_PAD_M
    for cand in generate_candidates(city, START, 3000, seed=4):
        for eid, _ in cand.arcs:
            e = city.edges[eid]
            near = min(math.dist(city.xy[start_node], city.xy[n]) for n in (e.u, e.v))
            assert near <= limit + 1


def test_preferences_reach_the_cost(city):
    # every street already fully run: newness only adds a small penalty, but the loops still form
    coverage = {e.pack_id: 1.0 for e in city.edges.values()}
    cands = generate_candidates(city, START, 4000, Preferences(newness=1.0), coverage, seed=5)
    assert cands and all(closed(city, c) for c in cands)


def test_bad_starts_and_distances(city):
    with pytest.raises(ValueError, match="150 m"):
        generate_candidates(city, PROJ.to_latlon((9000, 9000)), 5000)
    with pytest.raises(ValueError, match="positive"):
        generate_candidates(city, START, 0)


def test_generation_is_quick(city):
    t0 = time.perf_counter()
    generate_candidates(city, START, 8000, seed=6)
    assert time.perf_counter() - t0 < 30
