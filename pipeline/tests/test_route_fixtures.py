"""Shared route fixtures for the Swift port (issue #49). Synthetic data only."""

import json
from pathlib import Path

import pytest
from test_fixtures import close

from streetfill.costs import Preferences
from streetfill.route_fixtures import builtin_route_fixture, dumps
from streetfill.route_highlights import HighlightPoint
from streetfill.routing import Graph
from streetfill.scoring import best_routes

COMMITTED = Path(__file__).resolve().parents[1] / "fixtures" / "routes.json"


@pytest.fixture(scope="module")
def fixture():
    return json.loads(dumps(builtin_route_fixture()))


def test_committed_fixture_is_up_to_date(fixture):
    # if this fails after a deliberate routing change, run `streetfill fixtures` and commit the result
    close(fixture, json.loads(COMMITTED.read_text(encoding="utf-8")))


def test_fixture_is_self_contained(fixture):
    """Rebuild everything from the JSON alone, as the Swift tests will, and get the same routes."""
    graph = Graph.from_rows(tuple(fixture["origin"]), fixture["pack_edges"])
    highlights = [HighlightPoint(i, name, cat, graph.projection.to_xy((lat, lon)))
                  for i, name, cat, lat, lon in fixture["highlights"]]
    coverage = {int(k): v for k, v in fixture["coverage"].items()}
    for case in fixture["cases"]:
        prefs = Preferences(**case["preferences"])
        chosen = best_routes(graph, tuple(case["start"]), case["distance_m"], prefs, coverage, highlights,
                             seed=case["seed"], shape=case["shape"])
        got = []
        for ch in chosen:
            arcs = []
            for eid, fwd in ch.candidate.arcs:
                e = graph.edges[eid]
                a, b = (e.u, e.v) if fwd else (e.v, e.u)
                arcs.append([e.pack_id, *graph.coords[a], *graph.coords[b], e.length_m])
            got.append(arcs)
        close(got, [r["arcs"] for r in case["routes"]], case["name"])


def test_cases_cover_the_preferences(fixture):
    cases = fixture["cases"]
    assert len(cases) == 9 and all(len(c["routes"]) == 3 for c in cases)
    assert {c["shape"] for c in cases} == {"loop", "out_and_back"}
    prefs = [c["preferences"] for c in cases]
    assert any(p["quiet"] for p in prefs) and any(p["newness"] > 0 for p in prefs) and any(p["scenery"] for p in prefs)
    assert {p["terrain"] for p in prefs} >= {-1.0, 0.0, 1.0}
    assert any(r["pulled"] for c in cases for r in c["routes"])  # the scenery pull is exercised
    layers = {row[6] for row in fixture["pack_edges"]}
    assert layers == {"street", "path", "steps"}
    assert all(row[8] for row in fixture["pack_edges"])  # every edge has an elevation profile
    # routes are continuous walks from the start back to the start
    for c in cases:
        for r in c["routes"]:
            arcs = r["arcs"]
            assert all(a[3:5] == b[1:3] for a, b in zip(arcs, arcs[1:])), c["name"]
            assert arcs[0][1:3] == arcs[-1][3:5] == r["waypoints"][0]
            assert sum(a[5] for a in arcs) == pytest.approx(r["length_m"])
    assert "costs.MIN_FACTOR" in fixture["constants"] and "loops.K" in fixture["constants"]
