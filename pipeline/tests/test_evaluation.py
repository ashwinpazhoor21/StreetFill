"""Gate 1 tooling on a toy pack and a synthetic Health export (no real data)."""

import csv
import json
from datetime import timedelta, timezone

import pytest
from conftest import BASE, HEADER, workout_xml
from test_matcher import GRID, PROJ, edge_id, line

from streetfill.cli import main
from streetfill.evaluation import (
    Metrics,
    evaluate,
    label_sheet,
    load_result,
    match_export,
    predicted_ran,
    read_labels,
)
from streetfill.health import HealthExport
from streetfill.matcher import Matcher
from streetfill.pack import write_pack

MAIN_MID = edge_id(GRID, "name:main street", 0, 200)
MAIN_WEST = edge_id(GRID, "name:main street", -200, 0)
MAIN_EAST = edge_id(GRID, "name:main street", 200, 400)
PAR_WEST = edge_id(GRID, "name:parallel street", -200, 0)
CROSS_SOUTH = edge_id(GRID, "name:cross avenue", -100, 0)

RUNS = [
    line((0, 0), (200, 0)),  # Main Street, middle block
    line((-190, 80), (190, 80)),  # Parallel Street, two blocks
]


def gpx_for(xy_points, start):
    pts = []
    for k, xy in enumerate(xy_points):
        lat, lon = PROJ.to_latlon(xy)
        t = (start + timedelta(seconds=k)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        pts.append(f'<trkpt lon="{lon:.7f}" lat="{lat:.7f}"><time>{t}</time><extensions><hAcc>5</hAcc></extensions></trkpt>')
    return ('<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">'
            f"<trk><trkseg>{''.join(pts)}</trkseg></trk></gpx>")


def write_export(root, runs):
    folder = root / "apple_health_export"
    (folder / "workout-routes").mkdir(parents=True)
    with open(folder / "export.xml", "w", encoding="utf-8") as fh:
        fh.write(HEADER)
        for i, pts in enumerate(runs):
            name = f"route_{i}.gpx"
            (folder / "workout-routes" / name).write_text(gpx_for(pts, BASE + timedelta(days=i)))
            fh.write(workout_xml(i, "Running", route=name, legacy_distance=True, indoor=False))
        # an indoor treadmill run with a stray route must be ignored
        (folder / "workout-routes" / "treadmill.gpx").write_text(gpx_for(line((0, -100), (0, 180)), BASE))
        fh.write(workout_xml(len(runs), "Running", route="treadmill.gpx", legacy_distance=True, indoor=True))
        fh.write("</HealthData>\n")
    return folder


@pytest.fixture()
def toy(tmp_path):
    pack = tmp_path / "pack.sqlite"
    write_pack(GRID, pack)
    export = write_export(tmp_path, RUNS)
    return pack, export


def write_labels(path, labels):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["edge_id", "street", "highway", "length_m", "label"])
        for eid, label in labels.items():
            w.writerow([eid, "", "residential", "200", label])


# --- match ------------------------------------------------------------------------

def test_match_export(toy):
    pack, export = toy
    matcher = Matcher.from_pack(pack)
    with HealthExport(export) as hx:
        result = match_export(matcher, hx)
    assert result["schema"] == 1
    assert result["summary"]["workouts"] == 2  # the indoor run is skipped
    pred = predicted_ran(result)
    assert pred[MAIN_MID] and pred[PAR_WEST]
    assert not pred[MAIN_WEST] and not pred[CROSS_SOUTH]
    assert result["config"]["visit_radius_m"] == 20
    assert json.loads(json.dumps(result)) == result


def test_predicted_ran_threshold():
    result = {"edges": {"1": [5, 10], "2": [4, 10], "3": [0, 0]}}
    assert predicted_ran(result) == {1: True, 2: False, 3: False}
    assert predicted_ran(result, threshold=0.4) == {1: True, 2: True, 3: False}


# --- label sheet --------------------------------------------------------------------

def test_label_sheet(toy, tmp_path):
    pack, export = toy
    matcher = Matcher.from_pack(pack)
    with HealthExport(export) as hx:
        geojson, csv_path, n = label_sheet(matcher, hx, tmp_path / "labels")
    rows = list(csv.DictReader(open(csv_path)))
    ids = {int(r["edge_id"]) for r in rows}
    assert n == len(rows)
    assert {MAIN_MID, PAR_WEST, MAIN_WEST, CROSS_SOUTH} <= ids  # run edges and their neighbours
    assert all(r["label"] == "" for r in rows)
    assert {r["street"] for r in rows} >= {"Main Street", "Parallel Street"}

    doc = json.load(open(geojson))
    kinds = [f["properties"]["kind"] for f in doc["features"]]
    assert kinds.count("edge") == n and kinds.count("route") == 2
    for f in doc["features"]:
        assert not any(k in f["properties"] for k in ("predicted", "visited", "fraction"))  # blind labelling
    lon, lat = doc["features"][0]["geometry"]["coordinates"][0]
    assert -88 < lon < -87 and 41 < lat < 42  # GeoJSON order is lon, lat


