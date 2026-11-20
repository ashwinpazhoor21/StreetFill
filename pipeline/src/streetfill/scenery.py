"""Scenery flags per edge (plan 6.6), for Discover's scenery preference (6.3, V).

An edge gets a flag when any part of it is within the distance [Tune] of a
feature of that kind, or lies inside one:

=========  ===  ==========  ===========================================================
flag       bit  within      features
=========  ===  ==========  ===========================================================
WATER      1    100 m       ``natural=water`` and ``waterway=riverbank`` polygons, ``natural=coastline`` lines
BEACH      2    150 m       ``natural=beach`` polygons, named or not
PARK       4    50 m        ``leisure=park`` polygons, named or not
HIGHLIGHT  8    75 m        the pack's highlight points (``streetfill.highlights``)
=========  ===  ==========  ===========================================================

Features come from the same Overpass document as highlights
(:func:`streetfill.overpass.build_feature_query`). Distances are measured in a
local projection between edge segments and feature outlines, indexed by grid
cell; "inside" is tested at one vertex per edge, because an edge that is only
partly inside crosses the outline and is caught by the distance test.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any, Iterable, Mapping, Sequence

from .boundaries import Area, _BoundaryIndex
from .geo import XY, LatLon, LocalProjection, point_segment_distance
from .network import Network
from .osm_boundaries import osm_areas

WATER, BEACH, PARK, HIGHLIGHT = 1, 2, 4, 8
NAMES = {WATER: "water", BEACH: "beach", PARK: "park", HIGHLIGHT: "highlight"}
WITHIN_M = {WATER: 100.0, BEACH: 150.0, PARK: 50.0, HIGHLIGHT: 75.0}
CELL_M = 150.0


def area_kind(tags: Mapping[str, str]) -> int:
    if tags.get("natural") == "water" or tags.get("waterway") == "riverbank":
        return WATER
    if tags.get("natural") == "beach":
        return BEACH
    if tags.get("leisure") == "park":
        return PARK
    return 0


def scenery_features(doc: Mapping[str, Any]) -> tuple[dict[int, list[Area]], list[list[LatLon]]]:
    """Polygons by flag, and coastline lines, from an Overpass document."""
    polygons: dict[int, list[Area]] = {WATER: [], BEACH: [], PARK: []}
    for a in osm_areas(doc):
        kind = area_kind(a.tags)
        if kind and a.tags.get("natural") != "coastline":
            polygons[kind].append(a.area)
    nodes = {
        el["id"]: (float(el["lat"]), float(el["lon"]))
        for el in doc.get("elements", [])
        if el.get("type") == "node" and "lat" in el
    }
    coast = []
    for el in doc.get("elements", []):
        if el.get("type") == "way" and (el.get("tags") or {}).get("natural") == "coastline":
            if "geometry" in el:
                line = [(float(p["lat"]), float(p["lon"])) for p in el["geometry"] if p]
            else:
                line = [nodes[n] for n in el.get("nodes", []) if n in nodes]
            if len(line) >= 2:
                coast.append(line)
    return polygons, coast


def _segment_distance(p1: XY, p2: XY, q1: XY, q2: XY) -> float:
    """Shortest distance between two segments (0 when they cross)."""
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    d1, d2 = cross(q1, q2, p1), cross(q1, q2, p2)
    d3, d4 = cross(p1, p2, q1), cross(p1, p2, q2)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 and d2 and d3 and d4:
        return 0.0
    return min(
        point_segment_distance(p1, q1, q2),
        point_segment_distance(p2, q1, q2),
        point_segment_distance(q1, p1, p2),
        point_segment_distance(q2, p1, p2),
    )


class _SegmentGrid:
    def __init__(self, cell_m: float = CELL_M):
        self.cell = cell_m
        self.cells: dict[tuple[int, int], list[tuple[int, XY, XY]]] = {}

    def _c(self, v: float) -> int:
        return math.floor(v / self.cell)

    def add(self, kind: int, a: XY, b: XY) -> None:
        item = (kind, a, b)  # one object in every cell, so near() can skip repeats by id
        for cx in range(self._c(min(a[0], b[0])), self._c(max(a[0], b[0])) + 1):
            for cy in range(self._c(min(a[1], b[1])), self._c(max(a[1], b[1])) + 1):
                self.cells.setdefault((cx, cy), []).append(item)

    def near(self, a: XY, b: XY, pad: float):
        seen: set[int] = set()
        for cx in range(self._c(min(a[0], b[0]) - pad), self._c(max(a[0], b[0]) + pad) + 1):
            for cy in range(self._c(min(a[1], b[1]) - pad), self._c(max(a[1], b[1]) + pad) + 1):
                for item in self.cells.get((cx, cy), ()):
                    if id(item) not in seen:
                        seen.add(id(item))
                        yield item


def add_scenery(
    network: Network,
    polygons: Mapping[int, Sequence[Area]],
    coastlines: Iterable[Sequence[LatLon]] = (),
    highlight_points: Iterable[LatLon] = (),
    projection: LocalProjection | None = None,
) -> Network:
    """Copy of ``network`` with ``Edge.scenery`` bit flags set."""
    if not network.edges:
        return network
    proj = projection or LocalProjection.for_points(p for e in network.edges for p in e.coords)
    grid = _SegmentGrid()
    inside: dict[int, _BoundaryIndex] = {}
    for kind, areas in polygons.items():
        if not areas:
            continue
        inside[kind] = _BoundaryIndex(list(areas), proj)
        for area in areas:
            for ring in area.rings:
                xy = [proj.to_xy(p) for p in ring]
                for a, b in zip(xy, xy[1:]):
                    grid.add(kind, a, b)
    for line in coastlines:
        xy = [proj.to_xy(p) for p in line]
        for a, b in zip(xy, xy[1:]):
            grid.add(WATER, a, b)
    for p in highlight_points:
        q = proj.to_xy(p)
        grid.add(HIGHLIGHT, q, q)

    pad = max(WITHIN_M.values())
    edges = []
    for e in network.edges:
        xy = [proj.to_xy(p) for p in e.coords]
        flags = 0
        for kind, index in inside.items():
            if index.areas_at(xy[0]):
                flags |= kind
        for a, b in zip(xy, xy[1:]):
            for kind, q1, q2 in grid.near(a, b, pad):
                if not flags & kind and _segment_distance(a, b, q1, q2) <= WITHIN_M[kind]:
                    flags |= kind
        edges.append(replace(e, scenery=flags))
    return Network(streets=network.streets, edges=edges)


def flag_names(flags: int) -> list[str]:
    return [name for bit, name in NAMES.items() if flags & bit]
