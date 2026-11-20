"""Named highlights from OpenStreetMap (plan F5 and 6.6).

A highlight is a named place a runner would notice: a beach, a park, a
landmark, a pier or a historic site. Each one is reduced to a point, a
category for the placeholder illustration, a size, and a matching radius:
large features (beaches and parks) belong to a route within 150 m, others
within 60 m [Tune].

Which tags qualify (plan 6.6), all of them only when named:

* ``natural=beach`` → beach
* ``leisure=park`` of at least 1 ha → park
* ``tourism=attraction|viewpoint|artwork|museum``, ``man_made=lighthouse``,
  ``man_made=bridge`` (or a ``bridge:name``) → landmark
* ``man_made=pier``, ``amenity=fountain`` → water
* ``historic=*`` → historic

Score [Tune] = 2 for a Wikidata id + 1 for a photo hint (``image`` or
``wikimedia_commons`` tag) + up to 1 for size (log scale; 1 at 100 ha).
The top ``limit`` (2,000) are kept. The same name and category within 200 m is
one highlight (for example a museum mapped as both a node and a building).

Photos, descriptions and their licences are added by :mod:`streetfill.photos`;
a highlight without a photo uses its category placeholder.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping, Sequence
from urllib.parse import unquote

from .boundaries import Area
from .geo import LatLon, LocalProjection, haversine_m
from .osm_boundaries import _Container, _inside_point, assemble_rings

if TYPE_CHECKING:
    from .photos import Photo

CATEGORIES = ("beach", "park", "landmark", "water", "historic")
LARGE = {"beach", "park"}
RADIUS_M = {"large": 150.0, "small": 60.0}
MIN_PARK_M2 = 10_000.0
MAX_HIGHLIGHTS = 2000
DEDUPE_M = 200.0


@dataclass(frozen=True)
class Highlight:
    osm_id: str
    name: str
    category: str
    point: LatLon
    size_m2: float  # area for polygons, length x 10 m for lines, 0 for points
    radius_m: float
    wikidata: str | None
    score: float
    commons: str | None = None  # "File:..." from the wikimedia_commons or image tag
    description: str | None = None  # set by photos.resolve_photos (Wikidata)
    photo: "Photo | None" = None  # set by photos.resolve_photos


def category(tags: Mapping[str, str]) -> str | None:
    """Placeholder category for a feature's tags, or None if it is not a highlight."""
    if tags.get("natural") == "beach":
        return "beach"
    if tags.get("leisure") == "park":
        return "park"
    if tags.get("man_made") == "pier" or tags.get("amenity") == "fountain":
        return "water"
    if tags.get("historic") not in (None, "no"):
        return "historic"
    if tags.get("tourism") in ("attraction", "viewpoint", "artwork", "museum"):
        return "landmark"
    if tags.get("man_made") in ("lighthouse", "bridge") or "bridge:name" in tags:
        return "landmark"
    return None


def commons_file(tags: Mapping[str, str]) -> str | None:
    """A Commons file title from ``wikimedia_commons`` or ``image`` tags, if they name one."""
    for value in (tags.get("wikimedia_commons"), tags.get("image")):
        if not value:
            continue
        value = value.strip()
        if value.startswith("File:"):
            return value
        if "commons.wikimedia.org/wiki/File:" in value:
            return "File:" + unquote(value.split("/wiki/File:", 1)[1]).replace("_", " ")
        if "upload.wikimedia.org/wikipedia/commons/" in value:
            name = value.rstrip("/").rsplit("/", 1)[-1]
            if "/thumb/" in value:  # .../thumb/a/ab/Name.jpg/480px-Name.jpg
                name = value.split("/thumb/", 1)[1].split("/")[2]
            return "File:" + unquote(name).replace("_", " ")
    return None  # other image URLs have no known licence


def _name(tags: Mapping[str, str]) -> str | None:
    return (tags.get("name") or tags.get("bridge:name") or "").strip() or None


def _ring_area_m2(ring: Sequence[LatLon], proj: LocalProjection) -> float:
    xy = [proj.to_xy(p) for p in ring]
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(xy, xy[1:]))) / 2


def _line_midpoint(line: Sequence[LatLon]) -> LatLon:
    seg = [haversine_m(a, b) for a, b in zip(line, line[1:])]
    half, run = sum(seg) / 2, 0.0
    for (a, b), d in zip(zip(line, line[1:]), seg):
        if run + d >= half and d > 0:
            t = (half - run) / d
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        run += d
    return line[0]


