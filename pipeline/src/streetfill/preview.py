"""Route preview for rating (issue #16): GPX files and a self-contained HTML page.

The HTML page loads nothing from the network (no tiles, fonts or scripts), so it
can be opened from disk and shared. It shows each chosen route as its own card
with:

* a map of the route over the nearby streets, with the new streets marked (the
  6.5 definition: coverage under 50%) and the highlights passed;
* the elevation profile, with a hover readout of mile and elevation;
* the 6.5 annotation (distance, elevation gain, new share, highlights in
  route order with the mile point) and the 6.4 score terms.

The GPX files have one track each, which running watches and route apps
import as a course. Elevation is written where the pack has it (at graph
nodes). Distances are shown in miles and feet, the plan's units.
"""

from __future__ import annotations

import html
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .geo import XY, LatLon
from .loops import HIGHLIGHT_M, NEW_BELOW
from .route_highlights import HighlightGrid, HighlightPoint
from .routing import Graph
from .scoring import Choice

M_PER_MI = 1609.344
FT_PER_M = 3.28084
MAP_PAD_M = 300.0
MAP_W = 640.0
PROFILE_W, PROFILE_H = 640.0, 150.0

Arcs = Sequence[tuple[int, bool]]

# The first three categorical slots of the reference palette; they pass the
# colour checks for all pairs in both modes (scripts/validate_palette.js).
ROUTE_COLOURS_LIGHT = ("#2a78d6", "#eb6834", "#1baf7a")
ROUTE_COLOURS_DARK = ("#3987e5", "#d95926", "#199e70")


@dataclass
class Stop:
    highlight: HighlightPoint
    at_m: float  # distance along the route


def _arc_xy(graph: Graph, eid: int, forward: bool) -> list[XY]:
    e = graph.edges[eid]
    pts = [graph.projection.to_xy(p) for p in e.coords] if len(e.coords) >= 2 else [graph.xy[e.u], graph.xy[e.v]]
    return pts if forward else pts[::-1]


def _arc_coords(graph: Graph, eid: int, forward: bool) -> list[LatLon]:
    e = graph.edges[eid]
    pts = list(e.coords) if len(e.coords) >= 2 else [graph.coords[e.u], graph.coords[e.v]]
    return pts if forward else pts[::-1]


def _end(graph: Graph, eid: int, forward: bool) -> int:
    e = graph.edges[eid]
    return e.v if forward else e.u


def route_coords(graph: Graph, arcs: Arcs) -> list[tuple[LatLon, float | None]]:
    """The route's points in order, each with its elevation (m) where it is a node with elevation."""
    if not arcs:
        return []
    e0, f0 = arcs[0]
    first = graph.edges[e0].u if f0 else graph.edges[e0].v
    out: list[tuple[LatLon, float | None]] = [(_arc_coords(graph, e0, f0)[0], graph.elevation[first])]
    for eid, fwd in arcs:
        pts = _arc_coords(graph, eid, fwd)
        out.extend((p, None) for p in pts[1:-1])
        out.append((pts[-1], graph.elevation[_end(graph, eid, fwd)]))
    return out


def elevation_profile(graph: Graph, arcs: Arcs) -> list[tuple[float, float]]:
    """(distance along the route in m, elevation in m) at each node that has elevation."""
    if not arcs:
        return []
    e0, f0 = arcs[0]
    first = graph.edges[e0].u if f0 else graph.edges[e0].v
    out = [] if graph.elevation[first] is None else [(0.0, graph.elevation[first])]
    at = 0.0
    for eid, fwd in arcs:
        at += graph.edges[eid].length_m
        ele = graph.elevation[_end(graph, eid, fwd)]
        if ele is not None:
            out.append((at, ele))
    return out


def highlight_stops(graph: Graph, arcs: Arcs, highlights: Sequence[HighlightPoint] | HighlightGrid) -> list[Stop]:
    """Highlights within 75 m of the route, in route order, each at the first place the route passes it."""
    grid = highlights if isinstance(highlights, HighlightGrid) else HighlightGrid(highlights)
    found: dict[int, Stop] = {}
    at = 0.0
    for eid, fwd in arcs:
        pts = _arc_xy(graph, eid, fwd)
        seg_lengths = [math.dist(a, b) for a, b in zip(pts, pts[1:])]
        # scale the projected segments to the edge's measured length
        scale = graph.edges[eid].length_m / sum(seg_lengths) if sum(seg_lengths) > 0 else 0.0
        run = at
        for (a, b), seg in zip(zip(pts, pts[1:]), seg_lengths):
            for h in grid.near_segment(a, b, HIGHLIGHT_M):
                if h.id not in found:
                    found[h.id] = Stop(h, run + _foot(h.xy, a, b, seg) * scale)
            run += seg * scale
        at += graph.edges[eid].length_m
    return sorted(found.values(), key=lambda s: (s.at_m, s.highlight.id))


