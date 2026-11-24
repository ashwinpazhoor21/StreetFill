"""Scoring candidate routes and choosing three (plan 6.4). All weights are [Tune] for the week-3 spike.

For each candidate (lower is better)::

    score = 3·|len − D|/D + 2·|newShare − n| + 1.5·terrainMiss
            − 1·sceneryShare − 0.3·min(highlights, 3)
            + 2·repeatedShare + 0.05·max(0, turnsPerMile − 8) + 1·deadEndSpurs

* **newShare**: the share of the route's length on street and path edges whose
  coverage is under 50% (the 6.5 definition). Edges missing from the coverage
  map have never been run. When the New-to-me slider n is 0 the user has no
  preference, so the term is 0; that matches the cost, where n = 0 is neutral.
* **terrainMiss**: how far the route's gain per mile sits outside the band the
  terrain slider asks for: flat 15 ft/mi or less (s < 0), rolling 15–50
  (s = 0), hilly 50 or more (s > 0). The plan gives the distance in ft/mi; it is
  divided by 50 ft/mi here so it is on the same scale as the shares. A route
  with no elevation data has no miss.
* **sceneryShare**: the share of the length on edges carrying a selected
  scenery flag (0 when no chip is selected).
* **highlights**: distinct pack highlights within 75 m of the route (the same
  distance as the HIGHLIGHT scenery flag).
* **repeatedShare**: the length of second and later passes over an edge, in
  either direction, as a share of the length.
* **turnsPerMile**: changes of heading of 45° or more between consecutive
  edges. Going straight back along the same edge is a spur, not a turn.
* **deadEndSpurs**: places where the route turns straight back along the edge
  it arrived on, which is how a route goes in and out of a dead end.

**Choosing three.** The best-scoring candidate first, then the next best whose
overlap with every route already chosen is under 40%, until there are three.
Overlap is the length of the edges two routes share divided by the shorter
route's length. When the streets cannot give three different routes, fewer
are returned.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

from .costs import Preferences
from .geo import XY, LatLon, bearing_diff_deg, bearing_xy_deg
from .loops import Candidate, generate_candidates
from .route_highlights import HighlightGrid, HighlightPoint, load_highlights  # noqa: F401  (re-exported)
from .routing import Graph
from .scenery import WITHIN_M, HIGHLIGHT

W_DISTANCE = 3.0
W_NEW = 2.0
W_TERRAIN = 1.5
W_SCENERY = 1.0
W_HIGHLIGHT = 0.3
MAX_HIGHLIGHTS = 3
W_REPEAT = 2.0
W_TURNS = 0.05
FREE_TURNS_PER_MILE = 8.0
W_SPUR = 1.0

NEW_BELOW = 0.5  # coverage under this counts as new (6.5)
FLAT_MAX_FT_PER_MI = 15.0
HILLY_MIN_FT_PER_MI = 50.0
TERRAIN_SCALE_FT_PER_MI = 50.0
TURN_DEG = 45.0
HIGHLIGHT_M = WITHIN_M[HIGHLIGHT]
MAX_OVERLAP = 0.40

M_PER_MI = 1609.344
FT_PER_M = 3.28084


@dataclass
class Score:
    total: float
    terms: dict[str, float]  # each weighted term, so the spike can see what drove a choice
    length_m: float
    new_share: float
    gain_m: float | None  # None when no edge on the route has elevation
    gain_ft_per_mi: float | None
    scenery_share: float
    highlights: list[int]  # highlight ids passed, in route order
    repeated_share: float
    turns: int
    turns_per_mile: float
    dead_end_spurs: int


@dataclass
class Choice:
    candidate: Candidate
    score: Score


def terrain_band(s: float) -> tuple[float, float]:
    """The gain-per-mile band (ft/mi) the terrain slider asks for."""
    if s < 0:
        return 0.0, FLAT_MAX_FT_PER_MI
    if s > 0:
        return HILLY_MIN_FT_PER_MI, math.inf
    return FLAT_MAX_FT_PER_MI, HILLY_MIN_FT_PER_MI


def terrain_miss(gain_ft_per_mi: float | None, s: float) -> float:
    if gain_ft_per_mi is None:
        return 0.0
    lo, hi = terrain_band(s)
    miss = lo - gain_ft_per_mi if gain_ft_per_mi < lo else max(0.0, gain_ft_per_mi - hi)
    return miss / TERRAIN_SCALE_FT_PER_MI


def _arc_xy(graph: Graph, eid: int, forward: bool) -> list[XY]:
    e = graph.edges[eid]
    pts = [graph.projection.to_xy(p) for p in e.coords] if len(e.coords) >= 2 else [graph.xy[e.u], graph.xy[e.v]]
    return pts if forward else pts[::-1]


def _heading(a: XY, b: XY) -> float | None:
    return None if a == b else bearing_xy_deg(a, b)


def _first_heading(pts: Sequence[XY]) -> float | None:
    for a, b in zip(pts, pts[1:]):
        if (h := _heading(a, b)) is not None:
            return h
    return None


def _along(p: XY, a: XY, b: XY) -> float:
    """How far along a → b the point's foot falls (for ordering highlights on one segment)."""
    return (p[0] - a[0]) * (b[0] - a[0]) + (p[1] - a[1]) * (b[1] - a[1])


