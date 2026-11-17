from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from streetfill.geo import LocalProjection, dist_xy, polyline_length
from streetfill.matching import (
    DEFAULT_CONFIG,
    MatchConfig,
    checkpoint_offsets,
    clean_route,
    edge_checkpoints,
    route_bearings,
)

PROJ = LocalProjection(41.9, -87.65)
T0 = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)


@dataclass
class P:
    lat: float
    lon: float
    time: datetime | None
    h_acc: float | None = 5.0


def run(xy_points, *, dt=1.0, h_acc=5.0, start=T0):
    """Route points from local (x, y) metres, one every ``dt`` seconds."""
    out = []
    for i, xy in enumerate(xy_points):
        lat, lon = PROJ.to_latlon(xy)
        out.append(P(lat, lon, start + timedelta(seconds=i * dt), h_acc))
    return out


def straight(n, step=3.0, y=0.0):
    return [(i * step, y) for i in range(n)]


# --- config ------------------------------------------------------------------------

def test_config_defaults_match_plan():
    c = DEFAULT_CONFIG
    assert (c.max_h_acc_m, c.max_speed_mps, c.gap_split_s, c.gap_split_m, c.densify_m) == (25, 7, 30, 100, 5)
    assert (c.checkpoint_spacing_m, c.intersection_clear_m, c.short_edge_m) == (15, 10, 30)
    assert (c.visit_radius_m, c.max_bearing_diff_deg, c.tie_margin_m, c.street_complete_frac) == (20, 30, 3, 0.9)
    assert (c.min_segment_m, c.along_track_m) == (30, 5)


@pytest.mark.parametrize(
    "highway, radius",
    [("residential", 20), ("primary", 28), ("trunk", 28), ("secondary", 25), ("tertiary", 20), ("footway", 15)],
)
def test_visit_radius_by_class(highway, radius):
    assert DEFAULT_CONFIG.visit_radius_for(highway) == radius


def test_config_is_frozen():
    with pytest.raises(AttributeError):
        DEFAULT_CONFIG.visit_radius_m = 30


# --- cleaning ----------------------------------------------------------------------

def test_clean_straight_run_is_one_densified_segment():
    segs = clean_route(run(straight(34, step=3.0)), PROJ)  # 99 m at 3 m/s
    assert len(segs) == 1
    seg = segs[0]
    assert polyline_length(seg) == pytest.approx(99, abs=0.01)
    assert max(dist_xy(a, b) for a, b in zip(seg, seg[1:])) <= 5.0 + 1e-9


def test_clean_densifies_sparse_points():
    seg = clean_route(run([(0, 0), (20, 0), (40, 0)], dt=5), PROJ)[0]
    assert len(seg) == 9  # every 5 m
    assert seg[0] == pytest.approx((0, 0), abs=1e-6)
    assert seg[-1] == pytest.approx((40, 0), abs=1e-6)


def test_clean_drops_inaccurate_points():
    pts = run(straight(10))
    pts[4].h_acc = 40.0
    pts[5].h_acc = 25.0  # exactly the limit is kept
    pts[6].h_acc = None  # unknown accuracy is kept
    segs = clean_route(pts, PROJ, MatchConfig(densify_m=100, min_segment_m=0))
    assert len(segs[0]) == 9


def test_clean_drops_a_single_spike():
    pts = run(straight(10))
    lat, lon = PROJ.to_latlon((12.0, 60.0))  # 60 m off the line for one second
    pts[4] = P(lat, lon, pts[4].time)
    segs = clean_route(pts, PROJ, MatchConfig(densify_m=100, min_segment_m=0))
    assert len(segs) == 1
    assert all(abs(y) < 1e-6 for _, y in segs[0])


def test_clean_splits_at_a_jump_instead_of_bridging():
    pts = run(straight(20) + [(x + 300, 200) for x, _ in straight(20)])
    segs = clean_route(pts, PROJ)
    assert len(segs) == 2
    assert max(y for _, y in segs[0]) < 1e-6
    assert min(y for _, y in segs[1]) == pytest.approx(200, abs=1e-6)


def test_clean_splits_at_a_long_time_and_distance_gap():
    # 5 minutes and 150 m between the two halves (0.5 m/s, so not a speed jump).
    first = run(straight(20))
    second = run([(x + 207, 0) for x, _ in straight(20)], start=first[-1].time + timedelta(minutes=5))
    assert len(clean_route(first + second, PROJ)) == 2


