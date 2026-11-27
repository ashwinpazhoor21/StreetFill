"""Shared route fixtures for the Swift port (plan 6.5: start, preferences, seed → edge list).

The Swift route generator must reproduce at least 95% of each route's length on
the same seed. A route fixture is one self-contained JSON document:

* ``origin``: the pack's projection origin (lat, lon);
* ``constants``: every [Tune] value of the cost, loop and scoring code, for reference;
* ``pack_edges``: the pack's edge rows, decoded, in id order: ``[id, street_id,
  from_node, to_node, highway, length_m, layer, geometry [[lat, lon], ...],
  elevation profile in metres or null, gain_m, loss_m, scenery, neighborhood_id]``.
  :meth:`streetfill.routing.Graph.from_rows` builds the graph from exactly these;
* ``highlights``: ``[id, name, category, lat, lon]``;
* ``coverage``: pack edge id → covered fraction (edges not listed are 0);
* ``cases``: start, distance, shape, preferences and seed, with the number of
  candidates generated and the chosen routes. Each route lists its arcs in order
  as ``[pack_id or null for a connector, from_lat, from_lon, to_lat, to_lon,
  length_m]``, so the comparison does not depend on how either side numbers the
  pieces of split edges.

The pack is synthetic: a 2.4 km grid with a primary road, footways (one meeting
a street mid-block, one ending at the kerb, one cutting across blocks), a hill,
a waterfront, a park and three highlights.
"""

from __future__ import annotations

import json
import math
import sqlite3
import tempfile
from pathlib import Path

from . import costs, loops, scoring
from .costs import Preferences
from .geo import XY, LocalProjection
from .highlights import Highlight
from .osm import OsmData, Way
from .network import build_network
from .pack import decode_elevation, decode_geometry, write_pack
from .route_highlights import load_highlights
from .routing import Graph
from .scenery import HIGHLIGHT, PARK, WATER

SCHEMA = 1
ORIGIN = (41.9, -87.65)
HALF = 1200
BLOCK = 150
VERTEX = 75  # streets have a vertex every 75 m, so paths can meet them mid-block

HIGHLIGHTS = [  # (osm id, name, category, xy)
    ("node/1", "Harbor Light", "landmark", (-600.0, -1230.0)),
    ("way/2", "Central Park", "park", (525.0, 525.0)),
    ("node/3", "Old Mill", "historic", (-750.0, 825.0)),
]

# (name, start xy, distance m, shape, preferences, seed)
CASES = [
    ("loop-3km", (10, -5), 3000, "loop", Preferences(), 1),
    ("loop-5km-new", (10, -5), 5000, "loop", Preferences(newness=1.0), 2),
    ("loop-4km-quiet", (160, 140), 4000, "loop", Preferences(quiet=True), 3),
    ("loop-4km-hilly", (300, -300), 4000, "loop", Preferences(terrain=1.0), 4),
    ("loop-4km-flat", (300, -300), 4000, "loop", Preferences(terrain=-1.0), 4),
    ("loop-4km-scenic", (-300, -600), 4000, "loop", Preferences(scenery=WATER | PARK | HIGHLIGHT), 5),
    ("loop-6km-everything", (-150, 150), 6000, "loop",
     Preferences(terrain=0.5, quiet=True, newness=0.6, scenery=PARK), 6),
    ("out-and-back-3km", (10, -5), 3000, "out_and_back", Preferences(), 7),
    ("out-and-back-4km-new", (-450, 450), 4000, "out_and_back", Preferences(newness=0.8), 8),
]


def _hill(x: float, y: float) -> float:
    """A 25 m hill south-east of the middle, on a plain at 180 m."""
    return 180.0 + 25.0 * math.exp(-((x - 450) ** 2 + (y + 450) ** 2) / (2 * 400.0 ** 2))


def _network(proj: LocalProjection):
    nodes, ways, ids = {}, [], {}

    def way(way_id, tags, pts):
        nids = []
        for xy in pts:
            if xy not in ids:
                ids[xy] = len(ids) + 1
                nodes[ids[xy]] = proj.to_latlon(xy)
            nids.append(ids[xy])
        ways.append(Way(way_id, tuple(nids), tags))

    span = range(-HALF, HALF + 1, VERTEX)
    for i, c in enumerate(range(-HALF, HALF + 1, BLOCK)):
        hw = "primary" if c == 0 else "residential"
        way(100 + i, {"highway": hw, "name": "Grand Avenue" if c == 0 else f"Street {i}"}, [(x, c) for x in span])
        way(200 + i, {"highway": "residential", "name": f"Avenue {i}"}, [(c, y) for y in span])
    way(301, {"highway": "footway", "name": "Mid-block Walk"}, [(75, 600), (75, 675), (75, 750)])
    way(302, {"highway": "footway", "name": "Kerb Walk"}, [(600, 308), (600, 420)])  # stops 8 m short
    way(303, {"highway": "footway", "name": "Diagonal Trail"}, [(-1200, -1200), (-750, -750), (-300, -300)])
    way(304, {"highway": "steps"}, [(-300, 900), (-240, 900)])
    net = build_network(OsmData(nodes, ways))

    hl_xy = [xy for *_, xy in HIGHLIGHTS]
    for e in net.edges:
        pts = [proj.to_xy(p) for p in e.coords]
        mid = ((pts[0][0] + pts[-1][0]) / 2, (pts[0][1] + pts[-1][1]) / 2)
        length = sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
        n = max(2, math.ceil(length / 30) + 1)
        samples = []
        for k in range(n):
            target, run = length * k / (n - 1), 0.0
            for a, b in zip(pts, pts[1:]):
                d = math.dist(a, b)
                if run + d >= target or (a, b) == (pts[-2], pts[-1]):
                    t = 0.0 if d == 0 else min(1.0, (target - run) / d)
                    samples.append(round(_hill(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t), 1))
                    break
                run += d
        e.elevation = samples
        flags = 0
        if mid[1] <= -1050:
            flags |= WATER
        if 300 <= mid[0] <= 750 and 300 <= mid[1] <= 750:
            flags |= PARK
        if any(math.dist(mid, h) <= 75 + BLOCK / 2 for h in hl_xy):
            flags |= HIGHLIGHT
        e.scenery = flags
    return net


