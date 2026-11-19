"""City and neighborhood boundaries from OpenStreetMap (plan 5.6).

Input is an Overpass JSON document from :func:`streetfill.overpass.build_boundary_query`
(``out geom``, so relation members carry their geometry). Documents that list
member ways and nodes as separate elements work too.

* **City:** the ``boundary=administrative`` relation at ``admin_level`` (8 for
  most US cities [Unverified per city]), picked by name or, without a name, as
  the one containing a given point.
* **Neighborhoods:** polygons inside the city, taken from the first of these
  kinds that has at least two members: ``place=neighbourhood``,
  ``place=quarter``, ``place=suburb``, ``admin_level=10``, ``admin_level=9``.
  Mixing kinds would double-count, because suburbs contain neighbourhoods.
  Without polygons, :func:`approximate_regions` makes Voronoi cells around
  named place points instead.

Member ways are joined end to end into closed rings, separately for ``outer``
and ``inner`` roles; a relation whose rings do not close is skipped.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .boundaries import Area, _BoundaryIndex
from .geo import LatLon, LocalProjection

NEIGHBORHOOD_KINDS: tuple[tuple[str, str], ...] = (
    ("place", "neighbourhood"),
    ("place", "quarter"),
    ("place", "suburb"),
    ("admin_level", "10"),
    ("admin_level", "9"),
)


@dataclass(frozen=True)
class OsmArea:
    area: Area
    tags: Mapping[str, str]


def assemble_rings(lines: Sequence[Sequence[LatLon]]) -> list[tuple[LatLon, ...]]:
    """Join polylines that share end points into closed rings.

    Raises ``ValueError`` when some lines cannot be closed into a ring.
    """
    pending = [list(line) for line in lines if len(line) >= 2]
    rings = []
    while pending:
        ring = pending.pop(0)
        while ring[0] != ring[-1]:
            for i, line in enumerate(pending):
                if line[0] == line[-1]:
                    continue  # a closed way is a ring of its own
                if line[0] == ring[-1]:
                    ring.extend(line[1:])
                elif line[-1] == ring[-1]:
                    ring.extend(reversed(line[:-1]))
                else:
                    continue
                pending.pop(i)
                break
            else:
                raise ValueError(f"ring does not close (open end at {ring[-1]})")
        if len(ring) >= 4:  # three distinct points plus the closing one
            rings.append(tuple(ring))
    return rings


def _geometry(points: Sequence[Mapping[str, Any] | None]) -> list[LatLon]:
    return [(float(p["lat"]), float(p["lon"])) for p in points if p]


def osm_areas(doc: Mapping[str, Any]) -> list[OsmArea]:
    """Every closed way and multipolygon or boundary relation with a usable outline."""
    elements = doc.get("elements", [])
    nodes = {el["id"]: (float(el["lat"]), float(el["lon"])) for el in elements if el.get("type") == "node" and "lat" in el}
    ways: dict[int, list[LatLon]] = {}
    way_tags: dict[int, Mapping[str, str]] = {}
    for el in elements:
        if el.get("type") != "way":
            continue
        if "geometry" in el:
            ways[el["id"]] = _geometry(el["geometry"])
        else:
            ways[el["id"]] = [nodes[n] for n in el.get("nodes", []) if n in nodes]
        way_tags[el["id"]] = el.get("tags", {})

    out: list[OsmArea] = []
    for wid in sorted(ways):
        geom, tags = ways[wid], way_tags[wid]
        if tags and len(geom) >= 4 and geom[0] == geom[-1]:
            out.append(OsmArea(Area(f"way/{wid}", tags.get("name") or f"way/{wid}", (tuple(geom),)), tags))

    for el in sorted((el for el in elements if el.get("type") == "relation"), key=lambda el: el["id"]):
        tags = el.get("tags", {})
        if tags.get("type") not in ("boundary", "multipolygon"):
            continue
        by_role: dict[str, list[list[LatLon]]] = {"outer": [], "inner": []}
        for m in el.get("members", []):
            if m.get("type") != "way":
                continue
            geom = _geometry(m["geometry"]) if "geometry" in m else ways.get(m.get("ref"), [])
            role = "inner" if m.get("role") == "inner" else "outer"
            if geom:
                by_role[role].append(geom)
        try:
            outer = assemble_rings(by_role["outer"])
            inner = assemble_rings(by_role["inner"])
        except ValueError:
            continue  # incomplete relation (cut by the download, or broken in OSM)
        if outer:
            rid = f"relation/{el['id']}"
            out.append(OsmArea(Area(rid, tags.get("name") or rid, tuple(outer + inner)), tags))
    return out


class _Container:
    """Point-in-area test with the boundary index built once."""

    def __init__(self, area: Area):
        self.proj = LocalProjection(*area.rings[0][0])
        self.index = _BoundaryIndex([area], self.proj)

    def __call__(self, point: LatLon) -> bool:
        return bool(self.index.areas_at(self.proj.to_xy(point)))


def _inside_point(area: Area) -> LatLon:
    """A point well inside the area's first ring: the vertex mean, or a ring vertex nudged inward."""
    ring = area.rings[0]
    pts = ring[:-1] if ring[0] == ring[-1] else ring
    mean = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
    contains = _Container(area)
    if contains(mean):
        return mean
    for a, b in zip(pts, pts[1:]):  # concave shape: try points just inside the edges
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        for sign in (1, -1):
            p = (mid[0] + sign * (b[1] - a[1]) * 1e-3, mid[1] - sign * (b[0] - a[0]) * 1e-3)
            if contains(p):
                return p
    return mean


