"""Match cleaned routes to street checkpoints and compute coverage (plan 5.4 steps 3–5).

For each cleaned route point:

1. **Candidate edges.** An edge is a candidate when the point is within the
   edge's visit radius (20 m, primary/trunk +8, secondary +5, paths 15) of the
   edge geometry *and* the route's direction is within 30° of the edge's
   direction there (either way along the edge, so out-and-backs count).
2. **Ambiguity.** The nearest candidate wins. If a candidate on a *different*
   street is within ``tie_margin_m`` (3 m) of the winner's distance, the point
   credits nothing. Candidates on the *same* street within the margin are
   credited too, so a runner between the two carriageways of a divided boulevard
   is not penalised. That same-street exception is a deviation to measure in the
   spike.
3. **Visit.** The point visits every checkpoint of the credited edges that lies
   within the edge's radius of the point, is alongside it (within
   ``along_track_m`` measured along the street) and whose direction is within 30°
   of the route's. Points where the route doubles back have no direction and
   credit nothing.

Coverage (step 5): an edge's fraction is visited ÷ total checkpoints. A street
is complete at 90% of its checkpoints. An area's covered length is
Σ edge length × edge fraction, and its percentage is covered ÷ total length.

The output that fixtures compare is :meth:`Matcher.match`: a sorted list of
``(edge_id, checkpoint_index)`` keys.
"""

from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Hashable, Iterable, Sequence

from .geo import (
    XY,
    LatLon,
    LocalProjection,
    bearing_xy_deg,
    dist_xy,
    point_segment_distance,
    undirected_bearing_diff_deg,
)
from .matching import DEFAULT_CONFIG, Checkpoint, MatchConfig, clean_route, edge_checkpoints, route_bearings

CheckpointKey = tuple[int, int]


@dataclass(frozen=True)
class MatchEdge:
    id: int
    street: Hashable
    highway: str
    coords: Sequence[LatLon]


@dataclass
class StreetCoverage:
    street: Hashable
    name: str | None
    checkpoints: int
    visited: int
    length_m: float
    covered_m: float
    complete: bool

    @property
    def fraction(self) -> float:
        return self.visited / self.checkpoints if self.checkpoints else 0.0


@dataclass
class Coverage:
    streets: dict[Hashable, StreetCoverage] = field(default_factory=dict)
    edges: dict[int, tuple[int, int]] = field(default_factory=dict)  # edge id -> (visited, total)
    total_length_m: float = 0.0
    covered_length_m: float = 0.0

    @property
    def fraction(self) -> float:
        return self.covered_length_m / self.total_length_m if self.total_length_m else 0.0

    @property
    def complete_streets(self) -> list[Hashable]:
        return sorted((s.street for s in self.streets.values() if s.complete), key=str)


@dataclass
class _EdgeGeom:
    edge: MatchEdge
    xy: list[XY]
    length_m: float
    radius_m: float
    checkpoints: list[Checkpoint]


