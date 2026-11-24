"""Out-and-back candidates (plan 6.3 step 8). Synthetic networks only."""

import pytest
from test_loops import START, city, closed  # noqa: F401  (the 4 x 4 km grid fixture)
from test_matcher import PROJ
from test_path_matching import make
from test_routing_graph import graph_of, local

from streetfill.loops import FIT_TOLERANCE, generate_candidates
from streetfill.scoring import best_routes, overlap, score_route


def legs(g, cand):
    """The outbound and return arcs, split where the walk reaches the turnaround."""
    at = cand.waypoints[0]
    for i, (eid, fwd) in enumerate(cand.arcs):
        e = g.edges[eid]
        at = e.v if fwd else e.u
        if at == cand.waypoints[1]:
            return cand.arcs[: i + 1], cand.arcs[i + 1:]
    raise AssertionError("the walk never reaches the turnaround")


def test_out_and_back_on_the_grid(city):  # noqa: F811
    cands = generate_candidates(city, START, 5000, seed=1, shape="out_and_back")
    assert len(cands) >= 20
    assert all(c.shape == "out_and_back" and len(c.waypoints) == 2 and closed(city, c) for c in cands)
    assert sum(c.fits() for c in cands) >= 0.8 * len(cands), [round(c.distance_error, 3) for c in cands]
    for c in cands:
        out, back = legs(city, c)
        # on an open grid the return finds a different way home
        assert not {e for e, _ in out} & {e for e, _ in back}
    with pytest.raises(ValueError):
        generate_candidates(city, START, 5000, shape="figure_eight")


def test_a_lone_street_is_run_back_the_same_way(tmp_path):
    # one road, mapped as 100 m ways so it has a node every 100 m
    g = graph_of(make([(i + 1, {"highway": "residential", "name": "Lone Road"}, [(x, 0), (x + 100, 0)])
                       for i, x in enumerate(range(0, 3000, 100))]), tmp_path)
    start = PROJ.to_latlon((0, 0))
    assert not generate_candidates(g, start, 2000, seed=1)  # no loop is possible
    cands = generate_candidates(g, start, 2000, seed=1, shape="out_and_back")
    assert len(cands) == 1  # only the bearings along the road find a waypoint, and they agree
    (c,) = cands
    out, back = legs(g, c)
    assert back == [(e, not f) for e, f in reversed(out)]
    assert abs(c.distance_error) <= FIT_TOLERANCE
    s = score_route(g, c.arcs, 2000, turnarounds=1)
    assert s.dead_end_spurs == 1 and s.terms["spurs"] == 0  # the turnaround is not a spur
    assert score_route(g, c.arcs, 2000).terms["spurs"] == 1.0


def ladder(gap):
    """Two parallel streets ``gap`` m apart, joined only at their ends, with a node every 100 m."""
    def street(first_id, name, y):
        return [(first_id + i, {"highway": "residential", "name": name}, [(x, y), (x + 100, y)])
                for i, x in enumerate(range(0, 1200, 100))]

    return make(street(1, "Near", 0) + street(101, "Far", gap) + [
        (201, {"highway": "residential", "name": "West"}, [(0, 0), (0, gap)]),
        (202, {"highway": "residential", "name": "East"}, [(1200, 0), (1200, gap)]),
    ])


@pytest.mark.parametrize("gap, parallel", [(60, True), (700, False)])
def test_return_takes_a_parallel_street_only_when_close(tmp_path, gap, parallel):
    # turning at x = 1,000 on Near: running back costs 1,000 m × 2 (the 1.0 return penalty);
    # going on round by Far costs 200 + 1,200 + 2 × gap, so it wins at 60 m apart and loses at 700 m
    g = graph_of(ladder(gap), tmp_path)
    cands = generate_candidates(g, PROJ.to_latlon((0, 0)), 2400, seed=1, shape="out_and_back")
    east = [c for c in cands if abs(local(g, c.waypoints[1])[1]) < 1]  # turning on Near
    assert east
    for c in east:
        out, back = legs(g, c)
        shared = {e for e, _ in out} & {e for e, _ in back}
        assert bool(shared) is not parallel


def test_best_out_and_backs(city):  # noqa: F811
    chosen = best_routes(city, START, 5000, seed=1, shape="out_and_back")
    assert len(chosen) == 3 and all(c.candidate.shape == "out_and_back" for c in chosen)
    for i, a in enumerate(chosen):
        for b in chosen[i + 1:]:
            assert overlap(city, a.candidate, b.candidate) < 0.4
