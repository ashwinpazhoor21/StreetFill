"""Download OSM street ways for a bounding box from the Overpass API."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from .osm import STREET_HIGHWAYS

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
    """Overpass QL for candidate street ways in ``bbox`` plus all their nodes.

    The server-side filter is only by ``highway`` class to keep downloads small;
    the full rule (foot access, tunnels, layers and so on) runs locally in
    :func:`streetfill.osm.is_street`.
    """
    classes = "|".join(sorted(STREET_HIGHWAYS | {"trunk"}))
    south, west, north, east = bbox
    return (
        f"[out:json][timeout:{timeout_s}];"
        f'way["highway"~"^({classes})$"]({south},{west},{north},{east});'
        "(._;>;);out body;"
    )


def fetch(bbox: BBox, url: str = DEFAULT_URL, timeout_s: int = 180) -> dict[str, Any]:
    """Run the query and return the parsed Overpass JSON document."""
    body = urllib.parse.urlencode({"data": build_query(bbox, timeout_s)}).encode()
    req = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout_s + 30) as resp:
        return json.load(resp)
