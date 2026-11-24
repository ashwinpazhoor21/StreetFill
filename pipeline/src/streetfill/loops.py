"""Candidate loops for a target distance (plan 6.3). All numbers are [Tune] for the week-3 spike.

1. **Snap the start** to the nearest routable node within 150 m.
2. **Radius** for a target distance D: ``r = 1.1 · D / (2π)``.
3. **Waypoints.** For each of K = 24 bearings θ (evenly spaced, plus up to ±5°
   of jitter), W1 sits at distance r on bearing θ and W2 at bearing θ + 60°
   (±15° of jitter).
   **Rewarding nodes.** Each waypoint snaps to the most rewarding node within
   200 m, the nearest on a tie (to 0.01). A node's reward, from the edges that meet
   there: ``n × new share + selected-scenery share + 0.3 × highlights`` within
   75 m (up to three). New means coverage under 50%, as in scoring. With no
   preferences and no highlights every reward is 0, so this is plain nearest
   snapping.
   **Scenery pull.** Targets are the nodes of edges flagged with Waterfront,
   and the nodes nearest the highlights for Beaches (beach), Parks (park) and
   Landmarks (landmark, historic), when that chip is selected. Only targets
   within D/2 of the start count. Of the targets within 30° of a waypoint's
   bearing, the one nearest that waypoint wins and the waypoint moves onto
   it. At most one waypoint per loop moves.
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
from typing import AbstractSet, Callable, Mapping, Sequence

from .costs import MIN_FACTOR, Preferences, make_cost
from .geo import LatLon, bearing_diff_deg, bearing_xy_deg
from .route_highlights import HighlightGrid, HighlightPoint
from .routing import Graph, Route
from .scenery import BEACH, HIGHLIGHT, PARK, WATER, WITHIN_M

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
NEW_BELOW = 0.5  # coverage under this counts as new (6.5)
HIGHLIGHT_REWARD = 0.3
HIGHLIGHT_M = WITHIN_M[HIGHLIGHT]
MAX_HIGHLIGHTS = 3
PULL_SECTOR_DEG = 30.0  # half the W1–W2 spacing
PULL_CATEGORIES = {BEACH: ("beach",), PARK: ("park",), HIGHLIGHT: ("landmark", "historic")}


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
    pulled: int = 0  # which waypoint the scenery pull moved: 1 (W1), 2 (W2) or 0 (none)

    def fits(self, tolerance: float = FIT_TOLERANCE) -> bool:
        return abs(self.distance_error) <= tolerance


def _offset(graph: Graph, origin: int, distance_m: float, bearing_deg: float) -> tuple[float, float]:
    x, y = graph.xy[origin]
    t = math.radians(bearing_deg)
    return x + distance_m * math.sin(t), y + distance_m * math.cos(t)


def _nearby(graph: Graph, xy: tuple[float, float], max_m: float, allowed: AbstractSet[int] | None):
    for i in graph.nodes_near(xy, max_m):
        if allowed is not None and i not in allowed:
            continue
        d = math.dist(xy, graph.xy[i])
        if d <= max_m:
            yield d, i


def _snap_xy(graph: Graph, xy: tuple[float, float], max_m: float, allowed: AbstractSet[int] | None,
             reward: Callable[[int], float] | None = None) -> int | None:
    """The most rewarding node within ``max_m`` (the nearest on a tie, or when there is no reward).

    Rewards are compared to 0.01, so tiny differences in edge length do not beat distance.
    """
    best = None
    for d, i in _nearby(graph, xy, max_m, allowed):
        key = (-round(reward(i), 2) if reward else 0.0, d, i)  # rewards within 0.01 are a tie
        if best is None or key < best:
            best = key
    return best[2] if best else None


class NodeRewards:
    """How rewarding a node is as a waypoint (6.3 step 4), computed on demand and cached."""

    def __init__(self, graph: Graph, prefs: Preferences, coverage: Mapping[int, float],
                 highlights: HighlightGrid | None = None) -> None:
        self.graph, self.prefs, self.coverage, self.highlights = graph, prefs, coverage, highlights
        self._cache: dict[int, float] = {}

    def __call__(self, i: int) -> float:
        if i not in self._cache:
            self._cache[i] = self._reward(i)
        return self._cache[i]

    def _reward(self, i: int) -> float:
        total = new = scenic = 0.0
        for _, eid, _ in self.graph.adj[i]:
            e = self.graph.edges[eid]
            total += e.length_m
            if e.layer in ("street", "path") and e.pack_id is not None and self.coverage.get(e.pack_id, 0.0) < NEW_BELOW:
                new += e.length_m
            if e.scenery & self.prefs.scenery:
                scenic += e.length_m
        r = 0.0
        if total > 0:
            r += self.prefs.newness * new / total + scenic / total
        if self.highlights is not None:
            r += HIGHLIGHT_REWARD * min(self.highlights.count_near(self.graph.xy[i], HIGHLIGHT_M), MAX_HIGHLIGHTS)
        return r


def pull_targets(graph: Graph, start: int, distance_m: float, prefs: Preferences,
                 highlights: Sequence[HighlightPoint] = (), allowed: AbstractSet[int] | None = None) -> list[int]:
    """Nodes the scenery pull can move a waypoint onto (6.3 step 5), within D/2 of the start."""
    reach = distance_m / 2
    sxy = graph.xy[start]
    out: set[int] = set()
    if prefs.scenery & WATER:
        for e in graph.edges.values():
            if e.scenery & WATER:
                out.update((e.u, e.v))
    cats = {c for bit, group in PULL_CATEGORIES.items() if prefs.scenery & bit for c in group}
    for h in highlights:
        if h.category in cats:
            n = _snap_xy(graph, h.xy, WAYPOINT_SNAP_M, allowed)
            if n is not None:
                out.add(n)
    return sorted(i for i in out if i != start and (allowed is None or i in allowed)
                  and math.dist(sxy, graph.xy[i]) <= reach)


def _pull(graph: Graph, start: int, targets: Sequence[int], wanted: Sequence[tuple[float, tuple[float, float]]]):
    """(waypoint index, node) for the one waypoint to move, or None.

    ``wanted`` is each waypoint's bearing and its unsnapped position.
    """
    best = None
    sxy = graph.xy[start]
    for t in targets:
        b = bearing_xy_deg(sxy, graph.xy[t])
        for w, (bearing, xy) in enumerate(wanted):
            if bearing_diff_deg(b, bearing) <= PULL_SECTOR_DEG:
                key = (math.dist(xy, graph.xy[t]), w, t)
                if best is None or key < best:
                    best = key
    return (best[1], best[2]) if best else None


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
    highlights: Sequence[HighlightPoint] = (),
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
    reward = NodeRewards(graph, prefs, coverage, HighlightGrid(highlights) if highlights else None)
    targets = pull_targets(graph, s, distance_m, prefs, highlights, area)
    out: list[Candidate] = []
    seen: set[tuple[tuple[int, bool], ...]] = set()
    for j in range(k):
        theta = 360.0 * j / k + rng.uniform(-W1_JITTER_DEG, W1_JITTER_DEG)
        theta2 = theta + W2_OFFSET_DEG + rng.uniform(-W2_JITTER_DEG, W2_JITTER_DEG)
        r = RADIUS_FACTOR * distance_m / (2 * math.pi)
        best: Candidate | None = None
        for attempt in range(1, FIT_RETRIES + 2):  # the first try plus up to 3 retries
            p1, p2 = _offset(graph, s, r, theta), _offset(graph, s, r, theta2)
            w1 = _snap_xy(graph, p1, WAYPOINT_SNAP_M, area, reward)
            w2 = _snap_xy(graph, p2, WAYPOINT_SNAP_M, area, reward)
            pulled = _pull(graph, s, targets, [(theta % 360, p1), (theta2 % 360, p2)]) if targets else None
            if pulled is not None and pulled[1] in (w2 if pulled[0] == 0 else w1, s):
                pulled = None  # the pull would land on the other waypoint
            if pulled is not None:
                w1, w2 = (pulled[1], w2) if pulled[0] == 0 else (w1, pulled[1])
            if w1 is None or w2 is None or len({s, w1, w2}) < 3:
                break
            built = _loop(graph, [s, w1, w2, s], prefs, coverage, area)
            if built is None:
                break
            arcs, length, cost = built
            cand = Candidate(theta % 360, [s, w1, w2], arcs, length, cost, attempt,
                             (length - distance_m) / distance_m, {e for e, _ in arcs},
                             pulled[0] + 1 if pulled else 0)
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
