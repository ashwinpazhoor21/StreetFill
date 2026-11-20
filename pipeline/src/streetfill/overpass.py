"""Download OSM street ways and boundaries for a bounding box from the Overpass API."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from .osm import PATH_HIGHWAYS, STREET_HIGHWAYS

DEFAULT_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "streetfill-pipeline (+https://github.com/ashwinpazhoor21/StreetFill)"

BBox = tuple[float, float, float, float]  # south, west, north, east


def parse_bbox(text: str) -> BBox:
    """Parse ``south,west,north,east`` in decimal degrees."""
    parts = [p.strip() for p in text.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox must be south,west,north,east")
    south, west, north, east = (float(p) for p in parts)
    if not (-90 <= south < north <= 90) or not (-180 <= west < east <= 180):
        raise ValueError("bbox must satisfy south < north and west < east, within lat/lon range")
    return south, west, north, east


def build_query(bbox: BBox, timeout_s: int = 180) -> str:
    """Overpass QL for candidate street, path and steps ways in ``bbox`` plus all their nodes.

    The server-side filter is only by ``highway`` class to keep downloads small;
    the full rule (foot access, tunnels, layers and so on) runs locally in
    :func:`streetfill.osm.is_street`.
    """
    classes = "|".join(sorted(STREET_HIGHWAYS | PATH_HIGHWAYS | {"trunk", "steps"}))
    south, west, north, east = bbox
    return (
        f"[out:json][timeout:{timeout_s}];"
        f'way["highway"~"^({classes})$"]({south},{west},{north},{east});'
        "(._;>;);out body;"
    )


def build_boundary_query(bbox: BBox, timeout_s: int = 180) -> str:
    """Overpass QL for city and neighborhood outlines and place points in ``bbox``, with full geometry.

    ``out geom`` puts each member way's coordinates inline, so relations that
    reach outside the box still come back whole.
    """
    south, west, north, east = bbox
    b = f"({south},{west},{north},{east})"
    return (
        f"[out:json][timeout:{timeout_s}];("
        f'relation["boundary"="administrative"]["admin_level"~"^(8|9|10)$"]{b};'
        f'relation["place"~"^(neighbourhood|quarter|suburb)$"]{b};'
        f'way["place"~"^(neighbourhood|quarter|suburb)$"]{b};'
        f'node["place"~"^(neighbourhood|quarter|suburb)$"]{b};'
        ");out geom;"
    )


def build_feature_query(bbox: BBox, timeout_s: int = 180) -> str:
    """Overpass QL for highlight candidates and scenery features in ``bbox`` (plan 6.6), with full geometry.

    Highlights need a name; scenery (water, coastline, beaches, parks) does not.
    """
    south, west, north, east = bbox
    b = f"({south},{west},{north},{east})"
    filters = [
        '["natural"="beach"]',
        '["leisure"="park"]',
        '["tourism"~"^(attraction|viewpoint|artwork|museum)$"]',
        '["man_made"~"^(lighthouse|pier|bridge)$"]',
        '["amenity"="fountain"]',
        '["historic"]',
        '["bridge:name"]',
    ]
    parts = "".join(f"nwr{f}[\"name\"]{b};" if f != '["bridge:name"]' else f"way{f}{b};" for f in filters)
    scenery = (
        f'wr["natural"="water"]{b};wr["waterway"="riverbank"]{b};way["natural"="coastline"]{b};'
        f'wr["natural"="beach"]{b};wr["leisure"="park"]{b};'
    )
    return f"[out:json][timeout:{timeout_s}];({parts}{scenery});out geom;"


def fetch(bbox: BBox, url: str = DEFAULT_URL, timeout_s: int = 180, query: str | None = None) -> dict[str, Any]:
    """Run the street query (or ``query``) and return the parsed Overpass JSON document."""
    body = urllib.parse.urlencode({"data": query or build_query(bbox, timeout_s)}).encode()
    req = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout_s + 30) as resp:
        return json.load(resp)
