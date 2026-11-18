"""Self-contained HTML preview of coverage: an SVG map plus street and trail tables.

The page loads nothing from the network (no tiles, fonts or scripts), so it can
be opened from disk and shared without leaking anything. Streets and paths are
both drawn (paths dashed, on top) but counted separately: the street percentage
covers streets only (plan D7) and paths get their own totals. Route traces are
not drawn, because match results do not store them.
"""

from __future__ import annotations

import html
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .geo import LocalProjection
from .pack import decode_geometry

#: Stroke width (px at default zoom) by road class.
WIDTH = {"trunk": 6.0, "primary": 5.5, "secondary": 4.5, "tertiary": 4.0}
DEFAULT_WIDTH = 3.0
PATH_WIDTH = 2.5
SVG_WIDTH = 1000.0


@dataclass
class _Edge:
    id: int
    street_id: int
    highway: str
    xy: list[tuple[float, float]]
    layer: str = "street"


@dataclass
class StreetRow:
    name: str
    visited: int
    total: int
    length_m: float

    @property
    def fraction(self) -> float:
        return self.visited / self.total if self.total else 0.0


def _load_pack(path: str | Path):
    con = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        meta = dict(con.execute("SELECT key, value FROM meta"))
        proj = LocalProjection(float(meta["origin_lat"]), float(meta["origin_lon"]))
        streets = {
            sid: (name, length, layer)
            for sid, name, length, layer in con.execute("SELECT id, name, length_m, layer FROM streets")
        }
        edges = [
            _Edge(eid, sid, hw, [proj.to_xy(p) for p in decode_geometry(blob)], layer)
            for eid, sid, hw, blob, layer in con.execute(
                "SELECT id, street_id, highway, geometry, layer FROM edges "
                "WHERE layer IN ('street', 'path') ORDER BY id"
            )
        ]
    finally:
        con.close()
    return meta, streets, edges


def edge_class(hit: int, total: int, ran_threshold: float) -> str:
    if total == 0 or hit == 0:
        return "none"
    return "ran" if hit / total >= ran_threshold else "partial"