def test_label_sheet_near_radius(toy, tmp_path):
    pack, export = toy
    matcher = Matcher.from_pack(pack)
    par_east = edge_id(GRID, "name:parallel street", 200, 400)
    with HealthExport(export) as hx:
        _, csv_path, _ = label_sheet(matcher, hx, tmp_path / "near", near_m=5)
    ids = {int(r["edge_id"]) for r in csv.DictReader(open(csv_path))}
    assert par_east not in ids  # the Parallel run stops 10 m short of it
    assert MAIN_MID in ids and PAR_WEST in ids


def test_label_sheet_sample_is_deterministic(toy, tmp_path):
    pack, export = toy
    matcher = Matcher.from_pack(pack)
    with HealthExport(export) as hx:
        _, a, n1 = label_sheet(matcher, hx, tmp_path / "a", sample=3, seed=7)
        _, b, n2 = label_sheet(matcher, hx, tmp_path / "b", sample=3, seed=7)
    assert n1 == n2 == 3
    assert open(a).read() == open(b).read()


# --- evaluate -----------------------------------------------------------------------

def test_metrics_arithmetic():
    labels = {1: True, 2: True, 3: True, 4: False, 5: False, 9: True}
    preds = {1: True, 2: True, 3: False, 4: False, 5: True}
    m = evaluate(labels, preds)
    assert (m.labelled, m.correct, m.labelled_ran, m.found) == (5, 3, 3, 2)
    assert m.agreement == pytest.approx(0.6) and m.recall == pytest.approx(2 / 3)
    assert m.false_negative == [3] and m.false_positive == [5]
    assert m.unknown == [9]
    text = m.report()
    assert "agreement: 60.0% (3 correct of 5 labelled)" in text
    assert "recall:    66.7% (2 found of 3 labelled ran)" in text
    assert "not in the match result" in text


def test_metrics_with_nothing_labelled():
    assert Metrics().agreement is None and "n/a" in Metrics().report()


def test_read_labels_aliases_skips_and_errors(tmp_path):
    path = tmp_path / "l.csv"
    write_labels(path, {1: "ran", 2: "NOT_RUN", 3: "", 4: "skip", 5: "yes", 6: "n"})
    assert read_labels(path) == {1: True, 2: False, 5: True, 6: False}
    write_labels(path, {1: "maybe"})
    with pytest.raises(ValueError, match=":2: unknown label"):
        read_labels(path)
    path.write_text("id,value\n1,ran\n")
    with pytest.raises(ValueError, match="edge_id and label"):
        read_labels(path)


def test_load_result_rejects_other_schemas(tmp_path):
    path = tmp_path / "r.json"
    path.write_text('{"schema": 99}')
    with pytest.raises(ValueError, match="schema"):
        load_result(path)


# --- end to end through the CLI -----------------------------------------------------

def test_cli_gate1_workflow(toy, tmp_path, capsys):
    pack, export = toy
    result = tmp_path / "match.json"
    assert main(["match", "--pack", str(pack), "--export", str(export), "--out", str(result)]) == 0
    assert "matched 2 workouts" in capsys.readouterr().out

    out_dir = tmp_path / "labels"
    assert main(["label-sheet", "--pack", str(pack), "--export", str(export), "--out-dir", str(out_dir)]) == 0
    assert "edges to label" in capsys.readouterr().out

    # The owner's labels: truth for the two runs, plus one edge he says he ran
    # that the matcher did not credit (Cross Avenue south block).
    labels = {MAIN_MID: "ran", PAR_WEST: "ran", MAIN_WEST: "not_run", MAIN_EAST: "not_run", CROSS_SOUTH: "ran"}
    write_labels(out_dir / "labels.csv", labels)
    assert main(["evaluate", "--labels", str(out_dir / "labels.csv"), "--match", str(result)]) == 0
    out = capsys.readouterr().out
    assert "agreement: 80.0% (4 correct of 5 labelled)" in out
    assert "recall:    66.7% (2 found of 3 labelled ran)" in out
    assert f"false negatives (run, not credited): 1 [{CROSS_SOUTH}]" in out


def test_cli_evaluate_reports_bad_input(tmp_path, capsys):
    bad = tmp_path / "l.csv"
    bad.write_text("nope\n")
    (tmp_path / "m.json").write_text('{"schema": 1, "edges": {}}')
    assert main(["evaluate", "--labels", str(bad), "--match", str(tmp_path / "m.json")]) == 2
    assert "error:" in capsys.readouterr().err
