"""Geometry helpers shared by the pack builder and the matcher.

Everything works in one of two spaces:

* geographic: ``(lat, lon)`` in degrees (WGS84), as stored in OSM and Apple Health;
* local: ``(x, y)`` in metres on a flat plane around a city origin, produced by
  :class:`LocalProjection`. Distances and bearings inside one city are computed
  here because it is simple, fast and easy to port to Swift.

The local projection is equirectangular around the origin. Within 30 km of the
origin its distance error stays well under 0.5%, which is far below GPS noise.
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence

EARTH_RADIUS_M = 6_371_008.8  # mean Earth radius (IUGG)

LatLon = tuple[float, float]
XY = tuple[float, float]


# --- geographic -----------------------------------------------------------

def haversine_m(a: LatLon, b: LatLon) -> float:
    """Great-circle distance in metres between two ``(lat, lon)`` points."""
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def initial_bearing_deg(a: LatLon, b: LatLon) -> float:
    """Initial compass bearing from ``a`` to ``b`` in degrees, 0–360 (0 = north)."""
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlon = lon2 - lon1
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return math.degrees(math.atan2(y, x)) % 360.0


# --- bearings --------------------------------------------------------------

def bearing_xy_deg(a: XY, b: XY) -> float:
    """Compass bearing from ``a`` to ``b`` in local coordinates, 0–360 (0 = +y = north)."""
    return math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])) % 360.0


def bearing_diff_deg(b1: float, b2: float) -> float:
    """Smallest angle between two directed bearings, 0–180."""
    d = abs(b1 - b2) % 360.0
    return 360.0 - d if d > 180.0 else d


def undirected_bearing_diff_deg(b1: float, b2: float) -> float:
    """Smallest angle between two lines regardless of direction, 0–90.

    Running a street northbound or southbound is the same street, so the matcher
    compares route and edge bearings this way.
    """
    d = bearing_diff_deg(b1, b2)
    return 180.0 - d if d > 90.0 else d


# --- local projection ------------------------------------------------------

class LocalProjection:
    """Equirectangular projection to metres around an origin."""

    def __init__(self, origin_lat: float, origin_lon: float) -> None:
        self.origin_lat = origin_lat
        self.origin_lon = origin_lon
        self._m_per_deg_lat = math.radians(1.0) * EARTH_RADIUS_M
        self._m_per_deg_lon = self._m_per_deg_lat * math.cos(math.radians(origin_lat))

    @classmethod
    def for_points(cls, points: Iterable[LatLon]) -> "LocalProjection":
        """Projection centred on the bounding box of ``points``."""
        pts = list(points)
        if not pts:
            raise ValueError("need at least one point")
        lats = [p[0] for p in pts]
        lons = [p[1] for p in pts]
        return cls((min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2)

    def to_xy(self, p: LatLon) -> XY:
        lat, lon = p
        return ((lon - self.origin_lon) * self._m_per_deg_lon,
                (lat - self.origin_lat) * self._m_per_deg_lat)

    def to_latlon(self, p: XY) -> LatLon:
        x, y = p
        return (self.origin_lat + y / self._m_per_deg_lat,
                self.origin_lon + x / self._m_per_deg_lon)


# --- local polylines -------------------------------------------------------

def dist_xy(a: XY, b: XY) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def polyline_length(points: Sequence[XY]) -> float:
    return sum(dist_xy(points[i], points[i + 1]) for i in range(len(points) - 1))


def point_segment_distance(p: XY, a: XY, b: XY) -> float:
    """Distance from ``p`` to the segment ``a``–``b``."""
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    seg2 = dx * dx + dy * dy
    if seg2 == 0.0:
        return dist_xy(p, a)
    t = ((p[0] - ax) * dx + (p[1] - ay) * dy) / seg2
    t = max(0.0, min(1.0, t))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def point_at_distance(points: Sequence[XY], distance: float) -> tuple[XY, float]:
    """Point at ``distance`` metres along a polyline and the local bearing there.

    Distances beyond either end are clamped to the end points.
    """
    if len(points) < 2:
        raise ValueError("polyline needs at least two points")
    remaining = max(0.0, distance)
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        seg = dist_xy(a, b)
        if seg == 0.0:
            continue
        if remaining <= seg or i == len(points) - 2:
            t = min(1.0, remaining / seg)
            return ((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])), bearing_xy_deg(a, b))
        remaining -= seg
    # every segment had zero length
    return points[-1], 0.0


def densify(points: Sequence[XY], spacing: float) -> list[XY]:
    """Insert points so consecutive points are at most ``spacing`` metres apart.

    Original vertices are kept, so corners are preserved exactly.
    """
    if spacing <= 0:
        raise ValueError("spacing must be positive")
    if not points:
        return []
    out = [points[0]]
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        seg = dist_xy(a, b)
        n = math.ceil(seg / spacing) if seg > 0 else 0
        for k in range(1, n):
            t = k / n
            out.append((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
        if seg > 0:
            out.append(b)
    return out
