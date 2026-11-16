import math

import pytest

from streetfill import geo


CHICAGO = (41.8781, -87.6298)


def test_haversine_known_distance():
    # One degree of latitude is about 111.2 km everywhere.
    d = geo.haversine_m((41.0, -87.0), (42.0, -87.0))
    assert d == pytest.approx(111_195, rel=1e-3)


def test_initial_bearing_cardinal_directions():
    assert geo.initial_bearing_deg((0, 0), (1, 0)) == pytest.approx(0.0, abs=1e-9)
    assert geo.initial_bearing_deg((0, 0), (0, 1)) == pytest.approx(90.0, abs=1e-9)
    assert geo.initial_bearing_deg((0, 0), (-1, 0)) == pytest.approx(180.0, abs=1e-9)
    assert geo.initial_bearing_deg((0, 0), (0, -1)) == pytest.approx(270.0, abs=1e-9)


@pytest.mark.parametrize("b1,b2,directed,undirected", [
    (0, 10, 10, 10),
    (350, 10, 20, 20),
    (0, 180, 180, 0),      # opposite directions on the same street
    (90, 260, 170, 10),
    (45, 135, 90, 90),     # perpendicular
])
def test_bearing_differences(b1, b2, directed, undirected):
    assert geo.bearing_diff_deg(b1, b2) == pytest.approx(directed)
    assert geo.undirected_bearing_diff_deg(b1, b2) == pytest.approx(undirected)


def test_projection_round_trip():
    proj = geo.LocalProjection(*CHICAGO)
    p = (41.95, -87.70)
    back = proj.to_latlon(proj.to_xy(p))
    assert back[0] == pytest.approx(p[0], abs=1e-12)
    assert back[1] == pytest.approx(p[1], abs=1e-12)


@pytest.mark.parametrize("dlat,dlon", [(0.1, 0.0), (0.0, 0.2), (0.15, -0.2), (-0.2, 0.25)])
def test_projection_distance_error_under_half_percent_within_30km(dlat, dlon):
    proj = geo.LocalProjection(*CHICAGO)
    a = CHICAGO
    b = (CHICAGO[0] + dlat, CHICAGO[1] + dlon)
    true = geo.haversine_m(a, b)
    assert true < 32_000
    local = geo.dist_xy(proj.to_xy(a), proj.to_xy(b))
    assert abs(local - true) / true < 0.005


def test_projection_for_points_centres_on_bbox():
    proj = geo.LocalProjection.for_points([(41.0, -88.0), (42.0, -87.0)])
    assert (proj.origin_lat, proj.origin_lon) == (41.5, -87.5)
    with pytest.raises(ValueError):
        geo.LocalProjection.for_points([])


def test_bearing_xy_matches_compass():
    assert geo.bearing_xy_deg((0, 0), (0, 10)) == pytest.approx(0)
    assert geo.bearing_xy_deg((0, 0), (10, 0)) == pytest.approx(90)
    assert geo.bearing_xy_deg((0, 0), (0, -10)) == pytest.approx(180)


def test_polyline_length_and_point_segment_distance():
    line = [(0, 0), (30, 0), (30, 40)]
    assert geo.polyline_length(line) == pytest.approx(70)
    assert geo.point_segment_distance((15, 5), (0, 0), (30, 0)) == pytest.approx(5)
    assert geo.point_segment_distance((-3, 4), (0, 0), (30, 0)) == pytest.approx(5)  # beyond the end
    assert geo.point_segment_distance((1, 1), (2, 2), (2, 2)) == pytest.approx(math.sqrt(2))


def test_point_at_distance_walks_segments_and_clamps():
    line = [(0, 0), (30, 0), (30, 40)]
    p, bearing = geo.point_at_distance(line, 10)
    assert p == pytest.approx((10, 0)) and bearing == pytest.approx(90)
    p, bearing = geo.point_at_distance(line, 50)
    assert p == pytest.approx((30, 20)) and bearing == pytest.approx(0)
    p, _ = geo.point_at_distance(line, 999)
    assert p == pytest.approx((30, 40))
    p, _ = geo.point_at_distance(line, -5)
    assert p == pytest.approx((0, 0))


def test_densify_spacing_and_keeps_vertices():
    line = [(0, 0), (12, 0), (12, 7)]
    out = geo.densify(line, 5)
    assert out[0] == (0, 0) and out[-1] == (12, 7)
    assert (12, 0) in out
    gaps = [geo.dist_xy(out[i], out[i + 1]) for i in range(len(out) - 1)]
    assert max(gaps) <= 5 + 1e-9
    assert geo.polyline_length(out) == pytest.approx(19)


def test_densify_edge_cases():
    assert geo.densify([], 5) == []
    assert geo.densify([(1, 1)], 5) == [(1, 1)]
    assert geo.densify([(1, 1), (1, 1)], 5) == [(1, 1)]
    with pytest.raises(ValueError):
        geo.densify([(0, 0), (1, 0)], 0)