def _foot(p: XY, a: XY, b: XY, seg: float) -> float:
    """How far along a → b the point's nearest point lies, in m."""
    if seg <= 0:
        return 0.0
    t = ((p[0] - a[0]) * (b[0] - a[0]) + (p[1] - a[1]) * (b[1] - a[1])) / (seg * seg)
    return max(0.0, min(1.0, t)) * seg


def to_gpx(graph: Graph, arcs: Arcs, name: str) -> str:
    """A GPX 1.1 document with the route as one track."""
    pts = []
    for (lat, lon), ele in route_coords(graph, arcs):
        inner = f"<ele>{ele:.1f}</ele>" if ele is not None else ""
        pts.append(f'      <trkpt lat="{lat:.7f}" lon="{lon:.7f}">{inner}</trkpt>')
    title = html.escape(name, quote=False)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="StreetFill pipeline" xmlns="http://www.topografix.com/GPX/1/1">\n'
        f"  <metadata><name>{title}</name></metadata>\n"
        f"  <trk>\n    <name>{title}</name>\n    <trkseg>\n" + "\n".join(pts) + "\n    </trkseg>\n  </trk>\n</gpx>\n"
    )


# --- the HTML page ---------------------------------------------------------------------


def _is_new(edge, coverage: Mapping[int, float]) -> bool:
    return edge.layer in ("street", "path") and edge.pack_id is not None and coverage.get(edge.pack_id, 0.0) < NEW_BELOW


class _Frame:
    """Maps graph xy (m) onto the shared map box, y down."""

    def __init__(self, points: Sequence[XY]) -> None:
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        self.x0, self.x1 = min(xs) - MAP_PAD_M, max(xs) + MAP_PAD_M
        self.y0, self.y1 = min(ys) - MAP_PAD_M, max(ys) + MAP_PAD_M
        self.k = MAP_W / max(self.x1 - self.x0, 1.0)
        self.h = (self.y1 - self.y0) * self.k

    def contains(self, p: XY) -> bool:
        return self.x0 <= p[0] <= self.x1 and self.y0 <= p[1] <= self.y1

    def xy(self, p: XY) -> XY:
        return (p[0] - self.x0) * self.k, (self.y1 - p[1]) * self.k

    def pt(self, p: XY) -> str:
        x, y = self.xy(p)
        return f"{x:.1f},{y:.1f}"

    def path(self, pts: Sequence[XY]) -> str:
        return "M" + " L".join(self.pt(p) for p in pts)


def _background(graph: Graph, frame: _Frame) -> str:
    parts = []
    for e in graph.edges.values():
        if e.layer == "connector":
            continue
        pts = _arc_xy(graph, e.id, True)
        if any(frame.contains(p) for p in pts):
            cls = ' class="trail"' if e.layer != "street" else ""
            parts.append(f'<path{cls} d="{frame.path(pts)}"/>')
    return "\n".join(parts)


def _view_box(graph: Graph, arcs: Arcs, frame: _Frame) -> tuple[float, float, float, float]:
    """The card's window onto the shared map: the route plus a margin, at least half as tall as wide."""
    pts = [frame.xy(p) for e, f in arcs for p in _arc_xy(graph, e, f)]
    pad = MAP_PAD_M * frame.k
    x0, x1 = min(p[0] for p in pts) - pad, max(p[0] for p in pts) + pad
    y0, y1 = min(p[1] for p in pts) - pad, max(p[1] for p in pts) + pad
    w, h = x1 - x0, y1 - y0
    if h < w / 2:
        y0, h = y0 - (w / 2 - h) / 2, w / 2
    elif h > w * 1.25:
        x0, w = x0 - (h / 1.25 - w) / 2, h / 1.25
    return x0, y0, w, h


