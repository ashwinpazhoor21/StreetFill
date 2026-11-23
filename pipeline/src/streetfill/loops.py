"""Candidate loops for a target distance (plan 6.3). All numbers are [Tune] for the week-3 spike.

1. **Snap the start** to the nearest routable node within 150 m.
2. **Radius** for a target distance D: ``r = 1.1 · D / (2π)``.
3. **Waypoints.** For each of K = 24 bearings θ (evenly spaced, plus up to ±5°
   of jitter), W1 sits at distance r on bearing θ and W2 at bearing θ + 60°
   (±15° of jitter). Each is snapped to the nearest node within 200 m. Snapping
   to the most rewarding node, and the scenery pull, come with scoring (#15
   part 2).
4. **Path.** A* for S → W1 → W2 → S with the 6.2 cost. Edges used by earlier
   legs carry the reuse penalty on later legs, so a loop comes home a
   different way where the streets allow it.
5. **Distance fit.** If the length misses D by more than 5%, r is scaled by
   D ÷ length and the loop is rebuilt, up to 3 times. The closest attempt is
   kept.
6. **Search area.** Edges with both ends farther than D/2 + 0.5 mi (805 m) from
   the start are never used (6.5), which bounds the work on a big city.

A seed fixes the jitter, so the same start, preferences and seed always give
the same candidates. That is what the Swift port's fixtures need (6.5).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import AbstractSet, Mapping

from .costs import MIN_FACTOR, Preferences, make_cost
from .geo import LatLon
from .routing import Graph, Route

K = 24
RADIUS_FACTOR = 1.1
W2_OFFSET_DEG = 60.0
W1_JITTER_DEG = 5.0
W2_JITTER_DEG = 15.0
START_SNAP_M = 150.0
WAYPOINT_SNAP_M = 200.0
FIT_TOLERANCE = 0.05
FIT_RETRIES = 3
AREA_PAD_M = 805.0  # 0.5 mi


@dataclass
class Candidate:
    bearing_deg: float
    waypoints: list[int]  # node indices: start, W1, W2
    arcs: list[tuple[int, bool]]  # graph edge id and direction, in order
    length_m: float
    cost: float
    attempts: int
    distance_error: float  # (length − target) ÷ target
    edge_ids: set[int] = field(default_factory=set)

    def fits(self, tolerance: float = FIT_TOLERANCE) -> bool:
        return abs(self.distance_error) <= tolerance


def _offset(graph: Graph, origin: int, distance_m: float, bearing_deg: float) -> tuple[float, float]:
    x, y = graph.xy[origin]
    t = math.radians(bearing_deg)
    return x + distance_m * math.sin(t), y + distance_m * math.cos(t)


def _snap_xy(graph: Graph, xy: tuple[float, float], max_m: float, allowed: AbstractSet[int] | None) -> int | None:
    best = None
    for i in graph.nodes_near(xy, max_m):
        if allowed is not None and i not in allowed:
            continue
        d = math.dist(xy, graph.xy[i])
        if d <= max_m and (best is None or d < best[0]):
            best = (d, i)
    return best[1] if best else None


def _area(graph: Graph, start: int, radius_m: float) -> set[int]:
    sx, sy = graph.xy[start]
    return {i for i in graph.nodes_near((sx, sy), radius_m) if math.dist((sx, sy), graph.xy[i]) <= radius_m}


def _loop(graph, stops, prefs, coverage, area) -> tuple[list[tuple[int, bool]], float, float] | None:
    used: set[int] = set()
    arcs: list[tuple[int, bool]] = []
    length = cost_total = 0.0
    for a, b in zip(stops, stops[1:]):
        base = make_cost(prefs, coverage, used)

        def cost(edge, forward, base=base):
            if edge.u not in area and edge.v not in area:
                return math.inf  # outside the search area
            return base(edge, forward)

        leg: Route | None = graph.shortest_path(a, b, cost, min_factor=MIN_FACTOR)
        if leg is None or math.isinf(leg.cost):
            return None
        arcs.extend(leg.arcs)
        used.update(e for e, _ in leg.arcs)
        length += leg.length_m
        cost_total += leg.cost
    return arcs, length, cost_total


def generate_candidates(
    graph: Graph,
    start: LatLon,
    distance_m: float,
    prefs: Preferences = Preferences(),
    coverage: Mapping[int, float] = {},
    *,
    seed: int = 0,
    k: int = K,
) -> list[Candidate]:
    """Up to ``k`` loop candidates around ``start``, one per bearing, best distance fit first per bearing.

    Raises ``ValueError`` when no routable node is within 150 m of the start.
    """
    if distance_m <= 0:
        raise ValueError("distance must be positive")
    s = graph.nearest_node(start, START_SNAP_M)
    if s is None:
        raise ValueError("no street or path within 150 m of the start")
    rng = random.Random(seed)
    area = _area(graph, s, distance_m / 2 + AREA_PAD_M)
    out: list[Candidate] = []
    seen: set[tuple[tuple[int, bool], ...]] = set()
    for j in range(k):
        theta = 360.0 * j / k + rng.uniform(-W1_JITTER_DEG, W1_JITTER_DEG)
        theta2 = theta + W2_OFFSET_DEG + rng.uniform(-W2_JITTER_DEG, W2_JITTER_DEG)
        r = RADIUS_FACTOR * distance_m / (2 * math.pi)
        best: Candidate | None = None
        for attempt in range(1, FIT_RETRIES + 2):  # the first try plus up to 3 retries
            w1 = _snap_xy(graph, _offset(graph, s, r, theta), WAYPOINT_SNAP_M, area)
            w2 = _snap_xy(graph, _offset(graph, s, r, theta2), WAYPOINT_SNAP_M, area)
            if w1 is None or w2 is None or len({s, w1, w2}) < 3:
                break
            built = _loop(graph, [s, w1, w2, s], prefs, coverage, area)
            if built is None:
                break
            arcs, length, cost = built
            cand = Candidate(theta % 360, [s, w1, w2], arcs, length, cost, attempt,
                             (length - distance_m) / distance_m, {e for e, _ in arcs})
            if best is None or abs(cand.distance_error) < abs(best.distance_error):
                best = cand
            if cand.fits() or length <= 0:
                break
            r *= distance_m / length
        if best is not None:
            key = tuple(best.arcs)
            if key not in seen:
                seen.add(key)
                out.append(best)
    return out
