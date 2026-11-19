"""City and neighborhood boundaries: clip a network and split it by area (plan 5.6).

An :class:`Area` is a polygon or multipolygon (rings in ``(lat, lon)``; holes are
handled by the even-odd rule over all rings). :func:`assign_areas`:

1. cuts every edge where it crosses the city boundary or a neighborhood
   boundary, adding a node at each crossing;
2. drops the pieces outside the city (when a city is given);
3. tags each remaining piece with the neighborhood that contains it, or
   ``None`` when it is in no neighborhood.

Each piece lies in exactly one neighborhood (or none), so neighborhood lengths
plus the unassigned length always add up to the city total. Overlapping
neighborhoods are resolved by input order: the first one wins.

New nodes at crossings get negative ids (``-1, -2, ...``) so they never clash
with OSM node ids. Edge ids are renumbered from 1; output order is deterministic.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from .geo import XY, LatLon, LocalProjection, haversine_m
from .network import Edge, Network, Street

Ring = tuple[LatLon, ...]
#: Pieces closer than this (metres) to a vertex are cut at the vertex itself.
SNAP_M = 0.01
INDEX_CELL_M = 200.0


@dataclass(frozen=True)
class Area:
    id: str
    name: str
    rings: tuple[Ring, ...]  # outer rings and holes; even-odd rule


# --- GeoJSON ------------------------------------------------------------------------

def _rings_from_geometry(geom: Mapping[str, Any]) -> list[Ring]:
    kind = geom.get("type")
    if kind == "Polygon":
        polygons = [geom["coordinates"]]
    elif kind == "MultiPolygon":
        polygons = geom["coordinates"]
    else:
        raise ValueError(f"expected Polygon or MultiPolygon, got {kind!r}")
    rings = []
    for polygon in polygons:
        for ring in polygon:
            pts = tuple((float(lat), float(lon)) for lon, lat, *_ in ring)
            if len(pts) >= 3:
                rings.append(pts)
    if not rings:
        raise ValueError("geometry has no rings")
    return rings


def area_from_geojson(obj: Mapping[str, Any], id: str, name: str | None = None) -> Area:
    """Area from a GeoJSON Feature or bare Polygon/MultiPolygon geometry."""
    geom = obj["geometry"] if obj.get("type") == "Feature" else obj
    return Area(id=id, name=name or id, rings=tuple(_rings_from_geometry(geom)))


def load_areas(path: str | Path, id_property: str = "id", name_property: str = "name") -> list[Area]:
    """Areas from a GeoJSON FeatureCollection (or a single Feature)."""
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    features = doc["features"] if doc.get("type") == "FeatureCollection" else [doc]
    areas = []
    for i, f in enumerate(features, start=1):
        props = f.get("properties") or {}
        area_id = str(props.get(id_property) or i)
        name = props.get(name_property)
        try:
            areas.append(area_from_geojson(f, area_id, str(name) if name else None))
        except (KeyError, ValueError) as exc:
            raise ValueError(f"{path}: feature {i}: {exc}") from exc
    ids = [a.id for a in areas]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{path}: duplicate area ids")
    return areas


# --- spatial index over boundary segments -------------------------------------------

class _BoundaryIndex:
    """Ring segments of several areas, indexed for crossing and containment tests."""

    def __init__(self, areas: Sequence[Area], proj: LocalProjection, cell_m: float = INDEX_CELL_M):
        self.cell = cell_m
        self.segs: list[tuple[float, float, float, float, int]] = []
        self.cells: dict[tuple[int, int], list[int]] = {}
        self.bands: dict[int, list[int]] = {}
        for ai, area in enumerate(areas):
            for ring in area.rings:
                pts = [proj.to_xy(p) for p in ring]
                if pts[0] != pts[-1]:
                    pts.append(pts[0])
                for (ax, ay), (bx, by) in zip(pts, pts[1:]):
                    if (ax, ay) == (bx, by):
                        continue
                    si = len(self.segs)
                    self.segs.append((ax, ay, bx, by, ai))
                    cx0, cx1 = self._c(min(ax, bx)), self._c(max(ax, bx))
                    cy0, cy1 = self._c(min(ay, by)), self._c(max(ay, by))
                    for cy in range(cy0, cy1 + 1):
                        self.bands.setdefault(cy, []).append(si)
                        for cx in range(cx0, cx1 + 1):
                            self.cells.setdefault((cx, cy), []).append(si)

    def _c(self, v: float) -> int:
        return math.floor(v / self.cell)

    def areas_at(self, p: XY) -> set[int]:
        """Indices of the areas containing ``p`` (horizontal ray, even-odd rule)."""
        px, py = p
        inside: set[int] = set()
        for si in self.bands.get(self._c(py), ()):
            ax, ay, bx, by, ai = self.segs[si]
            if (ay > py) != (by > py) and px < ax + (py - ay) * (bx - ax) / (by - ay):
                inside ^= {ai}
        return inside

    def crossings(self, p: XY, q: XY) -> list[float]:
        """Parameters ``t`` in [0, 1] where segment p→q meets a boundary segment."""
        px, py = p
        rx, ry = q[0] - px, q[1] - py
        seen: set[int] = set()
        out = []
        for cy in range(self._c(min(py, q[1])), self._c(max(py, q[1])) + 1):
            for cx in range(self._c(min(px, q[0])), self._c(max(px, q[0])) + 1):
                for si in self.cells.get((cx, cy), ()):
                    if si in seen:
                        continue
                    seen.add(si)
                    ax, ay, bx, by, _ = self.segs[si]
                    sx, sy = bx - ax, by - ay
                    denom = rx * sy - ry * sx
                    if abs(denom) < 1e-12:
                        continue  # parallel or collinear: no single crossing point
                    wx, wy = ax - px, ay - py
                    t = (wx * sy - wy * sx) / denom
                    u = (wx * ry - wy * rx) / denom
                    if -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= u <= 1 + 1e-9:
                        out.append(min(1.0, max(0.0, t)))
        return out


# --- splitting --------------------------------------------------------------------

def _cut_positions(xy: Sequence[XY], index: _BoundaryIndex) -> list[float]:
    """Sorted positions (vertex index + fraction along the next segment) to cut at."""
    last = len(xy) - 1
    cuts: set[float] = set()
    for i in range(last):
        seg = math.dist(xy[i], xy[i + 1])
        for t in index.crossings(xy[i], xy[i + 1]):
            if t * seg < SNAP_M:
                pos = float(i)
            elif (1 - t) * seg < SNAP_M:
                pos = float(i + 1)
            else:
                pos = i + t
            if 0 < pos < last:
                cuts.add(pos)
    return sorted(cuts)


def _point_at(xy: Sequence[XY], pos: float) -> XY:
    i = int(pos)
    t = pos - i
    if t == 0:
        return xy[i]
    (ax, ay), (bx, by) = xy[i], xy[i + 1]
    return (ax + (bx - ax) * t, ay + (by - ay) * t)


def assign_areas(
    network: Network,
    *,
    city: Area | None = None,
    neighborhoods: Sequence[Area] = (),
    projection: LocalProjection | None = None,
) -> Network:
    """Clip ``network`` to ``city`` and tag edges with their neighborhood id."""
    if not network.edges:
        return Network(streets=[], edges=[])
    proj = projection or LocalProjection.for_points(p for e in network.edges for p in e.coords)
    areas = ([city] if city else []) + list(neighborhoods)
    first_hood = 1 if city else 0
    index = _BoundaryIndex(areas, proj)
    next_node = -1

    def label(inside: set[int]) -> tuple[bool, str | None]:
        in_city = city is None or 0 in inside
        hoods = sorted(i for i in inside if i >= first_hood)
        return in_city, (areas[hoods[0]].id if hoods else None)

    edges: list[Edge] = []
    for e in network.edges:
        xy = [proj.to_xy(p) for p in e.coords]
        cuts = _cut_positions(xy, index)
        bounds = [0.0] + cuts + [float(len(xy) - 1)]

        # pieces between consecutive cuts, labelled by a point inside each one
        pieces: list[tuple[tuple[bool, str | None], list[float]]] = []
        for s0, s1 in zip(bounds, bounds[1:]):
            inner = [float(k) for k in range(math.floor(s0) + 1, math.ceil(s1))]
            positions = [s0, *inner, s1]
            a, b = _point_at(xy, positions[0]), _point_at(xy, positions[1])
            lab = label(index.areas_at(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)))
            if pieces and pieces[-1][0] == lab:
                # the same area on both sides of a cut (a touch, not a crossing): merge
                prev = pieces[-1][1]
                if not prev[-1].is_integer():
                    prev.pop()  # the cut point is no longer needed
                prev.extend(positions[1:])
            else:
                pieces.append((lab, positions))

        new_node: dict[float, int] = {}

        def node(pos: float) -> int:
            nonlocal next_node
            if pos.is_integer():
                return e.node_ids[int(pos)]
            if pos not in new_node:
                new_node[pos] = next_node
                next_node -= 1
            return new_node[pos]

        for (in_city, hood), positions in pieces:
            if not in_city:
                continue
            coords = [e.coords[int(p)] if p.is_integer() else proj.to_latlon(_point_at(xy, p)) for p in positions]
            length = sum(haversine_m(a, b) for a, b in zip(coords, coords[1:]))
            if length <= 0:
                continue
            nodes = [node(p) for p in positions]
            edges.append(
                replace(
                    e,
                    id=len(edges) + 1,
                    from_node=nodes[0],
                    to_node=nodes[-1],
                    node_ids=nodes,
                    coords=coords,
                    length_m=length,
                    neighborhood=hood,
                )
            )

    by_key = {s.key: s for s in network.streets}
    streets: dict[str, Street] = {}
    for e in edges:
        s = streets.get(e.street_key)
        if s is None:
            old = by_key[e.street_key]
            s = streets[e.street_key] = Street(old.key, old.name, old.highway, layer=old.layer)
        s.edge_ids.append(e.id)
        s.length_m += e.length_m
    order = {s.key: i for i, s in enumerate(network.streets)}
    return Network(streets=sorted(streets.values(), key=lambda s: order[s.key]), edges=edges)


def area_lengths(network: Network, layer: str | None = "street") -> dict[str | None, float]:
    """Length per neighborhood id (``None`` = in no neighborhood), for one layer or all."""
    out: dict[str | None, float] = {}
    for e in network.edges:
        if layer is None or e.layer == layer:
            out[e.neighborhood] = out.get(e.neighborhood, 0.0) + e.length_m
    return out


def total_length(network: Network, layer: str | None = "street") -> float:
    return sum(e.length_m for e in network.edges if layer is None or e.layer == layer)