def _route_svg(graph: Graph, arcs: Arcs, frame: _Frame, coverage, stops: Sequence[Stop], start: int,
               unit: float) -> str:
    """``unit`` is the size of one screen pixel in map units, so markers keep their size at any zoom."""
    new_parts, line_parts = [], []
    for eid, fwd in arcs:
        d = frame.path(_arc_xy(graph, eid, fwd))
        line_parts.append(d)
        if _is_new(graph.edges[eid], coverage):
            new_parts.append(d)
    out = []
    if new_parts:
        out.append(f'<path class="new" d="{" ".join(new_parts)}"/>')
    out.append(f'<path class="route" d="{" ".join(line_parts)}"/>')
    sx, sy = frame.pt(graph.xy[start]).split(",")
    out.append(f'<circle class="start" cx="{sx}" cy="{sy}" r="{6 * unit:.2f}" stroke-width="{2 * unit:.2f}">'
               '<title>Start</title></circle>')
    for i, s in enumerate(stops, 1):
        x, y = frame.pt(s.highlight.xy).split(",")
        label = html.escape(f"{s.highlight.name} · mile {s.at_m / M_PER_MI:.1f}")
        out.append(f'<g class="hl"><circle cx="{x}" cy="{y}" r="{6 * unit:.2f}" stroke-width="{2 * unit:.2f}">'
                   f'<title>{label}</title></circle><text x="{float(x) + 9 * unit:.1f}" y="{float(y) + 4 * unit:.1f}" '
                   f'font-size="{13 * unit:.2f}">{i}</text></g>')
    return "\n".join(out)


def _profile_svg(profile: Sequence[tuple[float, float]], length_m: float) -> str:
    if len(profile) < 2 or length_m <= 0:
        return '<p class="sec">No elevation data for this route.</p>'
    feet = [e * FT_PER_M for _, e in profile]
    lo, hi = min(feet), max(feet)
    if hi - lo < 20:  # keep a flat route looking flat
        mid = (hi + lo) / 2
        lo, hi = mid - 10, mid + 10
    pad_l, pad_b, pad_t = 54.0, 22.0, 8.0
    w, h = PROFILE_W - pad_l - 8, PROFILE_H - pad_b - pad_t

    def x(d):
        return pad_l + d / length_m * w

    def y(f):
        return pad_t + (hi - f) / (hi - lo) * h

    line = "M" + " L".join(f"{x(d):.1f},{y(f):.1f}" for (d, _), f in zip(profile, feet))
    area = line + f" L{x(profile[-1][0]):.1f},{pad_t + h:.1f} L{x(profile[0][0]):.1f},{pad_t + h:.1f} Z"
    miles = length_m / M_PER_MI
    step = 0.5 if miles <= 4 else 1.0 if miles <= 10 else 2.0
    ticks = []
    m = 0.0
    while m <= miles + 1e-9:
        tx = x(m * M_PER_MI)
        ticks.append(f'<text class="tick" x="{tx:.1f}" y="{PROFILE_H - 6:.1f}" text-anchor="middle">{m:g}</text>')
        m += step
    grid = "".join(
        f'<line class="grid" x1="{pad_l}" x2="{pad_l + w:.1f}" y1="{y(f):.1f}" y2="{y(f):.1f}"/>'
        f'<text class="tick" x="{pad_l - 6}" y="{y(f) + 4:.1f}" text-anchor="end">{f:.0f} ft</text>'
        for f in (lo, hi)
    )
    data = ",".join(f"[{d / M_PER_MI:.3f},{f:.0f}]" for (d, _), f in zip(profile, feet))
    return (
        f'<svg class="profile" viewBox="0 0 {PROFILE_W:.0f} {PROFILE_H:.0f}" data-points="[{data}]" '
        f'data-x0="{pad_l}" data-w="{w:.1f}" data-miles="{miles:.3f}" role="img" '
        f'aria-label="Elevation profile, {lo:.0f} to {hi:.0f} ft">'
        f'{grid}<path class="area" d="{area}"/><path class="line" d="{line}"/>{"".join(ticks)}'
        f'<line class="cross" y1="{pad_t}" y2="{pad_t + h:.1f}" x1="-10" x2="-10"/></svg>'
        '<div class="readout sec" aria-live="polite">Hover the profile for mile and elevation (ft).</div>'
    )