def find_city(
    areas: Sequence[OsmArea], *, admin_level: str = "8", name: str | None = None, point: LatLon | None = None
) -> Area | None:
    """The city boundary: matched by ``name`` if given, else the one containing ``point``."""
    candidates = [
        a for a in areas
        if a.tags.get("boundary") == "administrative" and a.tags.get("admin_level") == admin_level
        and a.area.id.startswith("relation/")
    ]
    if name is not None:
        wanted = name.casefold()
        candidates = [a for a in candidates if a.tags.get("name", "").casefold() == wanted]
    elif point is not None:
        candidates = [a for a in candidates if _Container(a.area)(point)]
    return candidates[0].area if candidates else None


def find_neighborhoods(areas: Sequence[OsmArea], city: Area | None) -> tuple[list[Area], str | None]:
    """Neighborhood polygons inside ``city`` and the kind used (``"place=suburb"``), or ``([], None)``."""
    in_city = _Container(city) if city is not None else None
    for key, value in NEIGHBORHOOD_KINDS:
        found = [
            a.area for a in areas
            if a.tags.get(key) == value
            and (key != "admin_level" or a.tags.get("boundary") == "administrative")
            and (in_city is None or in_city(_inside_point(a.area)))
        ]
        if len(found) >= 2:
            return found, f"{key}={value}"
    return [], None


# --- approximate regions around place points (the last step before "none") ---------

PLACE_POINT_KINDS = ("neighbourhood", "quarter", "suburb")


@dataclass(frozen=True)
class PlacePoint:
    id: str
    name: str
    kind: str
    point: LatLon


def place_points(doc: Mapping[str, Any]) -> list[PlacePoint]:
    """Named ``place=neighbourhood|quarter|suburb`` nodes, sorted by id."""
    out = []
    for el in doc.get("elements", []):
        tags = el.get("tags", {})
        if el.get("type") == "node" and tags.get("place") in PLACE_POINT_KINDS and tags.get("name") and "lat" in el:
            out.append(PlacePoint(f"node/{el['id']}", tags["name"], tags["place"], (float(el["lat"]), float(el["lon"]))))
    return sorted(out, key=lambda p: int(p.id.split("/")[1]))


def _clip_half_plane(poly: list[tuple[float, float]], a: tuple[float, float], b: tuple[float, float]):
    """Keep the part of convex ``poly`` closer to site ``a`` than to site ``b`` (Sutherland–Hodgman)."""
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    nx, ny = b[0] - a[0], b[1] - a[1]

    def side(p):  # < 0 on a's side of the bisector
        return (p[0] - mx) * nx + (p[1] - my) * ny

    out = []
    for i, p in enumerate(poly):
        q = poly[(i + 1) % len(poly)]
        sp, sq = side(p), side(q)
        if sp <= 0:
            out.append(p)
        if (sp < 0 < sq) or (sq < 0 < sp):
            t = sp / (sp - sq)
            out.append((p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t))
    return out


def approximate_regions(
    points: Sequence[PlacePoint], city: Area | None, *, pad_m: float = 500.0
) -> tuple[list[Area], str | None]:
    """Voronoi cells around place points inside ``city``, of the first kind with at least two.

    Cells are cut to the city's bounding box (plus ``pad_m``); clipping the
    network to the city itself is :func:`streetfill.boundaries.assign_areas`'s job.
    The regions are approximate, which the pack's ``neighborhood_source`` says.
    """
    in_city = _Container(city) if city is not None else None
    for kind in PLACE_POINT_KINDS:
        sites, seen = [], set()
        for p in points:
            if p.kind == kind and p.point not in seen and (in_city is None or in_city(p.point)):
                seen.add(p.point)  # two places at one point would share a cell; keep the first
                sites.append(p)
        if len(sites) < 2:
            continue
        frame = [pt for ring in city.rings for pt in ring] if city is not None else [p.point for p in sites]
        proj = LocalProjection.for_points(frame)
        xy = [proj.to_xy(p) for p in frame]
        x0, x1 = min(x for x, _ in xy) - pad_m, max(x for x, _ in xy) + pad_m
        y0, y1 = min(y for _, y in xy) - pad_m, max(y for _, y in xy) + pad_m
        site_xy = [proj.to_xy(s.point) for s in sites]
        regions = []
        for i, s in enumerate(sites):
            cell = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
            for j, other in enumerate(site_xy):
                if j != i and cell:
                    cell = _clip_half_plane(cell, site_xy[i], other)
            if len(cell) >= 3:
                ring = tuple(proj.to_latlon(p) for p in cell + [cell[0]])
                regions.append(Area(s.id, s.name, (ring,)))
        return regions, f"place={kind} points"
    return [], None