def _geom(points) -> list[LatLon]:
    return [(float(p["lat"]), float(p["lon"])) for p in points if p]


def _shape(el: Mapping[str, Any], ways: Mapping[int, list[LatLon]]):
    """``(point, size_m2)`` for an Overpass element, or None if it has no usable geometry."""
    kind = el.get("type")
    if kind == "node":
        return ((float(el["lat"]), float(el["lon"])), 0.0) if "lat" in el else None
    if kind == "way":
        line = _geom(el["geometry"]) if "geometry" in el else ways.get(el["id"], [])
        if len(line) < 2:
            return None
        if len(line) >= 4 and line[0] == line[-1]:
            proj = LocalProjection(*line[0])
            return _inside_point(Area("", "", (tuple(line),))), _ring_area_m2(line, proj)
        length = sum(haversine_m(a, b) for a, b in zip(line, line[1:]))
        return _line_midpoint(line), length * 10.0
    if kind == "relation":
        outer, inner = [], []
        for m in el.get("members", []):
            if m.get("type") != "way":
                continue
            geom = _geom(m["geometry"]) if "geometry" in m else ways.get(m.get("ref"), [])
            if geom:
                (inner if m.get("role") == "inner" else outer).append(geom)
        try:
            outer_rings, inner_rings = assemble_rings(outer), assemble_rings(inner)
        except ValueError:
            return None
        if not outer_rings:
            return None
        proj = LocalProjection(*outer_rings[0][0])
        size = sum(_ring_area_m2(r, proj) for r in outer_rings) - sum(_ring_area_m2(r, proj) for r in inner_rings)
        biggest = max(outer_rings, key=lambda r: _ring_area_m2(r, proj))
        return _inside_point(Area("", "", (biggest, *inner_rings))), max(size, 0.0)
    return None


def score(size_m2: float, tags: Mapping[str, str]) -> float:
    size_term = min(1.0, math.log10(1 + size_m2) / 6)  # 1 at 1,000,000 m² (100 ha)
    photo_hint = bool(tags.get("image") or tags.get("wikimedia_commons"))
    return round(2.0 * bool(tags.get("wikidata")) + 1.0 * photo_hint + size_term, 4)


def extract(doc: Mapping[str, Any], *, city: Area | None = None, limit: int = MAX_HIGHLIGHTS) -> list[Highlight]:
    """Highlights in an Overpass document (``out geom``), inside ``city`` if given, best first."""
    elements = doc.get("elements", [])
    nodes = {el["id"]: (float(el["lat"]), float(el["lon"])) for el in elements if el.get("type") == "node" and "lat" in el}
    ways = {
        el["id"]: [nodes[n] for n in el.get("nodes", []) if n in nodes]
        for el in elements
        if el.get("type") == "way" and "geometry" not in el
    }
    inside = _Container(city) if city is not None else None

    found: list[Highlight] = []
    for el in elements:
        tags = el.get("tags") or {}
        cat, name = category(tags), _name(tags)
        if cat is None or name is None:
            continue
        shape = _shape(el, ways)
        if shape is None:
            continue
        point, size = shape
        if cat == "park" and size < MIN_PARK_M2:
            continue
        if inside is not None and not inside(point):
            continue
        found.append(
            Highlight(
                osm_id=f"{el['type']}/{el['id']}",
                name=name,
                category=cat,
                point=(round(point[0], 7), round(point[1], 7)),
                size_m2=round(size, 1),
                radius_m=RADIUS_M["large" if cat in LARGE else "small"],
                wikidata=tags.get("wikidata"),
                score=score(size, tags),
                commons=commons_file(tags),
            )
        )

    found.sort(key=lambda h: (-h.score, h.osm_id))
    kept: list[Highlight] = []
    seen: dict[tuple[str, str], list[LatLon]] = {}
    for h in found:  # best first, so a duplicate keeps the better-scored copy
        points = seen.setdefault((" ".join(h.name.split()).casefold(), h.category), [])
        if any(haversine_m(p, h.point) <= DEDUPE_M for p in points):
            continue
        points.append(h.point)
        kept.append(h)
        if len(kept) >= limit:
            break
    return kept