class Matcher:
    """Matches routes against a fixed set of street edges."""

    def __init__(
        self,
        edges: Iterable[MatchEdge],
        projection: LocalProjection,
        cfg: MatchConfig = DEFAULT_CONFIG,
        street_names: dict[Hashable, str | None] | None = None,
    ) -> None:
        self.projection = projection
        self.cfg = cfg
        self.street_names = street_names or {}
        self._edges: dict[int, _EdgeGeom] = {}
        for e in edges:
            xy = [projection.to_xy(p) for p in e.coords]
            length = sum(dist_xy(a, b) for a, b in zip(xy, xy[1:]))
            if length <= 0:
                continue
            self._edges[e.id] = _EdgeGeom(
                edge=e,
                xy=xy,
                length_m=length,
                radius_m=cfg.visit_radius_for(e.highway),
                checkpoints=edge_checkpoints(e.id, e.coords, projection, cfg),
            )
        self._max_radius = max((g.radius_m for g in self._edges.values()), default=cfg.visit_radius_m)
        self._cell = max(self._max_radius, 1.0)
        self._index: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
        for eid, g in self._edges.items():
            for i, (a, b) in enumerate(zip(g.xy, g.xy[1:])):
                for cell in self._cells_for_box(min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])):
                    self._index[cell].append((eid, i))

    # --- construction helpers -----------------------------------------------------

    @classmethod
    def from_pack(cls, path: str | Path, cfg: MatchConfig = DEFAULT_CONFIG) -> "Matcher":
        from .pack import decode_geometry

        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            meta = dict(con.execute("SELECT key, value FROM meta"))
            projection = LocalProjection(float(meta["origin_lat"]), float(meta["origin_lon"]))
            names = dict(con.execute("SELECT id, name FROM streets"))
            edges = [
                MatchEdge(id=eid, street=sid, highway=hw, coords=decode_geometry(blob))
                for eid, sid, hw, blob in con.execute("SELECT id, street_id, highway, geometry FROM edges ORDER BY id")
            ]
        finally:
            con.close()
        return cls(edges, projection, cfg, street_names=names)

    @classmethod
    def from_network(cls, network, projection: LocalProjection, cfg: MatchConfig = DEFAULT_CONFIG) -> "Matcher":
        edges = [MatchEdge(e.id, e.street_key, e.highway, e.coords) for e in network.edges]
        return cls(edges, projection, cfg, street_names={s.key: s.name for s in network.streets})

    def _cells_for_box(self, x1: float, y1: float, x2: float, y2: float):
        c = self._cell
        for cx in range(math.floor(x1 / c), math.floor(x2 / c) + 1):
            for cy in range(math.floor(y1 / c), math.floor(y2 / c) + 1):
                yield (cx, cy)

    @property
    def checkpoints(self) -> list[Checkpoint]:
        return [cp for g in self._edges.values() for cp in g.checkpoints]

    # --- matching -------------------------------------------------------------------

    def _candidates(self, p: XY, bearing: float) -> dict[int, float]:
        """Edge id -> distance, for edges the point may be travelling along."""
        r = self._max_radius
        best: dict[int, tuple[float, int]] = {}
        seen: set[tuple[int, int]] = set()
        for cell in self._cells_for_box(p[0] - r, p[1] - r, p[0] + r, p[1] + r):
            for key in self._index.get(cell, ()):
                if key in seen:
                    continue
                seen.add(key)
                eid, i = key
                g = self._edges[eid]
                d = point_segment_distance(p, g.xy[i], g.xy[i + 1])
                if d <= g.radius_m and (eid not in best or d < best[eid][0]):
                    best[eid] = (d, i)
        out = {}
        for eid, (d, i) in best.items():
            g = self._edges[eid]
            seg_bearing = bearing_xy_deg(g.xy[i], g.xy[i + 1])
            if undirected_bearing_diff_deg(bearing, seg_bearing) <= self.cfg.max_bearing_diff_deg:
                out[eid] = d
        return out

    def _credited_edges(self, candidates: dict[int, float]) -> list[int]:
        if not candidates:
            return []
        winner = min(candidates, key=lambda e: (candidates[e], e))
        best_d = candidates[winner]
        street = self._edges[winner].edge.street
        credited = []
        for eid, d in candidates.items():
            if d - best_d >= self.cfg.tie_margin_m:
                continue
            if self._edges[eid].edge.street != street:
                return []  # too close to call between two different streets
            credited.append(eid)
        return credited

    def match_segments(self, segments: Iterable[Sequence[XY]]) -> list[CheckpointKey]:
        visited: set[CheckpointKey] = set()
        max_diff = self.cfg.max_bearing_diff_deg
        along = self.cfg.along_track_m
        for seg in segments:
            for p, bearing in zip(seg, route_bearings(seg, self.cfg.bearing_window_m)):
                if bearing is None:
                    continue
                for eid in self._credited_edges(self._candidates(p, bearing)):
                    g = self._edges[eid]
                    for cp in g.checkpoints:
                        if cp.key in visited:
                            continue
                        if (
                            dist_xy(p, cp.xy) <= g.radius_m
                            and _along_track(p, cp) <= along
                            and undirected_bearing_diff_deg(bearing, cp.bearing_deg) <= max_diff
                        ):
                            visited.add(cp.key)
        return sorted(visited)

    def match(self, route_points: Iterable) -> list[CheckpointKey]:
        """Sorted visited checkpoint keys for one recorded route."""
        return self.match_segments(clean_route(route_points, self.projection, self.cfg))

    # --- coverage -------------------------------------------------------------------

    def coverage(self, visited: Iterable[CheckpointKey]) -> Coverage:
        visited = set(visited)
        cov = Coverage()
        for eid, g in sorted(self._edges.items()):
            total = len(g.checkpoints)
            hit = sum(1 for cp in g.checkpoints if cp.key in visited)
            cov.edges[eid] = (hit, total)
            covered = g.length_m * hit / total if total else 0.0
            cov.total_length_m += g.length_m
            cov.covered_length_m += covered

            sid = g.edge.street
            s = cov.streets.get(sid)
            if s is None:
                s = cov.streets[sid] = StreetCoverage(sid, self.street_names.get(sid), 0, 0, 0.0, 0.0, False)
            s.checkpoints += total
            s.visited += hit
            s.length_m += g.length_m
            s.covered_m += covered
        for s in cov.streets.values():
            s.complete = s.checkpoints > 0 and s.fraction >= self.cfg.street_complete_frac
        return cov


def _along_track(p: XY, cp: Checkpoint) -> float:
    """Distance from ``cp`` to ``p`` measured along the street direction."""
    rad = math.radians(cp.bearing_deg)
    return abs((p[0] - cp.xy[0]) * math.sin(rad) + (p[1] - cp.xy[1]) * math.cos(rad))
