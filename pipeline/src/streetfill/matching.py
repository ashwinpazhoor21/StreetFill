"""Reference street matcher (product plan 5.4). The Swift app ports this exactly.

Stages:

1. :func:`clean_route`: recorded route points → clean, densified segments in
   local metres.
2. :func:`edge_checkpoints`: street edge → checkpoints at a fixed spacing.
3. (next) visit test, ambiguity and coverage.

Every threshold lives in :class:`MatchConfig`. All of them are **[Tune]** values
for the week-one spike; change them there, never inline.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Protocol, Sequence

from .geo import XY, LatLon, LocalProjection, bearing_xy_deg, densify, dist_xy, point_at_distance, polyline_length


@dataclass(frozen=True)
class MatchConfig:
    """All matching thresholds (plan 5.4). Every value is [Tune]."""

    # 1. cleaning
    max_h_acc_m: float = 25.0  # drop points less accurate than this
    max_speed_mps: float = 7.0  # faster than this between points is a GPS jump
    gap_split_s: float = 30.0  # split when a gap is longer than this...
    gap_split_m: float = 100.0  # ...and longer than this distance
    densify_m: float = 5.0
    min_segment_m: float = 30.0  # drop shorter pieces left between jumps (GPS spikes)

    # 2. checkpoints
    checkpoint_spacing_m: float = 15.0
    intersection_clear_m: float = 10.0  # no checkpoints this close to an edge end
    short_edge_m: float = 30.0  # shorter edges get one midpoint checkpoint

    # 3. visit test
    visit_radius_m: float = 20.0
    primary_bonus_m: float = 8.0
    secondary_bonus_m: float = 5.0
    path_radius_m: float = 15.0
    max_bearing_diff_deg: float = 30.0
    # The route point must also be alongside the checkpoint: within this distance
    # of it measured along the street. Without it the 20 m radius reaches past the
    # 10 m intersection clearance and a run ending at a corner credits the next block.
    along_track_m: float = 5.0
    bearing_window_m: float = 10.0  # route direction is taken over ±this much of the route

    # 4. ambiguity
    tie_margin_m: float = 3.0
    # Path beside a street (plan 5.4 step 4): when a point is a candidate for both,
    # and they can be within beside_m of each other, the layer whose geometry the
    # route follows better over beside_window_m of route (mean distance) wins.
    beside_m: float = 25.0
    beside_window_m: float = 100.0

    # 5. coverage
    street_complete_frac: float = 0.90

    def visit_radius_for(self, highway: str) -> float:
        if highway in ("primary", "trunk"):
            return self.visit_radius_m + self.primary_bonus_m
        if highway == "secondary":
            return self.visit_radius_m + self.secondary_bonus_m
        if highway in ("footway", "path", "cycleway", "track", "bridleway", "steps"):
            return self.path_radius_m
        return self.visit_radius_m


DEFAULT_CONFIG = MatchConfig()


# --- 1. cleaning ----------------------------------------------------------------

class _Point(Protocol):
    lat: float
    lon: float
    time: datetime | None
    h_acc: float | None


def _speed(a: tuple[XY, datetime | None], b: tuple[XY, datetime | None]) -> float | None:
    """Implied speed in m/s, ``inf`` for movement with no elapsed time, None if unknown."""
    (pa, ta), (pb, tb) = a, b
    if ta is None or tb is None:
        return None
    dt = (tb - ta).total_seconds()
    d = dist_xy(pa, pb)
    if dt <= 0:
        return math.inf if d > 0 else 0.0
    return d / dt


def clean_route(
    points: Iterable[_Point], projection: LocalProjection, cfg: MatchConfig = DEFAULT_CONFIG
) -> list[list[XY]]:
    """Clean a recorded route into densified segments (plan 5.4 step 1).

    * points with horizontal accuracy worse than ``max_h_acc_m`` are dropped
      (points with unknown accuracy are kept);
    * single-point spikes (too fast both into and out of the point) are dropped;
    * the route is split, never bridged, wherever consecutive points still imply a
      speed above ``max_speed_mps``, or where the gap is longer than both
      ``gap_split_s`` and ``gap_split_m`` (distance alone when times are missing);
    * each segment is densified to ``densify_m``; segments shorter than two points
      are discarded, as are segments shorter than ``min_segment_m`` (what is
      left between two jumps is noise, not running).
    """
    pts = [
        (projection.to_xy((p.lat, p.lon)), p.time)
        for p in points
        if p.h_acc is None or p.h_acc <= cfg.max_h_acc_m
    ]

    def too_fast(a, b) -> bool:
        s = _speed(a, b)
        return s is not None and s > cfg.max_speed_mps

    # Drop isolated spikes: a point that is unreachable from both neighbours,
    # while the neighbours are reachable from each other.
    kept = []
    for i, p in enumerate(pts):
        if 0 < i < len(pts) - 1:
            prev, nxt = pts[i - 1], pts[i + 1]
            if too_fast(prev, p) and too_fast(p, nxt) and not too_fast(prev, nxt):
                continue
        kept.append(p)

    segments: list[list[XY]] = []
    current: list[XY] = []
    for i, p in enumerate(kept):
        if current:
            prev = kept[i - 1]
            d = dist_xy(prev[0], p[0])
            if prev[1] is not None and p[1] is not None:
                gap = (p[1] - prev[1]).total_seconds() > cfg.gap_split_s and d > cfg.gap_split_m
            else:
                gap = d > cfg.gap_split_m
            if gap or too_fast(prev, p):
                segments.append(current)
                current = []
        current.append(p[0])
    segments.append(current)

    return [
        densify(seg, cfg.densify_m)
        for seg in segments
        if len(seg) >= 2 and polyline_length(seg) > 0 and polyline_length(seg) >= cfg.min_segment_m
    ]


# --- 2. checkpoints --------------------------------------------------------------

@dataclass(frozen=True)
class Checkpoint:
    edge_id: int
    index: int  # 0-based along the edge, from its first vertex
    offset_m: float  # distance from the edge's first vertex
    xy: XY
    bearing_deg: float  # edge direction at the checkpoint, 0–360

    @property
    def key(self) -> tuple[int, int]:
        return (self.edge_id, self.index)


def checkpoint_offsets(length_m: float, cfg: MatchConfig = DEFAULT_CONFIG) -> list[float]:
    """Positions of checkpoints along an edge of ``length_m`` (plan 5.4 step 2).

    Edges shorter than ``short_edge_m`` get one midpoint. Longer edges get
    checkpoints every ``checkpoint_spacing_m`` within the span that keeps
    ``intersection_clear_m`` away from both ends, centred in that span. The
    layout is symmetric, so it does not depend on the edge's direction.
    """
    if length_m <= 0:
        return []
    if length_m < cfg.short_edge_m:
        return [length_m / 2]
    usable = length_m - 2 * cfg.intersection_clear_m
    n = math.floor(usable / cfg.checkpoint_spacing_m + 1e-9) + 1
    start = cfg.intersection_clear_m + (usable - (n - 1) * cfg.checkpoint_spacing_m) / 2
    return [start + k * cfg.checkpoint_spacing_m for k in range(n)]


def edge_checkpoints(
    edge_id: int, coords: Sequence[LatLon], projection: LocalProjection, cfg: MatchConfig = DEFAULT_CONFIG
) -> list[Checkpoint]:
    xy = [projection.to_xy(p) for p in coords]
    if len(xy) < 2:
        return []
    out = []
    for i, offset in enumerate(checkpoint_offsets(polyline_length(xy), cfg)):
        point, bearing = point_at_distance(xy, offset)
        out.append(Checkpoint(edge_id=edge_id, index=i, offset_m=offset, xy=point, bearing_deg=bearing))
    return out


def route_bearings(segment: Sequence[XY], window_m: float = DEFAULT_CONFIG.bearing_window_m) -> list[float | None]:
    """Direction of travel at each point of a cleaned segment.

    The direction at a point is the chord from the route ``window_m`` behind it to
    the route ``window_m`` ahead of it (clamped at the segment ends), which
    smooths GPS jitter. It is ``None`` where the route doubles back inside the
    window (the chord is shorter than half the path, i.e. a turn of more than
    about 120°, such as the far end of an out-and-back): the direction there is
    meaningless and must not credit a cross street.
    """
    n = len(segment)
    if n < 2:
        return [None] * n
    cum = [0.0]
    for a, b in zip(segment, segment[1:]):
        cum.append(cum[-1] + dist_xy(a, b))
    out: list[float | None] = []
    lo = hi = 0
    for i in range(n):
        while lo < i and cum[i] - cum[lo + 1] >= window_m:
            lo += 1
        hi = max(hi, i)
        while hi < n - 1 and cum[hi] - cum[i] < window_m:
            hi += 1
        a, b = segment[lo], segment[hi]
        chord = dist_xy(a, b)
        path = cum[hi] - cum[lo]
        out.append(None if chord == 0 or chord < 0.5 * path else bearing_xy_deg(a, b))
    return out
