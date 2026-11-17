"""Scenario tests for the matcher (issue #5 acceptance criteria). Synthetic streets only."""

import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from streetfill.geo import LocalProjection, dist_xy
from streetfill.matcher import Matcher
from streetfill.network import build_network
from streetfill.osm import OsmData, Way
from streetfill.pack import write_pack

PROJ = LocalProjection(41.9, -87.65)
T0 = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)


@dataclass
class P:
    lat: float
    lon: float
    time: datetime | None
    h_acc: float | None = 5.0


def make_network(lines):
    """lines: list of (way_id, name, highway, [(x, y), ...]) in local metres."""
    nodes, ways, ids = {}, [], {}
    for way_id, name, highway, pts in lines:
        nids = []
        for xy in pts:
            if xy not in ids:
                ids[xy] = len(ids) + 1
                nodes[ids[xy]] = PROJ.to_latlon(xy)
            nids.append(ids[xy])
        tags = {"highway": highway}
        if name:
            tags["name"] = name
        ways.append(Way(way_id, tuple(nids), tags))
    return build_network(OsmData(nodes, ways))


XS = [-200, 0, 200, 400]
GRID = make_network(
    [
        (1, "Main Street", "residential", [(x, 0) for x in XS]),
        (2, "Parallel Street", "residential", [(x, 80) for x in XS]),
        (3, "Cross Avenue", "residential", [(0, -100), (0, 0), (0, 80), (0, 180)]),
        (4, "Second Avenue", "residential", [(200, -100), (200, 0), (200, 80), (200, 180)]),
    ]
)


def line(a, b, step=3.0):
    n = max(1, round(dist_xy(a, b) / step))
    return [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(n + 1)]


def route(xy, *, start=T0, dt=1.0, h_acc=5.0):
    pts = []
    for i, p in enumerate(xy):
        lat, lon = PROJ.to_latlon(p)
        pts.append(P(lat, lon, start + timedelta(seconds=i * dt), h_acc))
    return pts


@pytest.fixture(scope="module")
def matcher():
    return Matcher.from_network(GRID, PROJ)


def edge_id(net, street_key, x_from, x_to=None):
    """Edge on ``street_key`` whose first vertex is at local x (or y) = x_from."""
    for e in net.edges:
        if e.street_key != street_key:
            continue
        a, b = PROJ.to_xy(e.coords[0]), PROJ.to_xy(e.coords[-1])
        if street_key in ("name:main street", "name:parallel street"):
            if round(a[0]) == x_from and (x_to is None or round(b[0]) == x_to):
                return e.id
        elif round(a[1]) == x_from and (x_to is None or round(b[1]) == x_to):
            return e.id
    raise KeyError((street_key, x_from))


def keys_on(visited, eid):
    return [k for k in visited if k[0] == eid]


def total_on(matcher, eid):
    return [cp.key for cp in matcher.checkpoints if cp.edge_id == eid]


MAIN_MID = edge_id(GRID, "name:main street", 0, 200)


# --- acceptance scenarios -----------------------------------------------------------

def test_straight_run_down_a_street(matcher):
    visited = matcher.match(route(line((0, 0), (200, 0))))
    assert keys_on(visited, MAIN_MID) == total_on(matcher, MAIN_MID)
    assert {k[0] for k in visited} == {MAIN_MID}


def test_run_on_a_parallel_street_80m_away(matcher):
    visited = matcher.match(route(line((0, 80), (200, 80))))
    assert keys_on(visited, MAIN_MID) == []
    parallel = edge_id(GRID, "name:parallel street", 0, 200)
    assert keys_on(visited, parallel) == total_on(matcher, parallel)


def test_crossing_a_street_perpendicular(matcher):
    visited = matcher.match(route(line((0, -95), (0, 175))))
    main_ids = {e.id for e in GRID.edges if e.street_key == "name:main street"}
    parallel_ids = {e.id for e in GRID.edges if e.street_key == "name:parallel street"}
    assert not any(k[0] in main_ids | parallel_ids for k in visited)
    cross_ids = {e.id for e in GRID.edges if e.street_key == "name:cross avenue"}
    assert {k[0] for k in visited} == cross_ids


def drifting(points, rng, sd=5.0, tau_s=30.0, white=1.0):
    """GPS-like error: a slow lateral drift (std ``sd``, time constant ``tau_s``) plus small noise."""
    phi = math.exp(-1.0 / tau_s)
    step = sd * math.sqrt(1 - phi * phi)
    off = rng.gauss(0, sd)
    out = []
    for x, y in points:
        off = phi * off + rng.gauss(0, step)
        out.append((x + rng.gauss(0, white), y + off + rng.gauss(0, white)))
    return out


def test_gps_jitter(matcher):
    total = len(total_on(matcher, MAIN_MID))
    parallel_ids = {e.id for e in GRID.edges if e.street_key == "name:parallel street"}
    recalls = []
    for seed in range(20):
        pts = drifting(line((0, 0), (200, 0)), random.Random(seed))
        visited = matcher.match(route(pts, h_acc=8.0))
        recalls.append(len(keys_on(visited, MAIN_MID)) / total)
        assert not any(k[0] in parallel_ids for k in visited)
    assert sum(recalls) / len(recalls) >= 0.95
    assert min(recalls) >= 0.8


