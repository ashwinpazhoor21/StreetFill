"""Write a street network to a SQLite street pack (product plan 5.3).

Schema version 2 (version 1 had no ``layer`` columns; neighborhoods, elevation
and highlights arrive later in Phase 2):

``meta(key TEXT PRIMARY KEY, value TEXT)``
    ``schema_version``, ``pipeline_version``, ``built_at`` (UTC ISO 8601),
    ``source``, ``attribution``, ``bbox`` (``south,west,north,east``),
    ``origin_lat``/``origin_lon`` (local projection origin), ``grid_cell_m``,
    ``street_count``, ``edge_count``, ``total_length_m``.

``streets(id, key, name, highway, length_m)``
    One row per street. ``key`` is ``name:<normalized name>`` or ``way:<osm id>``.

``edges(id, street_id, way_id, from_node, to_node, highway, length_m, geometry)``
    ``geometry`` is a BLOB of little-endian float64 ``(lat, lon)`` pairs, which
    keeps full precision and is trivial to read in Swift.

``grid(cell_x, cell_y, edge_id)``
    Spatial index. Cells are ``grid_cell_m`` squares in the local projection
    (``cell = floor(metres / grid_cell_m)``). An edge is listed in every cell
    that overlaps the bounding box of one of its segments, so a lookup never
    misses an edge (it may return a few extra ones).
"""

from __future__ import annotations

import math
import os
import sqlite3
import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from . import __version__
from .geo import LatLon, LocalProjection
from .network import Network

SCHEMA_VERSION = 2
GRID_CELL_M = 100.0
ATTRIBUTION = "© OpenStreetMap contributors"

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE streets (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    name TEXT,
    highway TEXT NOT NULL,
    length_m REAL NOT NULL,
    layer TEXT NOT NULL
);
CREATE TABLE edges (
    id INTEGER PRIMARY KEY,
    street_id INTEGER NOT NULL REFERENCES streets(id),
    way_id INTEGER NOT NULL,
    from_node INTEGER NOT NULL,
    to_node INTEGER NOT NULL,
    highway TEXT NOT NULL,
    length_m REAL NOT NULL,
    geometry BLOB NOT NULL,
    layer TEXT NOT NULL
);
CREATE INDEX edges_street ON edges(street_id);
CREATE INDEX edges_layer ON edges(layer);
CREATE TABLE grid (
    cell_x INTEGER NOT NULL,
    cell_y INTEGER NOT NULL,
    edge_id INTEGER NOT NULL REFERENCES edges(id),
    PRIMARY KEY (cell_x, cell_y, edge_id)
) WITHOUT ROWID;
"""


def encode_geometry(coords: Iterable[LatLon]) -> bytes:
    flat = [v for lat_lon in coords for v in lat_lon]
    return struct.pack(f"<{len(flat)}d", *flat)


def decode_geometry(blob: bytes) -> list[LatLon]:
    flat = struct.unpack(f"<{len(blob) // 8}d", blob)
    return list(zip(flat[0::2], flat[1::2]))


def cell_of(x: float, y: float, cell_m: float = GRID_CELL_M) -> tuple[int, int]:
    return math.floor(x / cell_m), math.floor(y / cell_m)


def edge_cells(
    coords: list[LatLon], projection: LocalProjection, cell_m: float = GRID_CELL_M
) -> set[tuple[int, int]]:
    """Grid cells overlapping the bounding box of any segment of an edge."""
    xy = [projection.to_xy(p) for p in coords]
    cells: set[tuple[int, int]] = set()
    for (x1, y1), (x2, y2) in zip(xy, xy[1:]):
        cx1, cy1 = cell_of(min(x1, x2), min(y1, y2), cell_m)
        cx2, cy2 = cell_of(max(x1, x2), max(y1, y2), cell_m)
        for cx in range(cx1, cx2 + 1):
            for cy in range(cy1, cy2 + 1):
                cells.add((cx, cy))
    return cells


def network_bbox(network: Network) -> tuple[float, float, float, float]:
    lats = [lat for e in network.edges for lat, _ in e.coords]
    lons = [lon for e in network.edges for _, lon in e.coords]
    return min(lats), min(lons), max(lats), max(lons)


def write_pack(
    network: Network,
    out: str | Path,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    source: str = "OpenStreetMap via Overpass API",
    cell_m: float = GRID_CELL_M,
) -> dict[str, str]:
    """Write ``network`` to a new SQLite file at ``out`` and return its meta."""
    if not network.edges:
        raise ValueError("network has no edges; nothing to write")

    bbox = bbox or network_bbox(network)
    south, west, north, east = bbox
    projection = LocalProjection((south + north) / 2, (west + east) / 2)

    out = Path(out)
    tmp = out.with_name(out.name + ".tmp")
    if tmp.exists():
        tmp.unlink()

    street_ids = {s.key: i for i, s in enumerate(network.streets, start=1)}
    meta = {
        "schema_version": str(SCHEMA_VERSION),
        "pipeline_version": __version__,
        "built_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": source,
        "attribution": ATTRIBUTION,
        "bbox": ",".join(f"{v:.7f}" for v in bbox),
        "origin_lat": repr(projection.origin_lat),
        "origin_lon": repr(projection.origin_lon),
        "grid_cell_m": repr(cell_m),
        "street_count": str(len(network.streets)),
        "edge_count": str(len(network.edges)),
        "total_length_m": f"{sum(e.length_m for e in network.edges):.2f}",
        "street_length_m": f"{sum(e.length_m for e in network.edges if e.layer == 'street'):.2f}",
        "path_length_m": f"{sum(e.length_m for e in network.edges if e.layer == 'path'):.2f}",
    }

    con = sqlite3.connect(tmp)
    try:
        with con:
            con.executescript(SCHEMA)
            con.executemany("INSERT INTO meta VALUES (?, ?)", meta.items())
            con.executemany(
                "INSERT INTO streets VALUES (?, ?, ?, ?, ?, ?)",
                ((street_ids[s.key], s.key, s.name, s.highway, s.length_m, s.layer) for s in network.streets),
            )
            con.executemany(
                "INSERT INTO edges VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    (
                        e.id,
                        street_ids[e.street_key],
                        e.way_id,
                        e.from_node,
                        e.to_node,
                        e.highway,
                        e.length_m,
                        encode_geometry(e.coords),
                        e.layer,
                    )
                    for e in network.edges
                ),
            )
            con.executemany(
                "INSERT INTO grid VALUES (?, ?, ?)",
                (
                    (cx, cy, e.id)
                    for e in network.edges
                    for cx, cy in sorted(edge_cells(e.coords, projection, cell_m))
                ),
            )
        con.execute("VACUUM")
    finally:
        con.close()
    os.replace(tmp, out)
    return meta
