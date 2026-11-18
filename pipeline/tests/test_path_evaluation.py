"""Streets and paths measured and shown separately (plan 5.8 and D7). Toy data only."""

import csv
import json
import re

import pytest
from test_evaluation import write_export, write_labels
from test_matcher import line
from test_path_matching import NET, PARK, STREET, TRAIL

from streetfill.cli import main
from streetfill.evaluation import (
    Metrics,
    edge_layers,
    evaluate_layers,
    label_sheet,
    layered_report,
    match_export,
    predicted_ran,
)
from streetfill.health import HealthExport
from streetfill.matcher import Matcher
from streetfill.pack import write_pack
from streetfill.report import build_report

DRIVE = next(iter(STREET))
TRAIL_ID = next(iter(TRAIL))
PARK_ID = next(iter(PARK))

# One run along the lakefront trail, one along Park Walk; the drive is never run.
RUNS = [line((0, 12), (400, 12)), line((0, 300), (400, 300))]


@pytest.fixture()
def lake(tmp_path):
    pack = tmp_path / "pack.sqlite"
    write_pack(NET, pack)
    export = write_export(tmp_path, RUNS)
    with HealthExport(export) as hx:
        result = match_export(Matcher.from_pack(pack), hx)
    return pack, export, result


def test_result_lists_path_edges(lake):
    _, _, result = lake
    assert result["path_edges"] == sorted(TRAIL | PARK)
    layers = edge_layers(result)
    assert layers[DRIVE] == "street" and layers[TRAIL_ID] == "path" and layers[PARK_ID] == "path"
    pred = predicted_ran(result)
    assert pred[TRAIL_ID] and pred[PARK_ID] and not pred[DRIVE]
    assert result["summary"]["complete_trails"] == 2


def test_old_results_without_path_edges_are_all_streets():
    assert edge_layers({"edges": {"1": [1, 2], "2": [0, 3]}}) == {1: "street", 2: "street"}


def test_label_sheet_has_layer_and_samples_each_layer(lake, tmp_path):
    pack, export, _ = lake
    matcher = Matcher.from_pack(pack)
    with HealthExport(export) as hx:
        geojson, csv_path, n = label_sheet(matcher, hx, tmp_path / "all")
        rows = list(csv.DictReader(open(csv_path)))
        assert {int(r["edge_id"]): r["layer"] for r in rows} == {DRIVE: "street", TRAIL_ID: "path", PARK_ID: "path"}
        doc = json.load(open(geojson))
        assert {f["properties"]["layer"] for f in doc["features"] if f["properties"]["kind"] == "edge"} == {
            "street",
            "path",
        }

        # sampling is per layer, so the street sample cannot crowd paths out
        _, csv_path, n = label_sheet(matcher, hx, tmp_path / "s", sample=1, path_sample=1, seed=3)
        rows = list(csv.DictReader(open(csv_path)))
        assert n == 2 and sorted(r["layer"] for r in rows) == ["path", "street"]
        _, csv_path, n = label_sheet(matcher, hx, tmp_path / "z", sample=0, path_sample=None)
        assert n == 2 and all(r["layer"] == "path" for r in csv.DictReader(open(csv_path)))


def test_evaluate_layers_splits_metrics():
    labels = {1: True, 2: False, 10: True, 11: True, 99: True}
    preds = {1: True, 2: True, 10: True, 11: False}
    layers = {1: "street", 2: "street", 10: "path", 11: "path"}
    m = evaluate_layers(labels, preds, layers)
    assert (m["street"].labelled, m["street"].correct, m["street"].false_positive) == (2, 1, [2])
    assert m["street"].unknown == [99]  # not in the result: reported with streets
    assert (m["path"].labelled, m["path"].found, m["path"].false_negative) == (2, 1, [11])


def test_layered_report_sections():
    text = layered_report({"street": Metrics(labelled=2, correct=2), "path": Metrics()})
    assert text.index("Streets (Gate 1)") < text.index("Paths and trails")
    assert "no path edges labelled" in text


def test_cli_evaluate_reports_paths_separately(lake, tmp_path, capsys):
    pack, export, result = lake
    match = tmp_path / "match.json"
    match.write_text(json.dumps(result))
    labels = tmp_path / "labels.csv"
    write_labels(labels, {DRIVE: "not_run", TRAIL_ID: "ran", PARK_ID: "not_run"})
    assert main(["evaluate", "--labels", str(labels), "--match", str(match)]) == 0
    out = capsys.readouterr().out
    streets, paths = out.split("Paths and trails")
    assert "agreement: 100.0% (1 correct of 1 labelled)" in streets
    assert "agreement: 50.0% (1 correct of 2 labelled)" in paths
    assert f"false positives (credited, not run): 1 [{PARK_ID}]" in paths


def test_report_draws_paths_dashed_and_counts_them_apart(lake):
    pack, _, result = lake
    page = build_report(pack, result)
    group = re.search(r'<g class="paths">(.*?)</g>', page, re.S).group(1)
    assert f"(edge {TRAIL_ID})" in group and f"(edge {PARK_ID})" in group
    assert f"(edge {DRIVE})" not in group
    assert "stroke-dasharray" in page
    # streets only in the street percentage: the drive was never run
    assert "<b>0.0%</b>" in page
    assert re.search(r"<b>0\.8 km</b><span class=\"sec\">of 0\.8 km paths and trails", page)
    assert "<b>2</b><span class=\"sec\">trails complete" in page
    trails = page.split("<h2>Trails</h2>")[1]
    assert "Lakefront Trail" in trails and "Park Walk" in trails
    assert "Lake Drive" not in trails