def _pct(x: float) -> str:
    """A signed percentage that never shows "-0.0%"."""
    x = round(x * 100, 1)
    return f"{x + 0.0:+.1f}%" if x else "0.0%"


def _card(graph, choice: Choice, index: int, frame: _Frame, coverage, grid) -> str:
    c, s = choice.candidate, choice.score
    stops = highlight_stops(graph, c.arcs, grid)
    profile = elevation_profile(graph, c.arcs)
    gain = f"{s.gain_m * FT_PER_M:,.0f} ft" if s.gain_m is not None else "n/a"
    vx, vy, vw, vh = _view_box(graph, c.arcs, frame)
    shape = "out-and-back" if c.shape == "out_and_back" else "loop"
    stop_rows = "".join(
        f"<li>{html.escape(st.highlight.name)} <span class='sec'>({html.escape(st.highlight.category)}) · "
        f"mile {st.at_m / M_PER_MI:.1f}</span></li>"
        for st in stops
    ) or "<li class='sec'>None within 75 m</li>"
    terms = "".join(f"<tr><td>{html.escape(k)}</td><td>{v:+.2f}</td></tr>" for k, v in s.terms.items())
    return f"""<section class="card r{index}">
<h2><span class="swatch"></span>Option {index} · {s.length_m / M_PER_MI:.2f} mi {shape}</h2>
<div class="stats">
<div><b>{s.length_m / M_PER_MI:.2f} mi</b><span class="sec">{_pct(c.distance_error)} vs target</span></div>
<div><b>{gain}</b><span class="sec">elevation gain</span></div>
<div><b>{s.new_share:.0%}</b><span class="sec">on new streets</span></div>
<div><b>{len(stops)}</b><span class="sec">highlights</span></div>
</div>
<div class="map"><svg viewBox="{vx:.1f} {vy:.1f} {vw:.1f} {vh:.1f}" role="img" aria-label="Map of option {index}">
<use href="#streets"/>
{_route_svg(graph, c.arcs, frame, coverage, stops, c.waypoints[0], vw / MAP_W)}
</svg></div>
<h3>Elevation</h3>
{_profile_svg(profile, s.length_m)}
<h3>Highlights</h3>
<ol>{stop_rows}</ol>
<details><summary>Score {s.total:.2f} (lower is better)</summary>
<table><tbody>{terms}
<tr><td>turns per mile</td><td>{s.turns_per_mile:.1f}</td></tr>
<tr><td>repeated share</td><td>{s.repeated_share:.0%}</td></tr></tbody></table></details>
</section>"""


def build_preview(
    graph: Graph,
    choices: Sequence[Choice],
    distance_m: float,
    coverage: Mapping[int, float] = {},
    highlights: Sequence[HighlightPoint] = (),
    *,
    title: str = "Route options",
) -> str:
    """The HTML page for up to three chosen routes."""
    grid = HighlightGrid(highlights)
    pts = [p for ch in choices for e, f in ch.candidate.arcs for p in _arc_xy(graph, e, f)]
    if not pts:
        body = '<p class="sec">No routes were found for this start and distance.</p>'
        streets = ""
    else:
        frame = _Frame(pts)
        streets = _background(graph, frame)
        body = "\n".join(_card(graph, ch, i, frame, coverage, grid) for i, ch in enumerate(choices, 1))
    css_light = "".join(f"--r{i}:{c};" for i, c in enumerate(ROUTE_COLOURS_LIGHT, 1))
    css_dark = "".join(f"--r{i}:{c};" for i, c in enumerate(ROUTE_COLOURS_DARK, 1))
    route_css = "".join(
        f".r{i} .route,.r{i} .new,.r{i} .line{{stroke:var(--r{i})}} .r{i} .area{{fill:var(--r{i})}} "
        f".r{i} .swatch{{background:var(--r{i})}} .r{i} .hl circle{{fill:var(--r{i})}}"
        for i in (1, 2, 3)
    )
    dark = (f"color-scheme:dark;--surface:#1a1a19;--map:#242422;--text:#f0efec;--sec:#c3c2b7;"
            f"--line:#3a3936;--street:#4a4945;{css_dark}")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>
