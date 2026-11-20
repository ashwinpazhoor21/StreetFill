"""Write a street network to a SQLite street pack (product plan 5.3).

Schema version 5 (version 1 had no ``layer`` columns, version 2 no
neighborhoods, version 3 no elevation, version 4 no highlights; scenery flags
arrive later in Phase 2):

``meta(key TEXT PRIMARY KEY, value TEXT)``
    ``schema_version``, ``pipeline_version``, ``built_at`` (UTC ISO 8601),
    ``source``, ``attribution``, ``bbox`` (``south,west,north,east``),
    ``origin_lat``/``origin_lon`` (local projection origin), ``grid_cell_m``,
    ``street_count``, ``edge_count``, ``total_length_m``, ``street_length_m``,
    ``path_length_m``, ``neighborhood_count``, ``unassigned_street_length_m``.
    ``elevation_source``, ``elevation_spacing_m`` and ``elevation_edge_count``
    (0 when the pack was built without an elevation model), ``highlight_count``
    and, with highlights, ``highlight_source``. When the pack is
    clipped to a city: ``city_id``, ``city_name``,
    ``city_source`` and ``city_rings``. With neighborhoods: ``neighborhood_source``.

``neighborhoods(id, key, name, street_length_m, path_length_m, rings)``
    One row per neighborhood, in input order. ``key`` is the source's id.
    ``rings`` (like ``city_rings``) is JSON: a list of rings of ``[lon, lat]``
    pairs, read with the even-odd rule (outer rings and holes alike). Lengths
    are of the edges tagged with the neighborhood, so the neighborhoods plus
    ``unassigned_street_length_m`` add up to ``street_length_m``.

``streets(id, key, name, highway, length_m)``
    One row per street. ``key`` is ``name:<normalized name>`` or ``way:<osm id>``.

``edges(id, street_id, way_id, from_node, to_node, highway, length_m, geometry, layer, neighborhood_id, bridge, elevation, gain_m, loss_m)``
    ``geometry`` is a BLOB of little-endian float64 ``(lat, lon)`` pairs, which
    keeps full precision and is trivial to read in Swift. ``neighborhood_id``
    is NULL for edges in no neighborhood. Negative node ids are boundary
    crossings added by the pipeline, not OSM nodes. ``bridge`` is 1 for bridges
    and piers. ``elevation`` is a BLOB of little-endian int16 whole decimetres,
    sampled evenly about ``elevation_spacing_m`` apart from ``from_node`` to
    ``to_node`` with both ends included (``streetfill.elevation``); ``gain_m``
    and ``loss_m`` are summed from it in that direction (swap them for the
    other way). All three are NULL where the model has no data.

``highlights(id, osm_id, name, category, lat, lon, radius_m, size_m2, wikidata, score, description, photo_url, photo_author, photo_licence)``
    Named places from OSM, best ``score`` first (``streetfill.highlights``).
    ``category`` is one of beach, park, landmark, water, historic and picks the
    placeholder illustration. A highlight belongs to a route that passes within
    ``radius_m``. The description and photo columns are NULL until photos are
    resolved; a photo is never shown without its author and licence.

``grid(cell_x, cell_y, edge_id)``
    Spatial index. Cells are ``grid_cell_m`` squares in the local projection
    (``cell = floor(metres / grid_cell_m)``). An edge is listed in every cell
    that overlaps the bounding box of one of its segments, so a lookup never
    misses an edge (it may return a few extra ones).
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Sequence

from . import __version__
from .geo import LatLon, LocalProjection
from .network import Network

if TYPE_CHECKING:
    from .boundaries import Area
    from .highlights import Highlight

SCHEMA_VERSION = 5
GRID_CELL_M = 100.0
ATTRIBUTION = "© OpenStreetMap contributors"

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE neighborhoods (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    street_length_m REAL NOT NULL,
    path_length_m REAL NOT NULL,
    rings TEXT NOT NULL
);
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
    layer TEXT NOT NULL,
    neighborhood_id INTEGER REFERENCES neighborhoods(id),
    bridge INTEGER NOT NULL DEFAULT 0,
    elevation BLOB,
    gain_m REAL,
    loss_m REAL
);
CREATE INDEX edges_street ON edges(street_id);
CREATE INDEX edges_layer ON edges(layer);
CREATE INDEX edges_neighborhood ON edges(neighborhood_id);
CREATE TABLE highlights (
    id INTEGER PRIMARY KEY,
    osm_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    radius_m REAL NOT NULL,
    size_m2 REAL NOT NULL,
    wikidata TEXT,
    score REAL NOT NULL,
    description TEXT,
    photo_url TEXT,
    photo_author TEXT,
    photo_licence TEXT,
    CHECK (photo_url IS NULL OR (photo_author IS NOT NULL AND photo_licence IS NOT NULL))
);
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


def encode_elevation(profile: Iterable[float]) -> bytes:
    """Metres to little-endian int16 whole decimetres (enough for -3276.8 m to 3276.7 m)."""
    dm = [round(v * 10) for v in profile]
    if any(not -32768 <= v <= 32767 for v in dm):
        raise ValueError("elevation outside the int16 decimetre range")
    return struct.pack(f"<{len(dm)}h", *dm)


def decode_elevation(blob: bytes) -> list[float]:
    return [v / 10 for v in struct.unpack(f"<{len(blob) // 2}h", blob)]


def rings_json(rings: Iterable[Iterable[LatLon]]) -> str:
    """Compact JSON for boundary rings: ``[[[lon, lat], ...], ...]``, 7 decimals (about 1 cm)."""
    return json.dumps(
        [[[round(lon, 7), round(lat, 7)] for lat, lon in ring] for ring in rings], separators=(",", ":")
    )


def _elevation_columns(profile):
    if profile is None:
        return None, None, None
    from .elevation import gain_loss

    gain, loss = gain_loss(profile)
    return encode_elevation(profile), gain, loss


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
    city: Area | None = None,
    city_source: str = "",
    neighborhoods: Sequence[Area] = (),
    neighborhood_source: str = "",
    elevation_source: str = "",
    elevation_spacing_m: float | None = None,
    highlights: Sequence[Highlight] = (),
    highlight_source: str = "",
) -> dict[str, str]:
    """Write ``network`` to a new SQLite file at ``out`` and return its meta.

    Pass the ``city`` and ``neighborhoods`` the network was clipped and split
    with (:func:`streetfill.boundaries.assign_areas`); every edge's
    ``neighborhood`` must be one of the neighborhoods' ids or ``None``.
    """
    if not network.edges:
        raise ValueError("network has no edges; nothing to write")
    hood_ids = {a.id: i for i, a in enumerate(neighborhoods, start=1)}
    if len(hood_ids) != len(neighborhoods):
        raise ValueError("duplicate neighborhood ids")
    unknown = {e.neighborhood for e in network.edges if e.neighborhood is not None} - hood_ids.keys()
    if unknown:
        raise ValueError(f"edges tagged with unknown neighborhoods: {sorted(unknown)[:5]}")
    hood_len = {(a.id, layer): 0.0 for a in neighborhoods for layer in ("street", "path")}
    unassigned_m = 0.0
    for e in network.edges:
        if e.neighborhood is not None and e.layer in ("street", "path"):
            hood_len[(e.neighborhood, e.layer)] += e.length_m
        elif e.neighborhood is None and e.layer == "street":
            unassigned_m += e.length_m

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
        "neighborhood_count": str(len(neighborhoods)),
        "unassigned_street_length_m": f"{unassigned_m:.2f}",
        "elevation_edge_count": str(sum(1 for e in network.edges if e.elevation is not None)),
        "highlight_count": str(len(highlights)),
    }
    if highlights:
        meta["highlight_source"] = highlight_source
    if meta["elevation_edge_count"] != "0":
        from .elevation import SPACING_M

        meta["elevation_source"] = elevation_source
        meta["elevation_spacing_m"] = repr(elevation_spacing_m or SPACING_M)
    if city is not None:
        meta.update(city_id=city.id, city_name=city.name, city_source=city_source, city_rings=rings_json(city.rings))
    if neighborhoods:
        meta["neighborhood_source"] = neighborhood_source

    con = sqlite3.connect(tmp)
    try:
        with con:
            con.executescript(SCHEMA)
            con.executemany("INSERT INTO meta VALUES (?, ?)", meta.items())
            con.executemany(
                "INSERT INTO neighborhoods VALUES (?, ?, ?, ?, ?, ?)",
                (
                    (i, a.id, a.name, hood_len[(a.id, "street")], hood_len[(a.id, "path")], rings_json(a.rings))
                    for a, i in ((a, hood_ids[a.id]) for a in neighborhoods)
                ),
            )
            con.executemany(
                "INSERT INTO highlights (id, osm_id, name, category, lat, lon, radius_m, size_m2, wikidata, score) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    (i, h.osm_id, h.name, h.category, h.point[0], h.point[1], h.radius_m, h.size_m2, h.wikidata, h.score)
                    for i, h in enumerate(highlights, start=1)
                ),
            )
            con.executemany(
                "INSERT INTO streets VALUES (?, ?, ?, ?, ?, ?)",
                ((street_ids[s.key], s.key, s.name, s.highway, s.length_m, s.layer) for s in network.streets),
            )
            con.executemany(
                "INSERT INTO edges VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                        hood_ids.get(e.neighborhood) if e.neighborhood is not None else None,
                        int(e.bridge),
                        *_elevation_columns(e.elevation),
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
