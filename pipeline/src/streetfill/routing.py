"""Routing graph and shortest paths (plan 5.2 and 6.1).

The graph is every edge in a pack, on all layers (streets, paths, steps), in
both directions. On foot, one-way streets are ignored; ``foot=no`` ways never
reach a pack.

**Connectors** (plan 5.2: "streets + paths + short crossing connectors"). A
path that ends near a street or another path without sharing a node with it
(common where a footway is drawn up to the kerb but not joined) would be a dead
end. Every node with only one edge on the path or steps layer is joined to the
nearest node of another way within ``CONNECTOR_M`` (15 m [Tune]), unless the
two are already within two edges of each other. Connectors have negative edge
ids and layer ``connector``.

**Joining at shared vertices.** Packs split streets only at street junctions,
so a footway that meets a street mid-block ends on one of the street edge's
interior vertices. The graph splits any edge at an interior vertex where
another edge ends (coordinates are exact copies of the OSM node's, so they are
compared exactly). Each piece keeps its pack edge in ``pack_id``. A piece's
length is measured; its rise and fall come from the matching part of the
parent's elevation profile.

Node elevation is the first or last value of an edge's elevation profile;
every edge at a node agrees on it, because profiles keep their sampled ends.

:func:`shortest_path` is A* with a pluggable cost per edge direction. The
heuristic is straight-line distance times ``min_factor``. That factor must not
exceed the smallest cost per metre the cost function can return (0.15 for the
plan 6.2 cost), so the search stays admissible.
"""

from __future__ import annotations

import heapq
import math
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from .geo import XY, LatLon, LocalProjection, haversine_m
from .pack import decode_elevation, decode_geometry

CONNECTOR_M = 15.0
NODE_CELL_M = 100.0


@dataclass
class GraphEdge:
    id: int  # the pack edge id when unsplit; negative for pieces of split edges and for connectors
    u: int  # node index at the start of the geometry
    v: int  # node index at the end
    length_m: float
    highway: str
    layer: str  # street, path, steps or connector
    street_id: int | None = None
    gain_m: float | None = None  # u -> v; swap for v -> u
    loss_m: float | None = None
    scenery: int = 0
    neighborhood_id: int | None = None
    coords: list[LatLon] = field(default_factory=list, repr=False)
    pack_id: int | None = None  # the pack edge this is (part of); None for connectors

    def rise(self, forward: bool) -> float | None:
        if self.gain_m is None:
            return None
        return self.gain_m if forward else self.loss_m


@dataclass
class Route:
    nodes: list[int]  # node indices, start to end
    arcs: list[tuple[int, bool]]  # (edge id, forward) in order
    length_m: float
    cost: float


#: ``cost(edge, forward) -> cost of traversing the edge in that direction``
Cost = Callable[[GraphEdge, bool], float]


def length_cost(edge: GraphEdge, forward: bool) -> float:
    return edge.length_m


def _profile_part(profile: list[float], f0: float, f1: float) -> list[float]:
    """The part of an evenly sampled profile between fractions ``f0`` and ``f1`` of the edge."""
    n = len(profile) - 1

    def at(f: float) -> float:
        x = f * n
        i = min(int(x), n - 1) if n else 0
        t = x - i
        return profile[i] if n == 0 else profile[i] + (profile[i + 1] - profile[i]) * t

    inner = [profile[k] for k in range(n + 1) if f0 * n < k < f1 * n]
    return [at(f0), *inner, at(f1)]


def _rise_fall(profile: list[float]) -> tuple[float, float]:
    up = sum(max(0.0, b - a) for a, b in zip(profile, profile[1:]))
    down = sum(max(0.0, a - b) for a, b in zip(profile, profile[1:]))
    return round(up, 1), round(down, 1)


