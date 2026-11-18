"""Matching on the path layer, including a path beside a street (plan 5.4 step 4)."""

import math
import random
from dataclasses import replace

import pytest
from test_matcher import PROJ, line, route

from streetfill.matcher import Matcher
from streetfill.matching import DEFAULT_CONFIG
from streetfill.network import build_network
from streetfill.osm import OsmData, Way


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
    return build_network(OsmData(nodes, ways))


# A drive with a named lakefront trail 12 m beside it, steps, and a footway far away.
NET = make(
    [
        (1, {"highway": "secondary", "name": "Lake Drive"}, [(0, 0), (400, 0)]),
        (2, {"highway": "cycleway", "name": "Lakefront Trail", "foot": "designated"}, [(0, 12), (400, 12)]),
        (3, {"highway": "steps"}, [(0, 100), (40, 100)]),
        (4, {"highway": "footway", "name": "Park Walk"}, [(0, 300), (400, 300)]),
    ]
)
STREET = {e.id for e in NET.edges if e.layer == "street"}
TRAIL = {e.id for e in NET.edges if e.street_key == "trail:lakefront trail"}
PARK = {e.id for e in NET.edges if e.street_key == "trail:park walk"}


def matcher(**cfg):
    return Matcher.from_network(NET, PROJ, replace(DEFAULT_CONFIG, **cfg))


def share(visited, ids, m):
    total = sum(1 for cp in m.checkpoints if cp.edge_id in ids)
    return sum(1 for k in visited if k[0] in ids) / total


def drifting(points, seed, mean, sd=3.0, tau_s=30.0):
    """Lateral GPS error with a bias (``mean``) toward one side, drifting slowly."""
    rng = random.Random(seed)
    phi = math.exp(-1 / tau_s)
    off = mean + rng.gauss(0, sd)
    out = []
    for x, y in points:
        off = mean + phi * (off - mean) + rng.gauss(0, sd * math.sqrt(1 - phi * phi))
        out.append((x + rng.gauss(0, 1), y + off + rng.gauss(0, 1)))
    return out


def test_running_the_trail_credits_the_trail_not_the_drive():
    m = matcher()
    visited = m.match(route(line((10, 12), (390, 12))))
    assert share(visited, TRAIL, m) == 1.0
    assert share(visited, STREET, m) == 0.0


def test_running_the_drive_credits_the_drive_not_the_trail():
    m = matcher()
    visited = m.match(route(line((10, 0), (390, 0))))
    assert share(visited, STREET, m) == 1.0
    assert share(visited, TRAIL, m) == 0.0


def test_trail_run_with_gps_pulled_toward_the_drive():
    # GPS biased 3 m toward the drive (points around y = 9: 3 m from the trail, 9 m
    # from the drive) and drifting slowly. Point-by-point "nearest" often credits the
    # drive; the 100 m window cuts that sharply. Stretches where the GPS sits nearer
    # the drive for the whole window cannot be rescued by geometry (the plan's known
    # hard case, measured in the spike).
    with_rule, without_rule = matcher(), matcher(beside_window_m=0)
    n = 15
    street_with = street_without = trail_with = 0.0
    for seed in range(n):
        pts = route(drifting(line((10, 12), (390, 12)), seed, mean=-3.0, sd=2.0))
        v = with_rule.match(pts)
        trail_with += share(v, TRAIL, with_rule) / n
        street_with += share(v, STREET, with_rule) / n
        street_without += share(without_rule.match(pts), STREET, without_rule) / n
    assert trail_with >= 0.9
    assert street_with <= 0.1
    assert street_with <= 0.6 * street_without  # the rule is doing the work


def test_path_radius_is_15m_without_widening():
    m = matcher()
    assert m.match(route(line((10, 312), (390, 312))))  # 12 m off the footway
    assert not m.match(route(line((10, 318), (390, 318))))  # 18 m off


def test_steps_are_never_matched():
    m = matcher()
    assert not any(e.highway == "steps" for e in m.edges.values())
    assert m.match(route(line((0, 100), (40, 100)))) == []


def test_coverage_keeps_streets_and_paths_apart():
    m = matcher()
    cov = m.coverage(m.match(route(line((10, 12), (390, 12)))))
    street_m = sum(e.length_m for e in NET.edges if e.layer == "street")
    path_m = sum(e.length_m for e in NET.edges if e.layer == "path")
    assert cov.total_length_m == pytest.approx(street_m, rel=1e-3)  # street % is streets only (D7)
    assert cov.covered_length_m == 0 and cov.fraction == 0
    assert cov.path_length_m == pytest.approx(path_m, rel=1e-3)
    assert cov.path_covered_m == pytest.approx(400, abs=0.5)
    assert cov.path_fraction == pytest.approx(0.5, abs=0.01)
    assert cov.complete_trails == ["trail:lakefront trail"]
    assert cov.complete_streets == []
    assert cov.streets["trail:lakefront trail"].layer == "path"
    assert cov.streets["trail:lakefront trail"].name == "Lakefront Trail"


def test_unnamed_paths_count_miles_but_are_not_trails():
    net = make([(1, {"highway": "footway"}, [(0, 0), (200, 0)])])
    m = Matcher.from_network(net, PROJ)
    cov = m.coverage(m.match(route(line((5, 0), (195, 0)))))
    assert cov.path_covered_m == pytest.approx(200, abs=0.5)
    assert cov.complete_trails == []
