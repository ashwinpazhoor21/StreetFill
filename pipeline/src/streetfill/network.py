"""Split street ways into edges at intersections and group edges into streets.

An *edge* is a stretch of one OSM way between two split nodes. A node is a split
node when it is the first or last node of a street way, or when it is used more
than once across all street ways (an intersection, or a way crossing itself).
Ways that are not streets (alleys, footways, motorways) never create splits.

A *street* is what the app reports completion for:

* named edges are grouped by name (case and spacing ignored), so "Oak Street"
  split over several OSM ways is one street;
* unnamed edges are grouped per OSM way (``way:<id>``); they still count toward
  the city's length but are not listed by name.

Output order is deterministic (ways sorted by OSM id), so packs built from the
same input are identical.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .geo import LatLon, haversine_m
from .osm import OsmData, Way, street_ways

#: Road classes from most to least important; a street takes its top class.
CLASS_RANK = (
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "unclassified",
    "residential",
    "living_street",
    "pedestrian",
)


@dataclass
class Edge:
    id: int
    street_key: str
    way_id: int
    from_node: int
    to_node: int
    node_ids: list[int]
    coords: list[LatLon]
    length_m: float
    highway: str


@dataclass
class Street:
    key: str
    name: str | None
    highway: str
    edge_ids: list[int] = field(default_factory=list)
    length_m: float = 0.0


@dataclass
class Network:
    streets: list[Street]
    edges: list[Edge]


def normalize_name(name: str) -> str:
    return " ".join(name.split()).casefold()


def street_key(way: Way) -> str:
    name = way.tags.get("name", "").strip()
    return f"name:{normalize_name(name)}" if name else f"way:{way.id}"


def _class_rank(highway: str) -> int:
    return CLASS_RANK.index(highway) if highway in CLASS_RANK else len(CLASS_RANK)


def _present_runs(way: Way, nodes: dict[int, LatLon]) -> list[list[int]]:
    """Split a way's node list wherever a node is missing from the input.

    Overpass extracts cut at a bounding box can reference nodes they do not
    include; bridging the gap with a straight line would invent geometry.
    """
    runs: list[list[int]] = [[]]
    for nid in way.node_ids:
        if nid in nodes:
            runs[-1].append(nid)
        elif runs[-1]:
            runs.append([])
    return [r for r in runs if len(r) >= 2]


def build_network(data: OsmData) -> Network:
    ways = sorted(street_ways(data), key=lambda w: w.id)
    runs_by_way = [(w, _present_runs(w, data.nodes)) for w in ways]

    use_count: Counter[int] = Counter()
    split: set[int] = set()
    for _, runs in runs_by_way:
        for run in runs:
            use_count.update(run[:-1] if run[0] == run[-1] else run)
            split.add(run[0])
            split.add(run[-1])
    split.update(nid for nid, count in use_count.items() if count > 1)

    edges: list[Edge] = []
    streets: dict[str, Street] = {}
    for way, runs in runs_by_way:
        key = street_key(way)
        highway = way.tags["highway"]
        street = streets.get(key)
        if street is None:
            street = streets[key] = Street(key=key, name=way.tags.get("name", "").strip() or None, highway=highway)
        elif _class_rank(highway) < _class_rank(street.highway):
            street.highway = highway

        for run in runs:
            start = 0
            for i in range(1, len(run)):
                if run[i] in split or i == len(run) - 1:
                    piece = run[start : i + 1]
                    coords = [data.nodes[n] for n in piece]
                    length = sum(haversine_m(a, b) for a, b in zip(coords, coords[1:]))
                    if length > 0:
                        edge = Edge(
                            id=len(edges) + 1,
                            street_key=key,
                            way_id=way.id,
                            from_node=piece[0],
                            to_node=piece[-1],
                            node_ids=piece,
                            coords=coords,
                            length_m=length,
                            highway=highway,
                        )
                        edges.append(edge)
                        street.edge_ids.append(edge.id)
                        street.length_m += length
                    start = i

    return Network(streets=[s for s in streets.values() if s.edge_ids], edges=edges)
