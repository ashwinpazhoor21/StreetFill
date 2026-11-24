"""Rewarding waypoints and the scenery pull (plan 6.3 steps 4 and 5). A synthetic street grid only."""

import pytest
from test_matcher import PROJ
from test_path_matching import make
from test_routing_graph import graph_of, local, node_at

from streetfill.costs import Preferences
from streetfill.loops import NodeRewards, _snap_xy, generate_candidates, pull_targets
from streetfill.route_highlights import HighlightGrid, HighlightPoint
from streetfill.scenery import HIGHLIGHT, PARK, WATER

START = PROJ.to_latlon((10, -5))


@pytest.fixture
def grid(tmp_path):
    # a 3 x 3 km grid of streets 100 m apart, the start in the middle
    xs = range(-1500, 1501, 100)
    lines = [(i + 1, {"highway": "residential", "name": f"H{i}"}, [(x, y) for x in xs]) for i, y in enumerate(xs)]
    lines += [(1000 + i, {"highway": "residential", "name": f"V{i}"}, [(x, y) for y in xs]) for i, x in enumerate(xs)]
    return graph_of(make(lines), tmp_path)


def xy(g, p):
    """A test-projection point in the graph's own projection."""
    return g.projection.to_xy(PROJ.to_latlon(p))


def on_street_x(g, e, x):
    return all(abs(local(g, n)[0] - x) < 0.5 for n in (e.u, e.v))


def coverage_all_run_but(g, keep):
    return {e.pack_id: (0.0 if keep(e) else 1.0) for e in g.edges.values()}


def test_snapping_prefers_new_streets(grid):
    coverage = coverage_all_run_but(grid, lambda e: on_street_x(grid, e, 100))
    reward = NodeRewards(grid, Preferences(newness=1.0), coverage)
    p = xy(grid, (40, 500))  # 40 m from x = 0 (run), 60 m from x = 100 (new)
    assert _snap_xy(grid, p, 200, None) == node_at(grid, (0, 500))
    assert _snap_xy(grid, p, 200, None, reward) == node_at(grid, (100, 500))
    assert reward(node_at(grid, (100, 500))) == pytest.approx(0.5, abs=1e-3)  # 2 of its 4 edges are new
    assert reward(node_at(grid, (0, 500))) == 0


def test_no_preferences_means_nearest(grid):
    reward = NodeRewards(grid, Preferences(), {})
    assert all(reward(i) == 0 for i in range(len(grid.node_ids)))
    p = xy(grid, (40, 470))
    assert _snap_xy(grid, p, 200, None, reward) == _snap_xy(grid, p, 200, None) == node_at(grid, (0, 500))


def test_scenery_and_highlights_add_reward(grid):
    n = node_at(grid, (500, 500))
    for e in grid.edges.values():
        if n in (e.u, e.v) and on_street_x(grid, e, 500):
            e.scenery = PARK  # the two north-south edges at the node
    hs = HighlightGrid([HighlightPoint(1, "Statue", "landmark", xy(grid, (530, 500))),
                        HighlightPoint(2, "Far", "landmark", xy(grid, (600, 600)))])
    assert NodeRewards(grid, Preferences(scenery=PARK), {}, hs)(n) == pytest.approx(0.5 + 0.3, abs=1e-3)
    assert NodeRewards(grid, Preferences(scenery=WATER), {}, hs)(n) == pytest.approx(0.3, abs=1e-3)  # park not selected


def test_new_streets_draw_waypoints(grid):
    # only the street at x = 800 is new; waypoints on the east side land on it
    coverage = coverage_all_run_but(grid, lambda e: on_street_x(grid, e, 800))
    on_new = {i for i in range(len(grid.node_ids)) if abs(local(grid, i)[0] - 800) < 0.5}

    def count(prefs):
        cands = generate_candidates(grid, START, 5000, prefs, coverage, seed=1)
        return sum(1 for c in cands for w in c.waypoints[1:] if w in on_new)

    assert count(Preferences(newness=1.0)) > count(Preferences())


def flag_water(g):
    """Water along the street y = 0 between x = 1000 and 1200, east of the start."""
    water = set()
    for e in g.edges.values():
        ys = [local(g, n)[1] for n in (e.u, e.v)]
        xs = [local(g, n)[0] for n in (e.u, e.v)]
        if all(abs(y) < 0.5 for y in ys) and min(xs) >= 999.5 and max(xs) <= 1200.5:
            e.scenery |= WATER
            water.update((e.u, e.v))
    return water


def test_waterfront_pulls_one_waypoint_onto_the_water(grid):
    water = flag_water(grid)
    cands = generate_candidates(grid, START, 5000, Preferences(scenery=WATER), seed=1)
    pulled = [c for c in cands if c.pulled]
    assert pulled and len(pulled) < len(cands)  # only loops heading east
    for c in pulled:
        w = c.waypoints[c.pulled]
        assert w in water
        sx, sy = local(grid, c.waypoints[0])
        assert local(grid, w)[0] > sx  # east of the start
        assert w in {grid.edges[e].u for e, _ in c.arcs} | {grid.edges[e].v for e, _ in c.arcs}
    assert not [c for c in generate_candidates(grid, START, 5000, seed=1) if c.pulled]  # chip not selected
    assert not pull_targets(grid, node_at(grid, (0, 0)), 1500, Preferences(scenery=WATER))  # beyond D/2


def test_parks_pull_towards_park_highlights(grid):
    hs = [HighlightPoint(1, "Little Park", "park", xy(grid, (-30, 880))),
          HighlightPoint(2, "Statue", "landmark", xy(grid, (880, -30)))]
    park = node_at(grid, (0, 900))
    s = node_at(grid, (0, 0))
    assert pull_targets(grid, s, 5000, Preferences(scenery=PARK), hs) == [park]
    assert pull_targets(grid, s, 5000, Preferences(scenery=HIGHLIGHT), hs) == [node_at(grid, (900, 0))]
    cands = generate_candidates(grid, START, 5000, Preferences(scenery=PARK), highlights=hs, seed=1)
    pulled = [c for c in cands if c.pulled]
    assert pulled and all(c.waypoints[c.pulled] == park for c in pulled)