def test_white_noise_jitter_never_credits_the_wrong_street(matcher):
    # Independent 5 m noise every second looks like 7+ m/s jumps; the cleaner splits it
    # up. Recall suffers, but nothing may be credited to the street 80 m away.
    rng = random.Random(42)
    pts = [(x + rng.gauss(0, 3), rng.gauss(0, 5)) for x, _ in line((0, 0), (200, 0))]
    visited = matcher.match(route(pts, h_acc=8.0))
    assert {k[0] for k in visited} <= {MAIN_MID}


def test_two_spike_points_do_not_credit_anything(matcher):
    pts = line((-190, 0), (-10, 0))
    pts[30] = (-100, 80)  # two consecutive points on Parallel Street
    pts[31] = (-97, 80)
    visited = matcher.match(route(pts))
    parallel_ids = {e.id for e in GRID.edges if e.street_key == "name:parallel street"}
    assert not any(k[0] in parallel_ids for k in visited)


def test_a_gap_is_not_bridged(matcher):
    before = route(line((-190, 0), (-20, 0)))
    after = route(line((220, 0), (390, 0)), start=before[-1].time + timedelta(minutes=3))
    visited = matcher.match(before + after)
    assert keys_on(visited, MAIN_MID) == []
    assert keys_on(visited, edge_id(GRID, "name:main street", -200, 0))
    assert keys_on(visited, edge_id(GRID, "name:main street", 200, 400))


def test_a_fast_jump_is_not_bridged(matcher):
    # No pause, but 240 m in one second is a GPS jump, not running.
    pts = line((-190, 0), (-20, 0)) + line((220, 0), (390, 0))
    assert keys_on(matcher.match(route(pts)), MAIN_MID) == []


def test_out_and_back_counts_once(matcher):
    out = line((0, 0), (200, 0))
    one_way = matcher.match(route(out))
    both = matcher.match(route(out + out[::-1][1:]))
    assert both == one_way


# --- ambiguity ----------------------------------------------------------------------

def test_tie_between_two_different_streets_credits_neither():
    net = make_network(
        [
            (1, "A Street", "residential", [(0, 0), (200, 0)]),
            (2, "B Street", "residential", [(0, 4), (200, 4)]),
        ]
    )
    m = Matcher.from_network(net, PROJ)
    assert m.match(route(line((0, 2), (200, 2)))) == []
    nearer = m.match(route(line((0, -3), (200, -3))))  # 3 m vs 7 m: A wins
    assert nearer and {k[0] for k in nearer} == {1}


def test_divided_boulevard_credits_both_carriageways():
    net = make_network(
        [
            (1, "Grand Boulevard", "secondary", [(0, 0), (200, 0)]),
            (2, "Grand Boulevard", "secondary", [(200, 6), (0, 6)]),
        ]
    )
    m = Matcher.from_network(net, PROJ)
    visited = m.match(route(line((0, 3), (200, 3))))
    assert {k[0] for k in visited} == {1, 2}


def test_wider_radius_on_primary_roads():
    for highway, expect in (("primary", True), ("residential", False)):
        net = make_network([(1, "Big Road", highway, [(0, 0), (200, 0)])])
        assert bool(Matcher.from_network(net, PROJ).match(route(line((0, 24), (200, 24))))) is expect


# --- coverage -----------------------------------------------------------------------

def test_coverage_by_street_and_area(matcher):
    partial = matcher.coverage(matcher.match(route(line((0, 0), (200, 0)))))
    main = partial.streets["name:main street"]
    assert main.name == "Main Street"
    assert 0.3 < main.fraction < 0.4 and not main.complete
    assert main.covered_m == pytest.approx(200, abs=0.5)
    assert partial.covered_length_m == pytest.approx(200, abs=0.5)
    assert partial.fraction == pytest.approx(200 / partial.total_length_m, abs=1e-3)
    assert partial.complete_streets == []

    full = matcher.coverage(matcher.match(route(line((-200, 0), (400, 0)))))
    assert full.streets["name:main street"].complete
    assert full.complete_streets == ["name:main street"]
    assert full.streets["name:parallel street"].visited == 0


def test_street_complete_at_90_percent(matcher):
    keys = sorted(cp.key for cp in matcher.checkpoints if GRID.edges[cp.edge_id - 1].street_key == "name:main street")
    n90 = -(-9 * len(keys) // 10)  # ceil(0.9 n)
    assert matcher.coverage(keys[:n90]).streets["name:main street"].complete
    assert not matcher.coverage(keys[: n90 - 1]).streets["name:main street"].complete


# --- determinism and packs ----------------------------------------------------------

def test_output_is_sorted_and_repeatable(matcher):
    pts = route(line((-190, 0), (390, 0)))
    a, b = matcher.match(pts), matcher.match(pts)
    assert a == b == sorted(a)


def test_pack_matcher_agrees_with_network_matcher(matcher, tmp_path):
    write_pack(GRID, tmp_path / "grid.sqlite")
    from_pack = Matcher.from_pack(tmp_path / "grid.sqlite")
    matcher = Matcher.from_network(GRID, from_pack.projection)  # same origin, two load paths
    loop = line((-190, 0), (190, 0)) + line((200, 10), (200, 70)) + line((190, 80), (-190, 80))
    assert from_pack.match(route(loop)) == matcher.match(route(loop))
    assert from_pack.street_names
