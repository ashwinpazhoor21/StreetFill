"""Shared fixtures for the Swift port (plan 5.4 step 6 and 5.3).

The Swift matcher must agree with this one on 99.5% or more of checkpoints, and
must generate checkpoints identically. A matcher fixture is one self-contained
JSON document, so the Swift tests need no pack file:

* ``origin``: the local projection's origin (lat, lon);
* ``config``: every matching threshold (:class:`streetfill.matching.MatchConfig`);
* ``edges``: id, street, highway, layer and geometry;
* ``checkpoints``: every checkpoint as ``[edge, index, offset_m, lat, lon, bearing_deg]``;
* ``routes``: recorded routes as ``[lat, lon, time, h_acc]`` points (time is
  ISO 8601 or null, h_acc is metres or null) with the ``visited`` checkpoint
  keys ``[edge, index]`` this matcher produces.

The built-in scenarios are synthetic: a small street network in local metres
and routes drawn along it with seeded GPS noise. Every coordinate is rounded to
7 decimals (about 1 cm) *before* matching, so the stored inputs are exactly the
ones that produced the stored outputs.
"""

from __future__ import annotations

import dataclasses
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from .geo import XY, LocalProjection, dist_xy
from .health import RoutePoint
from .matcher import MatchEdge, Matcher
from .matching import DEFAULT_CONFIG, MatchConfig

SCHEMA = 1
ORIGIN = (41.9, -87.65)
COORD_DP = 7
T0 = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)

# (id, street, highway, layer, points in local metres)
NETWORK: list[tuple[int, str, str, str, list[XY]]] = [
    (1, "Main Street", "residential", "street", [(-300, 0), (0, 0)]),
    (2, "Main Street", "residential", "street", [(0, 0), (300, 0)]),
    (3, "Parallel Street", "residential", "street", [(-300, 60), (0, 60)]),
    (4, "Parallel Street", "residential", "street", [(0, 60), (300, 60)]),
    (5, "Cross Avenue", "secondary", "street", [(0, -200), (0, 0)]),
    (6, "Cross Avenue", "secondary", "street", [(0, 0), (0, 60)]),
    (7, "Cross Avenue", "secondary", "street", [(0, 60), (0, 200)]),
    (8, "Lake Drive", "primary", "street", [(-300, -150), (0, -150), (300, -150)]),
    (9, "Lakefront Trail", "footway", "path", [(-300, -165), (0, -165), (300, -165)]),
    (10, "North Lane", "residential", "street", [(-300, 120), (300, 120)]),
    (11, "Twin Lane", "residential", "street", [(-300, 146), (300, 146)]),
    (12, "Short Link", "residential", "street", [(300, 0), (300, 25)]),
    (13, "Bend Road", "tertiary", "street", [(-300, 260), (-100, 260), (0, 300), (100, 260), (300, 260)]),
]


def _round(lat: float, lon: float) -> tuple[float, float]:
    return round(lat, COORD_DP), round(lon, COORD_DP)


def _line(points: Sequence[XY], step: float) -> list[XY]:
    """Points every ``step`` m along a polyline."""
    out: list[XY] = [points[0]]
    for a, b in zip(points, points[1:]):
        n = max(1, round(dist_xy(a, b) / step))
        out += [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(1, n + 1)]
    return out


class _Recorder:
    """Turns a path in local metres into recorded points, 1 s apart at about 3 m/s.

    GPS error drifts rather than jumping each second, so the noise is a seeded
    AR(1) process: each second keeps 90% of the last offset and adds a little.
    ``noise_m`` is the offset's long-run standard deviation.
    """

    KEEP = 0.9

    def __init__(self, proj: LocalProjection, seed: int, noise_m: float = 2.0) -> None:
        self.proj, self.rng = proj, random.Random(seed)
        self.kick = noise_m * (1 - self.KEEP ** 2) ** 0.5
        self.offset = (0.0, 0.0)
        self.t = T0
        self.points: list[RoutePoint] = []

    def run(self, path: Sequence[XY], *, h_acc: float | None = 5.0, timed: bool = True, step: float = 3.0) -> None:
        for x, y in _line(path, step):
            ox, oy = self.offset
            self.offset = (self.KEEP * ox + self.rng.gauss(0, self.kick), self.KEEP * oy + self.rng.gauss(0, self.kick))
            self.add((x + self.offset[0], y + self.offset[1]), h_acc=h_acc, timed=timed)

    def add(self, xy: XY, *, h_acc: float | None = 5.0, timed: bool = True, seconds: float = 1.0) -> None:
        lat, lon = _round(*self.proj.to_latlon(xy))
        self.points.append(RoutePoint(lat, lon, self.t if timed else None, h_acc))
        self.t += timedelta(seconds=seconds)

    def wait(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)


