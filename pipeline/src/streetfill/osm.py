"""Read OpenStreetMap data and decide which ways count as streets.

Input is Overpass API JSON (``[out:json]``) containing ``node`` elements with
``lat``/``lon`` and ``way`` elements with ``nodes`` and ``tags``. Relations are
ignored here; boundaries arrive in Phase 2.

The street rule follows product plan section 5.2 (streets layer only; the
paths-and-trails layer is a separate issue).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .geo import LatLon

#: ``highway`` values that always count as streets (when not otherwise excluded).
STREET_HIGHWAYS = frozenset(
    {
        "primary",
        "secondary",
        "tertiary",
        "unclassified",
        "residential",
        "living_street",
        "pedestrian",
    }
)

#: ``foot`` values that make a road open to runners.
FOOT_ALLOWED = frozenset({"yes", "designated", "permissive"})

#: ``access`` values that close a road unless ``foot`` explicitly allows it.
ACCESS_CLOSED = frozenset({"private", "no", "customers", "delivery", "agricultural", "forestry"})


@dataclass(frozen=True)
class Way:
    id: int
    node_ids: tuple[int, ...]
    tags: Mapping[str, str] = field(default_factory=dict)


@dataclass
class OsmData:
    nodes: dict[int, LatLon]
    ways: list[Way]


def parse_overpass(doc: Mapping[str, Any]) -> OsmData:
    """Turn an Overpass JSON document into nodes and ways."""
    nodes: dict[int, LatLon] = {}
    ways: list[Way] = []
    for el in doc.get("elements", []):
        kind = el.get("type")
        if kind == "node" and "lat" in el and "lon" in el:
            nodes[int(el["id"])] = (float(el["lat"]), float(el["lon"]))
        elif kind == "way":
            ways.append(
                Way(
                    id=int(el["id"]),
                    node_ids=tuple(int(n) for n in el.get("nodes", [])),
                    tags=dict(el.get("tags", {})),
                )
            )
    return OsmData(nodes=nodes, ways=ways)


def load_overpass_file(path: str | Path) -> OsmData:
    with open(path, encoding="utf-8") as fh:
        return parse_overpass(json.load(fh))


def _is_yes(value: str | None) -> bool:
    return value is not None and value not in ("no", "false", "0")


def _layer(tags: Mapping[str, str]) -> float:
    try:
        return float(tags.get("layer", "0"))
    except ValueError:
        return 0.0


def is_street(tags: Mapping[str, str]) -> bool:
    """True if a way with these tags counts toward the street percentage (plan 5.2)."""
    highway = tags.get("highway")
    foot = tags.get("foot")

    if highway in STREET_HIGHWAYS:
        pass
    elif highway == "trunk":
        # Trunk roads count only where foot access is explicitly allowed.
        if foot not in FOOT_ALLOWED:
            return False
    else:
        # Motorways, *_link ramps, service, construction, paths and the rest.
        return False

    if foot == "no":
        return False
    if tags.get("access") in ACCESS_CLOSED and foot not in FOOT_ALLOWED:
        return False
    if _is_yes(tags.get("construction")) or _is_yes(tags.get("proposed")):
        return False
    if _is_yes(tags.get("tunnel")) or tags.get("location") == "underground":
        return False
    if _layer(tags) < 0:
        return False
    if tags.get("area") == "yes":
        # Pedestrian squares mapped as areas are polygons, not runnable lines.
        return False
    return True


def street_ways(data: OsmData) -> list[Way]:
    """The ways that count as streets, in input order."""
    return [w for w in data.ways if is_street(w.tags)]
