"""Route preview output: GPX and the HTML page (issue #16). Synthetic networks only."""

import xml.etree.ElementTree as ET

import pytest
from test_loops import START, city  # noqa: F401  (the 4 x 4 km grid fixture)
from test_matcher import PROJ
from test_routing_graph import node_at
from test_scoring import LOOP_M, around, block  # noqa: F401  (the 300 x 200 m block fixture)

from streetfill.preview import (
    build_preview,
    elevation_profile,
    highlight_stops,
    route_coords,
    to_gpx,
    write_preview,
)
from streetfill.route_highlights import HighlightPoint
from streetfill.scoring import best_routes

GPX = "{http://www.topografix.com/GPX/1/1}"


def hl(g, i, p, name=None, category="landmark"):
    return HighlightPoint(i, name or f"H{i}", category, g.projection.to_xy(PROJ.to_latlon(p)))


def test_route_coords_and_profile(block):
    for i in range(len(block.coords)):
        block.elevation[i] = 180.0 + i
    arcs = around(block)
    pts = route_coords(block, arcs)
    start = node_at(block, (0, 0))
    assert pts[0] == (block.coords[start], block.elevation[start]) and pts[-1] == pts[0]
    assert all(e is not None for _, e in pts)  # every point of this block is a node
    prof = elevation_profile(block, arcs)
    assert prof[0] == (0.0, block.elevation[start])
    assert [d for d, _ in prof] == sorted(d for d, _ in prof) and prof[-1][0] == pytest.approx(LOOP_M, abs=0.5)
    block.elevation[:] = [None] * len(block.coords)
    assert elevation_profile(block, arcs) == [] and all(e is None for _, e in route_coords(block, arcs))


def test_highlight_stops_in_route_order(block):
    hs = [hl(block, 1, (300, 100)), hl(block, 2, (150, -50)), hl(block, 3, (150, 100)), hl(block, 4, (-60, 50))]
    stops = highlight_stops(block, around(block), hs)
    # South from (0, 0) east, then East north, North west, West south
    assert [s.highlight.id for s in stops] == [2, 1, 4]  # 3 is 100 m from every street
    assert [s.at_m for s in stops] == pytest.approx([150, 400, 950], abs=1.0)  # 4 is 150 m down West


def test_gpx_is_valid_and_escaped(block):
    doc = to_gpx(block, around(block), "Loop <one> & two")
    root = ET.fromstring(doc)
    assert root.tag == f"{GPX}gpx" and root.get("version") == "1.1"
    assert root.find(f"{GPX}trk/{GPX}name").text == "Loop <one> & two"
    pts = root.findall(f".//{GPX}trkpt")
    assert len(pts) == len(route_coords(block, around(block)))
    lat, lon = block.coords[node_at(block, (0, 0))]
    assert float(pts[0].get("lat")) == pytest.approx(lat) and float(pts[0].get("lon")) == pytest.approx(lon)
    assert to_gpx(block, [], "Empty").count("<trkpt") == 0


def test_preview_page(city):  # noqa: F811
    hs = [hl(city, 1, (300, 300), '<script>alert("x")</script>'), hl(city, 2, (-400, 0), "Pond", "water")]
    coverage = {e.pack_id: 1.0 for e in city.edges.values() if e.id % 2}
    chosen = best_routes(city, START, 5000, coverage=coverage, highlights=hs, seed=1)
    page = build_preview(city, chosen, 5000, coverage, hs, title="Grid & co")
    assert page.count('<section class="card') == len(chosen) == 3
    assert "<script>alert" not in page and "&lt;script&gt;alert" in page  # names are escaped
    assert "<title>Grid &amp; co</title>" in page
    assert "src=" not in page and 'href="http' not in page  # nothing loaded from the network
    assert page.count('class="new"') == 3 and 'class="profile"' not in page  # no elevation on this grid
    assert "No elevation data" in page and "Use your judgement about traffic and safety" in page
    assert "No routes were found" in build_preview(city, [], 5000)


def test_write_preview(city, tmp_path):  # noqa: F811
    chosen = best_routes(city, START, 3000, seed=2, shape="out_and_back")
    paths = write_preview(tmp_path / "out", city, chosen, 3000, title="Grid")
    assert [p.name for p in paths] == ["preview.html", "option-1.gpx", "option-2.gpx", "option-3.gpx"]
    assert "out-and-back" in paths[0].read_text()
    for p in paths[1:]:
        ET.parse(p)
