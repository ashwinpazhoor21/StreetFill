"""Neighborhood annotation for a route (plan 6.5).

For each neighborhood a route passes through: whether it is **new** (the
user's street coverage there is 0%), and the street coverage **before** and
**after** running the route, so the gain the route would bring.

Percentages count streets only, as on the map (decision D7). Coverage is the
covered fraction per pack edge. After the run, every street piece on the route
counts as fully covered; other pieces of the same pack edge keep their coverage.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .routing import Graph


@dataclass
class NeighborhoodGain:
    id: int
    name: str
    route_m: float  # street length of the route in this neighborhood, each piece counted once
    before: float  # street coverage before the run, 0–1
    after: float  # and after it

    @property
    def new(self) -> bool:
        return self.before == 0

    @property
    def gain(self) -> float:
        return self.after - self.before


def load_neighborhood_names(path: str | Path) -> dict[int, str]:
    con = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        return dict(con.execute("SELECT id, name FROM neighborhoods ORDER BY id"))
    finally:
        con.close()


class NeighborhoodCoverage:
    """Street totals and covered length per neighborhood, for one graph and one user's coverage."""

    def __init__(self, graph: Graph, coverage: Mapping[int, float], names: Mapping[int, str] = {}) -> None:
        self.graph, self.coverage, self.names = graph, coverage, names
        self.total: dict[int, float] = {}
        self.covered: dict[int, float] = {}
        for e in graph.edges.values():
            if e.layer == "street" and e.neighborhood_id is not None:
                self.total[e.neighborhood_id] = self.total.get(e.neighborhood_id, 0.0) + e.length_m
                self.covered[e.neighborhood_id] = self.covered.get(e.neighborhood_id, 0.0) + e.length_m * self._cov(e)

    def _cov(self, e) -> float:
        return min(1.0, max(0.0, self.coverage.get(e.pack_id, 0.0))) if e.pack_id is not None else 0.0

    def gains(self, arcs: Sequence[tuple[int, bool]]) -> list[NeighborhoodGain]:
        """The neighborhoods the route's streets pass through, in the order it first enters them."""
        order: list[int] = []
        route_m: dict[int, float] = {}
        added: dict[int, float] = {}
        seen: set[int] = set()
        for eid, _ in arcs:
            e = self.graph.edges[eid]
            hood = e.neighborhood_id
            if e.layer != "street" or hood is None or eid in seen:
                continue
            seen.add(eid)
            if hood not in route_m:
                order.append(hood)
                route_m[hood] = added[hood] = 0.0
            route_m[hood] += e.length_m
            added[hood] += e.length_m * (1.0 - self._cov(e))
        out = []
        for hood in order:
            total = self.total[hood]
            before = self.covered[hood] / total if total else 0.0
            after = min(1.0, (self.covered[hood] + added[hood]) / total) if total else 0.0
            out.append(NeighborhoodGain(hood, self.names.get(hood, f"Neighborhood {hood}"), route_m[hood], before, after))
        return out