def _coverage(graph: Graph) -> dict[int, float]:
    """Run streets: the west third fully, the next third partly."""
    out = {}
    for e in graph.edges.values():
        if e.pack_id is None or e.pack_id in out:
            continue
        x = (graph.xy[e.u][0] + graph.xy[e.v][0]) / 2
        if x < -400:
            out[e.pack_id] = 1.0
        elif x < 0:
            out[e.pack_id] = 0.4
    return out


def _constants() -> dict:
    out = {}
    for mod in (costs, loops, scoring):
        for k, v in vars(mod).items():
            if k.isupper() and isinstance(v, (int, float)) and not isinstance(v, bool):
                out[f"{mod.__name__.rsplit('.', 1)[1]}.{k}"] = v
    return out


def _arc(graph: Graph, eid: int, fwd: bool) -> list:
    e = graph.edges[eid]
    a, b = (e.u, e.v) if fwd else (e.v, e.u)
    return [e.pack_id, *graph.coords[a], *graph.coords[b], e.length_m]


def builtin_route_fixture() -> dict:
    proj = LocalProjection(*ORIGIN)
    with tempfile.TemporaryDirectory() as tmp:
        pack = Path(tmp) / "fixture.sqlite"
        highlights = [Highlight(oid, name, cat, proj.to_latlon(xy), 0.0, 60.0, None, 1.0)
                      for oid, name, cat, xy in HIGHLIGHTS]
        write_pack(_network(proj), pack, highlights=highlights, elevation_source="synthetic hill",
                   elevation_spacing_m=30.0)
        con = sqlite3.connect(pack)
        try:
            meta = dict(con.execute("SELECT key, value FROM meta"))
            rows = con.execute(
                "SELECT id, street_id, from_node, to_node, highway, length_m, layer, geometry, elevation, "
                "gain_m, loss_m, scenery, neighborhood_id FROM edges ORDER BY id").fetchall()
            hl_rows = con.execute("SELECT id, name, category, lat, lon FROM highlights ORDER BY id").fetchall()
        finally:
            con.close()
        origin = (float(meta["origin_lat"]), float(meta["origin_lon"]))
        graph = Graph.from_pack(pack)
        hl_points = load_highlights(pack, graph.projection)
    pack_edges = [
        [eid, sid, a, b, hw, length, layer, [list(p) for p in decode_geometry(blob)],
         decode_elevation(ele) if ele else None, gain, loss, scenery, hood]
        for eid, sid, a, b, hw, length, layer, blob, ele, gain, loss, scenery, hood in rows
    ]
    coverage = _coverage(graph)
    cases = []
    for name, start_xy, distance, shape, prefs, seed in CASES:
        start = proj.to_latlon(start_xy)
        cands = loops.generate_candidates(graph, start, distance, prefs, coverage, highlights=hl_points,
                                          seed=seed, shape=shape)
        chosen = scoring.best_routes(graph, start, distance, prefs, coverage, hl_points, seed=seed, shape=shape)
        cases.append({
            "name": name,
            "start": list(start),
            "distance_m": distance,
            "shape": shape,
            "preferences": {"terrain": prefs.terrain, "quiet": prefs.quiet, "newness": prefs.newness,
                            "scenery": prefs.scenery},
            "seed": seed,
            "candidates": len(cands),
            "routes": [{
                "bearing_deg": ch.candidate.bearing_deg,
                "waypoints": [list(graph.coords[w]) for w in ch.candidate.waypoints],
                "pulled": ch.candidate.pulled,
                "length_m": ch.candidate.length_m,
                "distance_error": ch.candidate.distance_error,
                "score": ch.score.total,
                "terms": ch.score.terms,
                "highlights": ch.score.highlights,
                "arcs": [_arc(graph, e, f) for e, f in ch.candidate.arcs],
            } for ch in chosen],
        })
    return {
        "schema": SCHEMA,
        "kind": "routes",
        "origin": list(origin),
        "constants": _constants(),
        "pack_edges": pack_edges,
        "highlights": [list(r) for r in hl_rows],
        "coverage": {str(k): v for k, v in sorted(coverage.items())},
        "cases": cases,
    }


def dumps(fixture: dict) -> str:
    """Sorted keys; long lists one item per line, so diffs stay readable without bloating the file."""
    parts = []
    for key in sorted(fixture):
        value = fixture[key]
        if isinstance(value, list) and value and isinstance(value[0], (list, dict)):
            body = ",\n  ".join(json.dumps(v, sort_keys=True) for v in value)
            parts.append(f' "{key}": [\n  {body}\n ]')
        else:
            parts.append(f" {json.dumps(key)}: {json.dumps(value, sort_keys=True)}")
    return "{\n" + ",\n".join(parts) + "\n}\n"