def score_route(
    graph: Graph,
    arcs: Sequence[tuple[int, bool]],
    distance_m: float,
    prefs: Preferences = Preferences(),
    coverage: Mapping[int, float] = {},
    highlights: Sequence[HighlightPoint] | HighlightGrid = (),
) -> Score:
    """Score one route, given as (edge id, forward) arcs in order."""
    if distance_m <= 0:
        raise ValueError("distance must be positive")
    grid = highlights if isinstance(highlights, HighlightGrid) else HighlightGrid(highlights)
    length = new = scenic = repeated = 0.0
    gain = 0.0
    has_elevation = False
    seen: set[int] = set()
    passed: dict[int, None] = {}  # insertion-ordered set
    turns = spurs = 0
    prev: tuple[int, bool] | None = None
    prev_heading: float | None = None
    for eid, fwd in arcs:
        e = graph.edges[eid]
        length += e.length_m
        if e.layer in ("street", "path") and e.pack_id is not None:
            if coverage.get(e.pack_id, 0.0) < NEW_BELOW:
                new += e.length_m
        if prefs.scenery and e.scenery & prefs.scenery:
            scenic += e.length_m
        if eid in seen:
            repeated += e.length_m
        seen.add(eid)
        rise = e.rise(fwd)
        if rise is not None:
            gain += rise
            has_elevation = True
        pts = _arc_xy(graph, eid, fwd)
        if prev is not None:
            if prev[0] == eid and prev[1] != fwd:
                spurs += 1
            else:
                h = _first_heading(pts)
                if h is not None and prev_heading is not None and abs(bearing_diff_deg(prev_heading, h)) >= TURN_DEG:
                    turns += 1
        last = _first_heading(pts[::-1])
        prev_heading = None if last is None else (last + 180.0) % 360.0
        prev = (eid, fwd)
        for a, b in zip(pts, pts[1:]):
            hits = sorted(grid.near_segment(a, b, HIGHLIGHT_M), key=lambda h: _along(h.xy, a, b))
            for hl in hits:
                passed.setdefault(hl.id, None)

    miles = length / M_PER_MI
    share = (lambda x: x / length) if length > 0 else (lambda x: 0.0)
    new_share, scenery_share, repeated_share = share(new), share(scenic), share(repeated)
    gain_m = gain if has_elevation else None
    gain_rate = gain * FT_PER_M / miles if has_elevation and miles > 0 else None
    turns_per_mile = turns / miles if miles > 0 else 0.0
    terms = {
        "distance": W_DISTANCE * abs(length - distance_m) / distance_m,
        "newness": W_NEW * abs(new_share - prefs.newness) if prefs.newness > 0 else 0.0,
        "terrain": W_TERRAIN * terrain_miss(gain_rate, prefs.terrain),
        "scenery": -W_SCENERY * scenery_share,
        "highlights": -W_HIGHLIGHT * min(len(passed), MAX_HIGHLIGHTS),
        "repeated": W_REPEAT * repeated_share,
        "turns": W_TURNS * max(0.0, turns_per_mile - FREE_TURNS_PER_MILE),
        "spurs": W_SPUR * spurs,
    }
    return Score(sum(terms.values()), terms, length, new_share, gain_m, gain_rate, scenery_share,
                 list(passed), repeated_share, turns, turns_per_mile, spurs)


def overlap(graph: Graph, a: Candidate, b: Candidate) -> float:
    """Shared edge length ÷ the shorter route's length (each edge counted once)."""
    def size(ids):
        return sum(graph.edges[e].length_m for e in ids)

    shorter = min(size(a.edge_ids), size(b.edge_ids))
    return size(a.edge_ids & b.edge_ids) / shorter if shorter > 0 else 1.0


def choose(graph: Graph, scored: Sequence[Choice], n: int = 3, max_overlap: float = MAX_OVERLAP) -> list[Choice]:
    """The best, then each next best that overlaps every chosen route by under ``max_overlap``."""
    chosen: list[Choice] = []
    for c in sorted(scored, key=lambda c: c.score.total):
        if all(overlap(graph, c.candidate, k.candidate) < max_overlap for k in chosen):
            chosen.append(c)
            if len(chosen) == n:
                break
    return chosen


def best_routes(
    graph: Graph,
    start: LatLon,
    distance_m: float,
    prefs: Preferences = Preferences(),
    coverage: Mapping[int, float] = {},
    highlights: Sequence[HighlightPoint] = (),
    *,
    seed: int = 0,
    n: int = 3,
) -> list[Choice]:
    """Generate the 6.3 candidates, score them (6.4) and choose up to ``n`` different ones."""
    grid = HighlightGrid(highlights)
    scored = [
        Choice(c, score_route(graph, c.arcs, distance_m, prefs, coverage, grid))
        for c in generate_candidates(graph, start, distance_m, prefs, coverage, seed=seed)
    ]
    return choose(graph, scored, n)
