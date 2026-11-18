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


#: Path-layer ``highway`` values (plan 5.2). Bridleways also need explicit foot access.
PATH_HIGHWAYS = frozenset({"footway", "path", "cycleway", "track", "bridleway"})

#: ``footway`` values mapped beside a street: a run there is credited to the street
#: through the distance tolerance, so these stay out of both layers.
SIDEWALK_VALUES = frozenset({"sidewalk", "crossing", "traffic_island", "access_aisle"})

#: The layers a way can belong to. ``steps`` is routable only and never counts.
STREET, PATH, STEPS = "street", "path", "steps"
ALL_LAYERS = (STREET, PATH, STEPS)


def _closed(tags: Mapping[str, str]) -> bool:
    """Exclusions shared by every layer: no foot access, private, unbuilt, underground, areas."""
    foot = tags.get("foot")
    if foot == "no":
        return True
    if tags.get("access") in ACCESS_CLOSED and foot not in FOOT_ALLOWED:
        return True
    if _is_yes(tags.get("construction")) or _is_yes(tags.get("proposed")):
        return True
    if _is_yes(tags.get("tunnel")) or tags.get("location") == "underground" or _is_yes(tags.get("indoor")):
        return True
    if _layer(tags) < 0:
        return True
    # Squares and plazas mapped as areas are polygons, not runnable lines.
    return tags.get("area") == "yes"


def way_layer(tags: Mapping[str, str]) -> str | None:
    """Which pack layer a way belongs to (plan 5.2), or None if it is left out.

    * ``street``: counts toward the street percentage.
    * ``path``: footways (not sidewalks or crossings), paths, cycleways, tracks,
      and bridleways with explicit foot access. Counts toward "Paths & trails".
      Cycleways without a ``foot`` tag are treated as open to runners, the usual
      US default; ``foot=no`` still excludes them.
    * ``steps``: routable only, never counted.
    """
    highway = tags.get("highway")
    foot = tags.get("foot")
    if _closed(tags):
        return None
    if highway in STREET_HIGHWAYS:
        return STREET
    if highway == "trunk":
        # Trunk roads count only where foot access is explicitly allowed.
        return STREET if foot in FOOT_ALLOWED else None
    if highway in PATH_HIGHWAYS:
        if tags.get("footway") in SIDEWALK_VALUES:
            return None
        if highway == "bridleway" and foot not in FOOT_ALLOWED:
            return None
        return PATH
    if highway == "steps":
        return STEPS
    # Motorways, *_link ramps, service roads, construction and the rest.
    return None


def is_street(tags: Mapping[str, str]) -> bool:
    """True if a way with these tags counts toward the street percentage (plan 5.2)."""
    return way_layer(tags) == STREET


def street_ways(data: OsmData) -> list[Way]:
    """The ways that count as streets, in input order."""
    return [w for w in data.ways if is_street(w.tags)]


def layered_ways(data: OsmData, layers: tuple[str, ...] = ALL_LAYERS) -> list[tuple[Way, str]]:
    """``(way, layer)`` for every way in one of ``layers``, in input order."""
    out = []
    for w in data.ways:
        layer = way_layer(w.tags)
        if layer in layers:
            out.append((w, layer))
    return out
