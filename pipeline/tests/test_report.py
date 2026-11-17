"""HTML coverage report on a toy pack (no real data)."""

import re
from html.parser import HTMLParser

import pytest
from test_evaluation import MAIN_MID, MAIN_WEST, PAR_WEST, RUNS, toy, write_export  # noqa: F401
from test_matcher import GRID

from streetfill.cli import main
from streetfill.evaluation import match_export
from streetfill.health import HealthExport
from streetfill.matcher import Matcher
from streetfill.network import build_network
from streetfill.osm import OsmData, Way
from streetfill.pack import write_pack
from streetfill.report import build_report, edge_class


@pytest.fixture()
def report(toy):
    pack, export = toy
    with HealthExport(export) as hx:
        result = match_export(Matcher.from_pack(pack), hx)
    return build_report(pack, result), result


def classes_by_edge(page):
    return {int(m.group(2)): m.group(1) for m in re.finditer(r'<path class="(\w+)".*?\(edge (\d+)\)</title>', page)}


def test_edge_class():
    assert edge_class(0, 10, 0.5) == "none"
    assert edge_class(4, 10, 0.5) == "partial"
    assert edge_class(5, 10, 0.5) == "ran"
    assert edge_class(0, 0, 0.5) == "none"


def test_report_colours_edges_by_coverage(report):
    page, _ = report
    cls = classes_by_edge(page)
    assert len(cls) == len(GRID.edges)
    assert cls[MAIN_MID] == "ran" and cls[PAR_WEST] == "ran"
    assert cls[MAIN_WEST] == "none"


def test_report_summary_and_table(report):
    page, result = report
    assert f"{result['summary']['workouts']} workouts matched" in page
    assert "Main Street" in page and "Parallel Street" in page
    assert "© OpenStreetMap contributors" in page
    total_km = sum(e.length_m for e in GRID.edges) / 1000
    assert f"of {total_km:.1f} km" in page


def test_report_is_self_contained(report):
    page, _ = report
    assert not re.search(r"""(src|href)\s*=\s*["']?(https?:)?//""", page)
    assert "http://" not in page.replace('xmlns="http://www.w3.org/2000/svg"', "")
    assert "https://" not in page
    assert "<link" not in page and "@import" not in page


def test_report_is_well_formed(report):
    page, _ = report

    class Checker(HTMLParser):
        stack, errors = [], []
        void = {"meta", "br", "img", "input", "link"}

        def handle_starttag(self, tag, attrs):
            if tag not in self.void:
                self.stack.append(tag)

        def handle_endtag(self, tag):
            if not self.stack or self.stack.pop() != tag:
                self.errors.append(tag)

    c = Checker()
    c.feed(page)
    assert c.errors == [] and c.stack == []


def test_report_escapes_street_names(tmp_path):
    from streetfill.geo import LocalProjection

    proj = LocalProjection(41.9, -87.65)
    nodes = {1: proj.to_latlon((0, 0)), 2: proj.to_latlon((100, 0))}
    net = build_network(OsmData(nodes, [Way(1, (1, 2), {"highway": "residential", "name": "<b>A&B</b>"})]))
    write_pack(net, tmp_path / "p.sqlite")
    page = build_report(tmp_path / "p.sqlite", {"edges": {"1": [5, 5]}, "summary": {"workouts": 1}})
    assert "<b>A&B</b>" not in page
    assert "&lt;b&gt;A&amp;B&lt;/b&gt;" in page


def test_cli_report(toy, tmp_path, capsys):
    pack, export = toy
    result = tmp_path / "match.json"
    assert main(["match", "--pack", str(pack), "--export", str(export), "--out", str(result)]) == 0
    out = tmp_path / "report.html"
    assert main(["report", "--pack", str(pack), "--match", str(result), "--out", str(out)]) == 0
    assert "wrote" in capsys.readouterr().out
    assert out.read_text().startswith("<!doctype html>")