def test_clean_keeps_a_long_stop_in_place():
    # Waiting 2 minutes at a light: long in time, no distance, so no split.
    first = run(straight(10))
    second = run([(x + 30, 0) for x, _ in straight(10)], start=first[-1].time + timedelta(minutes=2))
    assert len(clean_route(first + second, PROJ)) == 1


def test_clean_short_gap_in_distance_is_not_split():
    # 60 s but only 50 m apart: both conditions are needed.
    first = run(straight(10))
    second = run([(x + 77, 0) for x, _ in straight(10)], start=first[-1].time + timedelta(seconds=60))
    assert len(clean_route(first + second, PROJ)) == 1


def test_clean_without_times_splits_on_distance_only():
    pts = run(straight(20) + [(x + 200, 0) for x, _ in straight(20)])
    for p in pts:
        p.time = None
    assert len(clean_route(pts, PROJ)) == 2


def test_clean_handles_empty_and_stationary_routes():
    assert clean_route([], PROJ) == []
    assert clean_route(run([(0, 0)] * 5), PROJ) == []


# --- checkpoints -------------------------------------------------------------------

def test_short_edge_gets_one_midpoint():
    assert checkpoint_offsets(20) == [10]
    assert checkpoint_offsets(29.9) == [pytest.approx(14.95)]


def test_checkpoints_every_15m_clear_of_ends():
    offs = checkpoint_offsets(100)  # usable 10..90 = 80 m -> 6 checkpoints, centred
    assert offs == pytest.approx([2.5 + 10 + 15 * k for k in range(6)])
    assert offs[0] >= 10 and 100 - offs[-1] >= 10


@pytest.mark.parametrize("length", [30, 31, 44.9, 45, 77.7, 100, 1234.5])
def test_checkpoint_layout_invariants(length):
    offs = checkpoint_offsets(length)
    assert offs[0] >= 10 - 1e-9
    assert length - offs[-1] >= 10 - 1e-9
    assert all(b - a == pytest.approx(15) for a, b in zip(offs, offs[1:]))
    # symmetric: same layout from either end
    assert [length - o for o in reversed(offs)] == pytest.approx(offs)


def test_edge_checkpoints_follow_geometry():
    coords = [PROJ.to_latlon((0, 0)), PROJ.to_latlon((60, 0)), PROJ.to_latlon((60, 60))]  # an L, 120 m
    cps = edge_checkpoints(7, coords, PROJ)
    assert [c.key for c in cps] == [(7, i) for i in range(len(cps))]
    assert len(cps) == 7
    for c in cps:
        if c.offset_m < 60 - 1e-6:
            assert c.xy[1] == pytest.approx(0, abs=1e-6) and c.bearing_deg == pytest.approx(90)
        elif c.offset_m > 60 + 1e-6:
            assert c.xy[0] == pytest.approx(60, abs=1e-6) and c.bearing_deg == pytest.approx(0)


def test_edge_checkpoints_degenerate_edges():
    assert edge_checkpoints(1, [PROJ.to_latlon((0, 0))], PROJ) == []
    assert edge_checkpoints(1, [PROJ.to_latlon((0, 0))] * 2, PROJ) == []


def test_route_bearings():
    assert route_bearings([(0, 0), (10, 0), (10, 10)], window_m=1) == pytest.approx([90, 45, 0])
    assert route_bearings([(0, 0)]) == [None]
    east = [(x * 5.0, 0.0) for x in range(10)]
    assert route_bearings(east) == pytest.approx([90] * 10)


def test_route_bearings_smooth_jitter_over_the_window():
    zigzag = [(x * 5.0, 3.0 if x % 2 else -3.0) for x in range(20)]
    inner = route_bearings(zigzag)[3:-3]
    assert all(b is not None and (b - 90) % 360 < 30 or (90 - b) % 360 < 30 for b in inner)


def test_route_bearings_none_where_the_route_doubles_back():
    out_and_back = [(x * 5.0, 0.0) for x in range(10)] + [(x * 5.0, 0.0) for x in range(8, -1, -1)]
    b = route_bearings(out_and_back)
    assert b[0] == pytest.approx(90) and b[5] == pytest.approx(90)
    assert b[9] is None
    assert b[-1] == pytest.approx(270) and b[-5] == pytest.approx(270)


def test_clean_drops_short_pieces_between_jumps():
    pts = run(straight(20))
    lat, lon = PROJ.to_latlon((30.0, 80.0))
    lat2, lon2 = PROJ.to_latlon((33.0, 80.0))
    pts[10] = P(lat, lon, pts[10].time)
    pts[11] = P(lat2, lon2, pts[11].time)
    segs = clean_route(pts, PROJ)
    assert all(abs(y) < 1e-6 for seg in segs for _, y in seg)