def build_report(pack: str | Path, result: dict, *, ran_threshold: float = 0.5, complete_frac: float = 0.9) -> str:
    meta, streets, edges = _load_pack(pack)
    if not edges:
        raise ValueError("pack has no edges")
    cov = {int(k): tuple(v) for k, v in result.get("edges", {}).items()}

    xs = [x for e in edges for x, _ in e.xy]
    ys = [y for e in edges for _, y in e.xy]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    span_x, span_y = max(max_x - min_x, 1.0), max(max_y - min_y, 1.0)
    scale = SVG_WIDTH / span_x
    height = max(200.0, span_y * scale)
    pad = 10.0

    def pt(x: float, y: float) -> str:
        return f"{(x - min_x) * scale + pad:.1f},{(max_y - y) * scale + pad:.1f}"

    drawn = {layer: {"none": [], "partial": [], "ran": []} for layer in ("street", "path")}
    per_street: dict[int, list[int]] = {}
    covered = {"street": 0.0, "path": 0.0}
    length_total = {"street": 0.0, "path": 0.0}
    for e in edges:
        hit, total = cov.get(e.id, (0, 0))
        cls = edge_class(hit, total, ran_threshold)
        fallback = "Unnamed path" if e.layer == "path" else "Unnamed street"
        name = streets.get(e.street_id, (None, 0, e.layer))[0] or fallback
        length = sum(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5 for a, b in zip(e.xy, e.xy[1:]))
        length_total[e.layer] += length
        covered[e.layer] += length * hit / total if total else 0.0
        acc = per_street.setdefault(e.street_id, [0, 0])
        acc[0] += hit
        acc[1] += total
        d = "M" + " L".join(pt(x, y) for x, y in e.xy)
        w = PATH_WIDTH if e.layer == "path" else WIDTH.get(e.highway, DEFAULT_WIDTH)
        title = html.escape(f"{name}: {hit}/{total} checkpoints (edge {e.id})")
        drawn[e.layer][cls].append(f'<path class="{cls}" d="{d}" stroke-width="{w}"><title>{title}</title></path>')

    def rows_for(layer: str) -> list[StreetRow]:
        rows = [
            StreetRow(streets[sid][0], hit, total, streets[sid][1])
            for sid, (hit, total) in per_street.items()
            if sid in streets and streets[sid][2] == layer and hit > 0
            # unnamed paths count toward path length but are not trails
            and (layer == "street" or streets[sid][0])
        ]
        for r in rows:
            r.name = r.name or "Unnamed street"
        rows.sort(key=lambda r: (-r.fraction, -r.length_m, r.name))
        return rows

    def table_rows(rows: list[StreetRow]) -> str:
        return "\n".join(
            f"<tr><td>{html.escape(r.name)}</td><td>{r.fraction:.0%}</td><td>{r.length_m / 1000:.2f} km</td>"
            f"<td>{'✓' if r.fraction >= complete_frac else ''}</td></tr>"
            for r in rows[:200]
        )

    rows, trail_rows = rows_for("street"), rows_for("path")
    complete = sum(1 for r in rows if r.fraction >= complete_frac)
    trails_complete = sum(1 for r in trail_rows if r.fraction >= complete_frac)
    covered_m, total_m = covered["street"], length_total["street"]
    path_covered_m, path_total_m = covered["path"], length_total["path"]
    pct = covered_m / total_m if total_m else 0.0
    workouts = result.get("summary", {}).get("workouts", len(result.get("workouts", [])))
    has_paths = path_total_m > 0

    table = table_rows(rows)
    street_svg = "\n".join(drawn["street"]["none"] + drawn["street"]["partial"] + drawn["street"]["ran"])
    path_svg = "\n".join(drawn["path"]["none"] + drawn["path"]["partial"] + drawn["path"]["ran"])
    svg_body = street_svg + (f'\n<g class="paths">\n{path_svg}\n</g>' if path_svg else "")  # covered on top
    path_stats = (
        f'<div><b>{path_covered_m / 1000:.1f} km</b><span class="sec">of {path_total_m / 1000:.1f} km '
        f"paths and trails</span></div>\n"
        f'<div><b>{trails_complete}</b><span class="sec">trails complete</span></div>'
        if has_paths
        else ""
    )
    path_legend = " · dashed = path or trail" if has_paths else ""
    trail_table = (
        "<h2>Trails</h2>\n<table><thead><tr><th>Trail</th><th>Covered</th><th>Length</th><th>Complete</th></tr>"
        f"</thead><tbody>\n{table_rows(trail_rows)}\n</tbody></table>"
        if trail_rows
        else ""
    )
    built = html.escape(meta.get("built_at", ""))
    attribution = html.escape(meta.get("attribution", "© OpenStreetMap contributors"))
    vw, vh = SVG_WIDTH + 2 * pad, height + 2 * pad

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>StreetFill coverage report</title>
<style>
:root{{--bg:#FAF8F5;--text:#14161A;--sec:#555A63;--line:#E6E3DD;--accent:#D24F28;--partial:#F2B8A4;--none:#C9C5BD}}
body{{margin:0;font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:var(--bg);color:var(--text)}}
main{{max-width:1080px;margin:0 auto;padding:24px}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:17px;margin:24px 0 0}} .sec{{color:var(--sec)}}
.stats{{display:flex;gap:24px;flex-wrap:wrap;margin:16px 0}} .stats b{{display:block;font-size:24px}}
.map{{background:#F1EEE8;border:1px solid var(--line);border-radius:12px;overflow:hidden;touch-action:none}}
svg{{display:block;width:100%;height:auto;cursor:grab}}
path{{fill:none;stroke-linecap:round;stroke-linejoin:round;vector-effect:non-scaling-stroke}}
path.none{{stroke:var(--none)}} path.partial{{stroke:var(--partial)}} path.ran{{stroke:var(--accent)}}
.paths path{{stroke-dasharray:6 4}} path:hover{{stroke:#2668D8}}
.legend span{{display:inline-block;width:18px;height:4px;border-radius:2px;margin:0 6px 2px 14px;vertical-align:middle}}
table{{border-collapse:collapse;width:100%;margin-top:16px}} td,th{{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}}
</style></head>
<body><main>
<h1>Coverage report</h1>
<div class="sec">Pack built {built} · {workouts} workouts matched · ran = at least {ran_threshold:.0%} of an edge's checkpoints</div>
<div class="stats">
<div><b>{pct:.1%}</b><span class="sec">of street length</span></div>
<div><b>{covered_m / 1000:.1f} km</b><span class="sec">of {total_m / 1000:.1f} km</span></div>
<div><b>{complete}</b><span class="sec">streets complete (≥{complete_frac:.0%})</span></div>
{path_stats}
</div>
<div class="legend sec"><span style="background:var(--accent)"></span>ran<span style="background:var(--partial)"></span>partly<span style="background:var(--none)"></span>not yet{path_legend} · scroll to zoom, drag to pan, hover a street for details</div>
<div class="map"><svg id="map" viewBox="0 0 {vw:.1f} {vh:.1f}" xmlns="http://www.w3.org/2000/svg">
{svg_body}
</svg></div>
<table><thead><tr><th>Street</th><th>Covered</th><th>Length</th><th>Complete</th></tr></thead><tbody>
{table}
</tbody></table>
{trail_table}
<p class="sec">Map data {attribution}. Generated offline by the StreetFill pipeline.</p>
</main>
<script>
(function(){{
  var svg=document.getElementById("map"),vb=svg.viewBox.baseVal,drag=null;
  function pt(e){{var r=svg.getBoundingClientRect();return [vb.x+(e.clientX-r.left)/r.width*vb.width,vb.y+(e.clientY-r.top)/r.height*vb.height];}}
  svg.addEventListener("wheel",function(e){{e.preventDefault();var p=pt(e),k=e.deltaY<0?0.8:1.25;
    vb.x=p[0]-(p[0]-vb.x)*k;vb.y=p[1]-(p[1]-vb.y)*k;vb.width*=k;vb.height*=k;}},{{passive:false}});
  svg.addEventListener("pointerdown",function(e){{drag=pt(e);svg.setPointerCapture(e.pointerId);}});
  svg.addEventListener("pointermove",function(e){{if(!drag)return;var p=pt(e);vb.x-=p[0]-drag[0];vb.y-=p[1]-drag[1];}});
  svg.addEventListener("pointerup",function(){{drag=null;}});
}})();
</script>
</body></html>
"""


def write_report(pack: str | Path, result: dict, out: str | Path, **kwargs) -> Path:
    out = Path(out)
    out.write_text(build_report(pack, result, **kwargs), encoding="utf-8")
    return out