class Graph:
    def __init__(self, node_ids: list[int], coords: list[LatLon], elevation: list[float | None],
                 edges: list[GraphEdge], projection: LocalProjection):
        self.node_ids = node_ids
        self.coords = coords
        self.elevation = elevation
        self.edges = {e.id: e for e in edges}
        self.projection = projection
        self.xy: list[XY] = [projection.to_xy(p) for p in coords]
        self.adj: list[list[tuple[int, int, bool]]] = [[] for _ in node_ids]  # (to, edge id, forward)
        for e in edges:
            self._link(e)
        self._grid: dict[tuple[int, int], list[int]] = {}
        for i, (x, y) in enumerate(self.xy):
            self._grid.setdefault(self._cell(x, y), []).append(i)

    def _link(self, e: GraphEdge) -> None:
        self.adj[e.u].append((e.v, e.id, True))
        if e.v != e.u:
            self.adj[e.v].append((e.u, e.id, False))
        else:
            self.adj[e.u].append((e.u, e.id, False))  # a loop can be run either way round

    @staticmethod
    def _cell(x: float, y: float) -> tuple[int, int]:
        return math.floor(x / NODE_CELL_M), math.floor(y / NODE_CELL_M)

    # --- loading ------------------------------------------------------------------

    @classmethod
    def from_pack(cls, path: str | Path, *, connectors: bool = True) -> "Graph":
        con = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
        try:
            meta = dict(con.execute("SELECT key, value FROM meta"))
            rows = con.execute(
                "SELECT id, street_id, from_node, to_node, highway, length_m, layer, geometry, elevation, "
                "gain_m, loss_m, scenery, neighborhood_id FROM edges ORDER BY id"
            ).fetchall()
        finally:
            con.close()
        proj = LocalProjection(float(meta["origin_lat"]), float(meta["origin_lon"]))
        index: dict[int, int] = {}
        node_ids: list[int] = []
        coords: list[LatLon] = []
        elevation: list[float | None] = []
        edges: list[GraphEdge] = []

        def node(osm_id: int, at: LatLon, ele: float | None) -> int:
            i = index.get(osm_id)
            if i is None:
                i = index[osm_id] = len(node_ids)
                node_ids.append(osm_id)
                coords.append(at)
                elevation.append(ele)
            elif elevation[i] is None and ele is not None:
                elevation[i] = ele
            return i

        decoded = []
        ends: dict[LatLon, int] = {}  # end coordinate -> pack node id
        for eid, sid, a, b, hw, length, layer, blob, ele_blob, gain, loss, scenery, hood in rows:
            geom = decode_geometry(blob)
            profile = decode_elevation(ele_blob) if ele_blob else None
            decoded.append((eid, sid, a, b, hw, length, layer, geom, profile, gain, loss, scenery or 0, hood))
            ends.setdefault(geom[0], a)
            ends.setdefault(geom[-1], b)

        next_piece = -1
        for eid, sid, a, b, hw, length, layer, geom, profile, gain, loss, scenery, hood in decoded:
            cuts = [k for k in range(1, len(geom) - 1) if geom[k] in ends]
            if not cuts:
                u = node(a, geom[0], profile[0] if profile else None)
                v = node(b, geom[-1], profile[-1] if profile else None)
                edges.append(GraphEdge(eid, u, v, length, hw, layer, sid, gain, loss, scenery, hood, geom, eid))
                continue
            seg = [haversine_m(p, q) for p, q in zip(geom, geom[1:])]
            total = sum(seg) or 1.0
            at = [0.0]
            for d in seg:
                at.append(at[-1] + d)
            bounds = [0, *cuts, len(geom) - 1]
            for k0, k1 in zip(bounds, bounds[1:]):
                piece = geom[k0 : k1 + 1]
                f0, f1 = at[k0] / total, at[k1] / total
                sub = _profile_part(profile, f0, f1) if profile else None
                pid_a = a if k0 == 0 else ends[geom[k0]]
                pid_b = b if k1 == len(geom) - 1 else ends[geom[k1]]
                u = node(pid_a, piece[0], sub[0] if sub else None)
                v = node(pid_b, piece[-1], sub[-1] if sub else None)
                g_up, g_down = _rise_fall(sub) if sub else (None, None)
                edges.append(GraphEdge(next_piece, u, v, at[k1] - at[k0], hw, layer, sid, g_up, g_down, scenery,
                                       hood, piece, eid))
                next_piece -= 1
        graph = cls(node_ids, coords, elevation, edges, proj)
        if connectors:
            graph.add_connectors()
        return graph

    # --- connectors ---------------------------------------------------------------

    def _ways_at(self, i: int) -> set[int]:
        return {eid for _, eid, _ in self.adj[i]}

    def _within_two_edges(self, a: int, b: int) -> bool:
        first = {to for to, _, _ in self.adj[a]}
        return b in first or any(b == to for n in first for to, _, _ in self.adj[n])

    def add_connectors(self, max_m: float = CONNECTOR_M) -> int:
        """Join dead-end path and steps nodes to a nearby node of another way. Returns how many were added."""
        added = 0
        next_id = min([0, *self.edges]) - 1
        for i in range(len(self.node_ids)):
            arcs = self.adj[i]
            if len(arcs) != 1 or self.edges[arcs[0][1]].layer not in ("path", "steps"):
                continue
            own = self._ways_at(i)
            best, best_d = None, max_m
            for j in self.nodes_near(self.xy[i], max_m):
                if j == i or self._ways_at(j) & own:
                    continue
                d = math.dist(self.xy[i], self.xy[j])
                if d <= best_d and not self._within_two_edges(i, j):
                    best, best_d = j, d
            if best is None:
                continue
            length = haversine_m(self.coords[i], self.coords[best])
            if length <= 0:
                continue
            e = GraphEdge(next_id, i, best, length, "connector", "connector",
                          coords=[self.coords[i], self.coords[best]], pack_id=None)
            self.edges[e.id] = e
            self._link(e)
            next_id -= 1
            added += 1
        return added

    # --- queries ------------------------------------------------------------------

    def nodes_near(self, xy: XY, radius_m: float) -> Iterable[int]:
        x, y = xy
        c0, r0 = self._cell(x - radius_m, y - radius_m)
        c1, r1 = self._cell(x + radius_m, y + radius_m)
        for cx in range(c0, c1 + 1):
            for cy in range(r0, r1 + 1):
                yield from self._grid.get((cx, cy), ())

    def nearest_node(self, at: LatLon, max_m: float = 150.0) -> int | None:
        """The closest node within ``max_m`` (plan 6.3: snap the start within 150 m)."""
        xy = self.projection.to_xy(at)
        best = min(((math.dist(xy, self.xy[i]), i) for i in self.nodes_near(xy, max_m)), default=None)
        return best[1] if best and best[0] <= max_m else None

    def components(self) -> list[int]:
        """Sizes of the connected components, largest first."""
        seen = [False] * len(self.node_ids)
        sizes = []
        for s in range(len(self.node_ids)):
            if seen[s]:
                continue
            seen[s], stack, n = True, [s], 0
            while stack:
                a = stack.pop()
                n += 1
                for b, _, _ in self.adj[a]:
                    if not seen[b]:
                        seen[b] = True
                        stack.append(b)
            sizes.append(n)
        return sorted(sizes, reverse=True)

    def shortest_path(self, source: int, target: int, cost: Cost = length_cost, *,
                      min_factor: float = 1.0) -> Route | None:
        """A* from ``source`` to ``target``, or None when they are not connected."""
        tx, ty = self.xy[target]

        def h(i: int) -> float:
            x, y = self.xy[i]
            return math.hypot(x - tx, y - ty) * min_factor

        best = {source: 0.0}
        back: dict[int, tuple[int, int, bool]] = {}
        heap = [(h(source), 0.0, source)]
        done = set()
        while heap:
            _, g, a = heapq.heappop(heap)
            if a in done:
                continue
            if a == target:
                break
            done.add(a)
            for b, eid, fwd in self.adj[a]:
                ng = g + cost(self.edges[eid], fwd)
                if ng < best.get(b, math.inf):
                    best[b] = ng
                    back[b] = (a, eid, fwd)
                    heapq.heappush(heap, (ng + h(b), ng, b))
        if target not in best:
            return None
        nodes, arcs = [target], []
        while nodes[-1] != source:
            a, eid, fwd = back[nodes[-1]]
            arcs.append((eid, fwd))
            nodes.append(a)
        nodes.reverse()
        arcs.reverse()
        return Route(nodes, arcs, sum(self.edges[e].length_m for e, _ in arcs), best[target])