def scenario_routes(proj: LocalProjection) -> list[tuple[str, str, list[RoutePoint]]]:
    """(name, what it checks, points) for each built-in scenario."""
    routes = []

    def scenario(name, description, seed, draw, noise_m=2.0):
        rec = _Recorder(proj, seed, noise_m)
        draw(rec)
        routes.append((name, description, rec.points))

    scenario("main-street", "a plain run along one street", 1,
             lambda r: r.run([(-290, 0), (290, 0)]))
    scenario("out-and-back", "out along a secondary street and back the same way", 2,
             lambda r: r.run([(0, -190), (0, 190), (0, -190)]))

    def inaccurate(r):
        r.run([(-290, 60), (-100, 60)])
        r.run([(-100, 60), (100, 60)], h_acc=40.0)  # dropped: worse than 25 m
        r.run([(100, 60), (290, 60)])

    scenario("inaccurate-points", "points less accurate than 25 m are dropped", 3, inaccurate)

    def jump(r):
        r.run([(-290, 0), (-60, 0)])
        r.add((-60, -150))  # one point on Lake Drive: far too fast in and out
        r.run([(-57, 0), (200, 0)])

    scenario("gps-jump", "a single-point GPS jump credits nothing", 4, jump)

    def gap(r):
        r.run([(-290, 0), (-150, 0)])
        r.wait(90)  # 90 s and 150 m later: split, never bridged
        r.run([(0, 0), (150, 0)])

    scenario("time-gap", "a long pause and move splits the route", 5, gap)
    scenario("lakefront-trail", "a path 15 m beside a primary road: the trail gets the credit", 6,
             lambda r: r.run([(-290, -164), (290, -164)]))
    scenario("lake-drive", "running the primary road beside the trail credits the road", 7,
             lambda r: r.run([(-290, -151), (290, -151)]))
    scenario("between-twins", "halfway between two streets 26 m apart (little noise) credits neither", 8,
             lambda r: r.run([(-290, 133), (290, 133)]), noise_m=0.3)
    scenario("corner", "a run that turns a corner and stops just past it", 9,
             lambda r: r.run([(-250, 0), (0, 0), (0, 30)]))
    scenario("no-timestamps", "points without times are split by distance only", 10,
             lambda r: r.run([(-290, 60), (290, 60)], timed=False))
    scenario("short-edge", "an edge under 30 m has one midpoint checkpoint", 11,
             lambda r: r.run([(200, 0), (300, 0), (300, 25)]))
    scenario("bend", "a road with bends: bearings follow the geometry", 12,
             lambda r: r.run([(-300, 260), (-100, 260), (0, 300), (100, 260), (300, 260)]))
    return routes


def scenario_edges(proj: LocalProjection) -> list[MatchEdge]:
    return [
        MatchEdge(eid, street, highway, [_round(*proj.to_latlon(p)) for p in pts], layer)
        for eid, street, highway, layer, pts in NETWORK
    ]


def matcher_fixture(
    edges: Sequence[MatchEdge],
    routes: Sequence[tuple[str, str, Sequence[RoutePoint]]],
    origin: tuple[float, float] = ORIGIN,
    cfg: MatchConfig = DEFAULT_CONFIG,
) -> dict:
    proj = LocalProjection(*origin)
    matcher = Matcher(edges, proj, cfg)
    checkpoints = []
    for cp in matcher.checkpoints:
        lat, lon = _round(*proj.to_latlon(cp.xy))
        checkpoints.append([cp.edge_id, cp.index, round(cp.offset_m, 3), lat, lon, round(cp.bearing_deg, 3)])
    out_routes = []
    for name, description, points in routes:
        visited = matcher.match(points)
        out_routes.append({
            "name": name,
            "description": description,
            "points": [[p.lat, p.lon, p.time.isoformat() if p.time else None, p.h_acc] for p in points],
            "visited": [list(k) for k in visited],
        })
    return {
        "schema": SCHEMA,
        "kind": "matcher",
        "origin": list(origin),
        "config": dataclasses.asdict(cfg),
        "edges": [
            {"id": e.id, "street": e.street, "highway": e.highway, "layer": e.layer, "coords": [list(c) for c in e.coords]}
            for e in edges
        ],
        "checkpoints": checkpoints,
        "routes": out_routes,
    }


def builtin_matcher_fixture() -> dict:
    proj = LocalProjection(*ORIGIN)
    return matcher_fixture(scenario_edges(proj), scenario_routes(proj))


def dumps(fixture: dict) -> str:
    """Stable text: sorted keys, one line per checkpoint, route point and edge, so diffs stay readable."""
    return json.dumps(fixture, indent=1, sort_keys=True) + "\n"


def write_fixtures(out_dir: str | Path) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "matcher.json"
    path.write_text(dumps(builtin_matcher_fixture()), encoding="utf-8")
    return [path]
