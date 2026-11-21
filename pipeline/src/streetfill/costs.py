"""Edge cost for route generation (plan 6.2). All weights are [Tune] for the week-3 spike.

For each edge direction::

    cost(e) = length(e) × max(0.15, 1 + T(e) + Q(e) + R(e) − N(e) − V(e))

* **T, terrain.** The Flat · Rolling · Hilly slider ``s`` runs from −1 to +1.
  The grade g = |rise| ÷ length, in %, where rise is the net climb (gain −
  loss), so it is the same both ways. Flat (s < 0): ``+0.25·|s|·max(0, g −
  1.5)``. Hilly (s > 0): ``−0.5·s·min(g, 8)/8``. Rolling (s = 0) and edges
  without elevation: 0.
* **Q, quiet.** Always: steps +1.0, primary and trunk +0.15. With "quiet
  streets" on, also: primary and trunk +0.6, secondary +0.3. The plan names
  only primary for the default; trunk is at least as busy, so it is treated
  the same.
* **R, reuse.** +2.0 if the edge is already in this route, in either
  direction. The loop generator passes the edges used so far, and passes a
  smaller penalty for an out-and-back's return leg (plan 6.3 step 8).
* **N, newness.** The New-to-me slider ``n`` runs from 0 to 1:
  ``0.8·n·(1 − cov) − 0.2·n·cov``, where cov is the user's coverage of that
  pack edge (0 to 1; edges never run are 0). Steps and connectors never
  count, so they get no newness term.
* **V, scenery.** +0.5 for each selected scenery flag present on the edge,
  capped at 0.8.

The 0.15 floor keeps every cost positive, and it is the ``min_factor`` that
keeps A*'s straight-line heuristic admissible (:data:`MIN_FACTOR`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AbstractSet, Mapping

from .routing import Cost, GraphEdge

MIN_FACTOR = 0.15
REUSE_PENALTY = 2.0


@dataclass(frozen=True)
class Preferences:
    terrain: float = 0.0  # s: −1 flat … 0 rolling … +1 hilly
    quiet: bool = False
    newness: float = 0.0  # n: 0 … 1
    scenery: int = 0  # selected scenery bits (streetfill.scenery: WATER | BEACH | PARK | HIGHLIGHT)

    def __post_init__(self):
        if not -1.0 <= self.terrain <= 1.0:
            raise ValueError("terrain must be between -1 (flat) and +1 (hilly)")
        if not 0.0 <= self.newness <= 1.0:
            raise ValueError("newness must be between 0 and 1")


def grade_pct(edge: GraphEdge) -> float:
    if edge.gain_m is None or edge.loss_m is None or edge.length_m <= 0:
        return 0.0
    return abs(edge.gain_m - edge.loss_m) / edge.length_m * 100.0


def terrain_term(edge: GraphEdge, s: float) -> float:
    g = grade_pct(edge)
    if s < 0:
        return 0.25 * -s * max(0.0, g - 1.5)
    if s > 0:
        return -0.5 * s * min(g, 8.0) / 8.0
    return 0.0


def quiet_term(edge: GraphEdge, quiet: bool) -> float:
    hw = edge.highway
    q = 0.0
    if edge.layer == "steps" or hw == "steps":
        q += 1.0
    if hw in ("primary", "trunk"):
        q += 0.15 + (0.6 if quiet else 0.0)
    elif hw == "secondary" and quiet:
        q += 0.3
    return q


def newness_term(edge: GraphEdge, n: float, coverage: Mapping[int, float]) -> float:
    if n == 0 or edge.layer not in ("street", "path") or edge.pack_id is None:
        return 0.0
    cov = min(1.0, max(0.0, coverage.get(edge.pack_id, 0.0)))
    return 0.8 * n * (1 - cov) - 0.2 * n * cov


def scenery_term(edge: GraphEdge, selected: int) -> float:
    return min(0.8, 0.5 * bin(edge.scenery & selected).count("1"))


def factor(
    edge: GraphEdge,
    prefs: Preferences,
    coverage: Mapping[int, float] = {},
    used: AbstractSet[int] = frozenset(),
    reuse_penalty: float = REUSE_PENALTY,
) -> float:
    """The multiplier on the edge's length (direction does not matter for the plan's terms)."""
    r = reuse_penalty if edge.id in used else 0.0
    f = (
        1.0
        + terrain_term(edge, prefs.terrain)
        + quiet_term(edge, prefs.quiet)
        + r
        - newness_term(edge, prefs.newness, coverage)
        - scenery_term(edge, prefs.scenery)
    )
    return max(MIN_FACTOR, f)


def make_cost(
    prefs: Preferences,
    coverage: Mapping[int, float] = {},
    used: AbstractSet[int] = frozenset(),
    reuse_penalty: float = REUSE_PENALTY,
) -> Cost:
    """A cost function for :meth:`streetfill.routing.Graph.shortest_path` (use ``min_factor=MIN_FACTOR``)."""

    def cost(edge: GraphEdge, forward: bool) -> float:
        return edge.length_m * factor(edge, prefs, coverage, used, reuse_penalty)

    return cost


def coverage_from_result(result: Mapping) -> dict[int, float]:
    """Per pack edge coverage (visited ÷ checkpoints) from a ``streetfill match`` result."""
    return {int(eid): (hit / total if total else 0.0) for eid, (hit, total) in result.get("edges", {}).items()}