.viz-root{{color-scheme:light;--surface:#fcfcfb;--map:#f3f2ef;--text:#0b0b0b;--sec:#52514e;--line:#e4e2dd;
  --street:#d6d3cc;{css_light}}}
@media (prefers-color-scheme: dark){{:root:where(:not([data-theme="light"])) .viz-root{{{dark}}}}}
:root[data-theme="dark"] .viz-root{{{dark}}}
body{{margin:0}}
.viz-root{{font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:var(--surface);color:var(--text);min-height:100vh}}
main{{max-width:720px;margin:0 auto;padding:24px}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:18px;margin:0 0 8px}} h3{{font-size:15px;margin:16px 0 4px}}
.sec{{color:var(--sec)}}
.card{{border:1px solid var(--line);border-radius:12px;padding:16px;margin:20px 0}}
.swatch{{display:inline-block;width:14px;height:14px;border-radius:4px;margin-right:8px;vertical-align:-1px}}
.stats{{display:flex;gap:24px;flex-wrap:wrap;margin:8px 0 12px}} .stats b{{display:block;font-size:20px}}
.map{{background:var(--map);border-radius:8px;overflow:hidden}}
svg{{display:block;width:100%;height:auto}}
path{{fill:none;stroke-linecap:round;stroke-linejoin:round;vector-effect:non-scaling-stroke}}
#streets path{{stroke:var(--street);stroke-width:1.5}} #streets .trail{{stroke-dasharray:4 3}}
.new{{stroke-width:11;opacity:.3}} .route{{stroke-width:3}}
.start{{fill:var(--text);stroke:var(--surface)}}
.hl circle{{stroke:var(--surface)}} .hl text{{fill:var(--text);font-weight:600}}
.profile .line{{stroke-width:2}} .profile .area{{opacity:.15;stroke:none}}
.grid{{stroke:var(--line);stroke-width:1}} .tick{{font-size:11px;fill:var(--sec)}}
.cross{{stroke:var(--sec);stroke-width:1}}
table{{border-collapse:collapse}} td{{padding:2px 12px 2px 0;font-variant-numeric:tabular-nums}}
ol{{margin:4px 0;padding-left:22px}}
{route_css}
</style></head>
<body><div class="viz-root"><main>
<h1>{html.escape(title)}</h1>
<div class="sec">Target {distance_m / M_PER_MI:.2f} mi · {len(choices)} option{"" if len(choices) == 1 else "s"}</div>
<div class="sec">Wide pale band = new street (under 50% covered) · dot = start · numbered dots = highlights (hover for names)</div>
<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>
<g id="streets">{streets}</g></defs></svg>
{body}
<p class="sec">Map data © OpenStreetMap contributors. Generated offline by the StreetFill pipeline.
Routes are generated from map data. Use your judgement about traffic and safety.</p>
</main></div>
<script>
document.querySelectorAll("svg.profile").forEach(function(svg){{
  var pts=JSON.parse(svg.dataset.points),x0=+svg.dataset.x0,w=+svg.dataset.w,miles=+svg.dataset.miles;
  var cross=svg.querySelector(".cross"),out=svg.nextElementSibling;
  svg.addEventListener("pointermove",function(e){{
    var r=svg.getBoundingClientRect(),vx=(e.clientX-r.left)/r.width*svg.viewBox.baseVal.width;
    var mi=Math.max(0,Math.min(miles,(vx-x0)/w*miles)),best=pts[0];
    pts.forEach(function(p){{if(Math.abs(p[0]-mi)<Math.abs(best[0]-mi))best=p;}});
    var cx=x0+best[0]/miles*w;cross.setAttribute("x1",cx);cross.setAttribute("x2",cx);
    out.textContent="Mile "+best[0].toFixed(2)+" · "+best[1]+" ft";
  }});
}});
</script>
</body></html>
"""


def write_preview(
    out_dir: str | Path,
    graph: Graph,
    choices: Sequence[Choice],
    distance_m: float,
    coverage: Mapping[int, float] = {},
    highlights: Sequence[HighlightPoint] = (),
    *,
    title: str = "Route options",
) -> list[Path]:
    """Write ``preview.html`` and ``option-N.gpx`` for each route into ``out_dir``. Returns the paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    page = out / "preview.html"
    page.write_text(build_preview(graph, choices, distance_m, coverage, highlights, title=title), encoding="utf-8")
    paths = [page]
    for i, ch in enumerate(choices, 1):
        p = out / f"option-{i}.gpx"
        p.write_text(to_gpx(graph, ch.candidate.arcs, f"{title} · option {i}"), encoding="utf-8")
        paths.append(p)
    return paths
