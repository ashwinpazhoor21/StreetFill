"""Shared matcher fixtures for the Swift port (issue #48). Synthetic data only."""

import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path

import pytest

from streetfill.cli import main
from streetfill.fixtures import builtin_matcher_fixture, dumps
from streetfill.geo import LocalProjection
from streetfill.health import RoutePoint
from streetfill.matcher import MatchEdge, Matcher
from streetfill.matching import MatchConfig

COMMITTED = Path(__file__).resolve().parents[1] / "fixtures" / "matcher.json"


@pytest.fixture(scope="module")
def fixture():
    return builtin_matcher_fixture()


def close(a, b, path="$"):
    """Equal, with floats compared to 1e-9 so a different libm cannot fail the check."""
    if isinstance(a, float) or isinstance(b, float):
        assert isinstance(a, (int, float)) and isinstance(b, (int, float)) and math.isclose(a, b, abs_tol=1e-9), path
    elif isinstance(a, dict):
        assert isinstance(b, dict) and a.keys() == b.keys(), path
        for k in a:
            close(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list):
        assert isinstance(b, list) and len(a) == len(b), (path, len(a), len(b))
        for i, (x, y) in enumerate(zip(a, b)):
            close(x, y, f"{path}[{i}]")
    else:
        assert a == b, (path, a, b)


def test_committed_fixture_is_up_to_date(fixture):
    # if this fails after a deliberate matcher change, run `streetfill fixtures` and commit the result
    close(json.loads(dumps(fixture)), json.loads(COMMITTED.read_text(encoding="utf-8")))


def test_fixture_is_self_contained(fixture):
    """Rebuild the matcher from the JSON alone, as the Swift tests will, and get the same answers."""
    doc = json.loads(dumps(fixture))
    assert doc["schema"] == 1 and doc["kind"] == "matcher"
    edges = [MatchEdge(e["id"], e["street"], e["highway"], [tuple(c) for c in e["coords"]], e["layer"])
             for e in doc["edges"]]
    matcher = Matcher(edges, LocalProjection(*doc["origin"]), MatchConfig(**doc["config"]))
    assert [[c.edge_id, c.index] for c in matcher.checkpoints] == [c[:2] for c in doc["checkpoints"]]
    for r in doc["routes"]:
        points = [RoutePoint(lat, lon, datetime.fromisoformat(t) if t else None, acc) for lat, lon, t, acc in r["points"]]
        assert [list(k) for k in matcher.match(points)] == r["visited"], r["name"]


def test_scenarios_do_what_they_say(fixture):
    total = Counter(c[0] for c in fixture["checkpoints"])
    got = {r["name"]: Counter(e for e, _ in r["visited"]) for r in fixture["routes"]}
    assert len(got) == 12
    assert got["main-street"] == {1: total[1], 2: total[2]}
    assert got["out-and-back"] == {5: total[5], 6: total[6], 7: total[7]}
    assert got["lakefront-trail"] == {9: total[9]} and got["lake-drive"] == {8: total[8]}  # the right layer only
    assert got["between-twins"] == {}  # a tie credits neither street
    assert got["no-timestamps"] == {3: total[3], 4: total[4]}
    assert got["bend"] == {13: total[13]}
    assert total[12] == 1 and got["short-edge"][12] == 1  # one midpoint checkpoint
    assert 8 not in got["gps-jump"]  # the jump onto Lake Drive credits nothing
    assert got["inaccurate-points"][3] < total[3] and got["inaccurate-points"][4] < total[4]
    assert sum(got["time-gap"].values()) < total[1] + total[2]  # the gap is not bridged
    assert got["corner"][1] >= total[1] - 2 and got["corner"][6] < total[6]


def test_cli_writes_the_fixture(tmp_path, capsys):
    assert main(["fixtures", "--out-dir", str(tmp_path)]) == 0
    close(json.loads((tmp_path / "matcher.json").read_text(encoding="utf-8")),
          json.loads(COMMITTED.read_text(encoding="utf-8")))
    assert "matcher.json" in capsys.readouterr().out
