"""Gate 1 tooling: match a Health export, make a label sheet, measure accuracy (plan 5.8).

Workflow (outputs contain location history, so keep them under the git-ignored
``data/`` folder):

1. ``streetfill match --pack P --export E --out data/match.json``
2. ``streetfill label-sheet --pack P --export E --out-dir data/labels`` writes
   ``edges.geojson`` (edges near your runs, plus your route traces for reference)
   and ``labels.csv`` with an empty ``label`` column. The sheet deliberately
   carries **no** matcher predictions, so labelling is blind.
3. Fill ``label`` with ``ran`` or ``not_run`` (blank or ``skip`` = not labelled).
4. ``streetfill evaluate --labels data/labels/labels.csv --match data/match.json``

An edge is *predicted ran* when at least ``ran_threshold`` (default 0.5) of its
checkpoints were visited across all workouts.

* agreement = correct ÷ labelled
* recall = found ÷ labelled ``ran`` (found = labelled ran and predicted ran)
"""

from __future__ import annotations

import csv
import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

from .health import DEFAULT_ACTIVITIES, HealthExport
from .matcher import Matcher
from .matching import DEFAULT_CONFIG, MatchConfig, clean_route

RESULT_SCHEMA = 1
DEFAULT_RAN_THRESHOLD = 0.5
DEFAULT_NEAR_M = 50.0

LABEL_ALIASES = {
    "ran": True,
    "run": True,
    "yes": True,
    "y": True,
    "1": True,
    "not_run": False,
    "not run": False,
    "no": False,
    "n": False,
    "0": False,
}
SKIP_LABELS = {"", "skip", "?", "unsure"}


# --- matching a whole export ------------------------------------------------------

def match_export(
    matcher: Matcher,
    export: HealthExport,
    activities: Iterable[str] = DEFAULT_ACTIVITIES,
    include_indoor: bool = False,
) -> dict:
    """Match every outdoor workout with a route. Returns a JSON-ready result."""
    workouts = []
    union: set[tuple[int, int]] = set()
    for w in export.workouts(activities):
        if w.indoor and not include_indoor:
            continue
        points = export.route_points(w)
        if not points:
            continue
        visited = matcher.match(points)
        union.update(visited)
        workouts.append(
            {
                "start": w.start.isoformat(),
                "activity": w.activity,
                "points": len(points),
                "visited": [list(k) for k in visited],
            }
        )
    cov = matcher.coverage(union)
    return {
        "schema": RESULT_SCHEMA,
        "config": asdict(matcher.cfg),
        "workouts": workouts,
        "edges": {str(eid): [hit, total] for eid, (hit, total) in cov.edges.items()},
        "summary": {
            "workouts": len(workouts),
            "covered_length_m": round(cov.covered_length_m, 1),
            "total_length_m": round(cov.total_length_m, 1),
            "complete_streets": len(cov.complete_streets),
        },
    }


def load_result(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        result = json.load(fh)
    if result.get("schema") != RESULT_SCHEMA:
        raise ValueError(f"{path}: unsupported match result schema {result.get('schema')!r}")
    return result


def predicted_ran(result: dict, threshold: float = DEFAULT_RAN_THRESHOLD) -> dict[int, bool]:
    out = {}
    for eid, (hit, total) in result["edges"].items():
        out[int(eid)] = total > 0 and hit / total >= threshold
    return out


# --- label sheet ------------------------------------------------------------------

def label_sheet(
    matcher: Matcher,
    export: HealthExport,
    out_dir: str | Path,
    *,
    near_m: float = DEFAULT_NEAR_M,
    sample: int | None = None,
    seed: int = 1,
    activities: Iterable[str] = DEFAULT_ACTIVITIES,
    cfg: MatchConfig = DEFAULT_CONFIG,
) -> tuple[Path, Path, int]:
    """Write ``edges.geojson`` and ``labels.csv`` for edges within ``near_m`` of any run."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    proj = matcher.projection

    near: set[int] = set()
    traces = []
    for w in export.workouts(activities):
        if w.indoor:
            continue
        points = export.route_points(w)
        segments = clean_route(points, proj, cfg)
        for seg in segments:
            near |= matcher.edges_near(seg, near_m)
            traces.append((w.start.isoformat(), [proj.to_latlon(p) for p in seg]))

    ids = sorted(near)
    if sample is not None and len(ids) > sample:
        ids = sorted(random.Random(seed).sample(ids, sample))

    edges = matcher.edges
    names = matcher.street_names
    features = []
    for eid in ids:
        e = edges[eid]
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[lon, lat] for lat, lon in e.coords]},
                "properties": {"kind": "edge", "edge_id": eid, "street": names.get(e.street), "highway": e.highway},
            }
        )
    for start, coords in traces:
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[round(lon, 6), round(lat, 6)] for lat, lon in coords]},
                "properties": {"kind": "route", "start": start},
            }
        )
    geojson_path = out_dir / "edges.geojson"
    with open(geojson_path, "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": features}, fh)

    csv_path = out_dir / "labels.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["edge_id", "street", "highway", "length_m", "label"])
        for eid in ids:
            e = edges[eid]
            w.writerow([eid, names.get(e.street) or "", e.highway, f"{matcher.edge_length(eid):.0f}", ""])
    return geojson_path, csv_path, len(ids)


# --- evaluation -------------------------------------------------------------------

def read_labels(path: str | Path) -> dict[int, bool]:
    labels: dict[int, bool] = {}
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None or "edge_id" not in reader.fieldnames or "label" not in reader.fieldnames:
            raise ValueError(f"{path}: needs edge_id and label columns")
        for line, row in enumerate(reader, start=2):
            raw = (row.get("label") or "").strip().lower()
            if raw in SKIP_LABELS:
                continue
            if raw not in LABEL_ALIASES:
                raise ValueError(f"{path}:{line}: unknown label {row['label']!r} (use ran or not_run)")
            labels[int(row["edge_id"])] = LABEL_ALIASES[raw]
    return labels


@dataclass
class Metrics:
    labelled: int = 0
    correct: int = 0
    labelled_ran: int = 0
    found: int = 0
    false_positive: list[int] = field(default_factory=list)  # predicted ran, labelled not_run
    false_negative: list[int] = field(default_factory=list)  # labelled ran, predicted not
    unknown: list[int] = field(default_factory=list)  # labelled edge ids not in the match result

    @property
    def agreement(self) -> float | None:
        return self.correct / self.labelled if self.labelled else None

    @property
    def recall(self) -> float | None:
        return self.found / self.labelled_ran if self.labelled_ran else None

    def report(self, target: float = 0.95) -> str:
        def pct(v):
            return "n/a" if v is None else f"{v:.1%}"

        def verdict(v):
            return "" if v is None else ("  PASS" if v >= target else "  below target")

        lines = [
            f"agreement: {pct(self.agreement)} ({self.correct} correct of {self.labelled} labelled){verdict(self.agreement)}",
            f"recall:    {pct(self.recall)} ({self.found} found of {self.labelled_ran} labelled ran){verdict(self.recall)}",
            f"false positives (credited, not run): {len(self.false_positive)} {self.false_positive[:20]}",
            f"false negatives (run, not credited): {len(self.false_negative)} {self.false_negative[:20]}",
        ]
        if self.unknown:
            lines.append(f"warning: {len(self.unknown)} labelled edges are not in the match result: {self.unknown[:20]}")
        lines.append(f"target: both at least {target:.0%} (plan, Gate 1)")
        return "\n".join(lines)


def evaluate(labels: dict[int, bool], predictions: dict[int, bool]) -> Metrics:
    m = Metrics()
    for eid in sorted(labels):
        truth = labels[eid]
        if eid not in predictions:
            m.unknown.append(eid)
            continue
        pred = predictions[eid]
        m.labelled += 1
        m.correct += pred == truth
        if truth:
            m.labelled_ran += 1
            if pred:
                m.found += 1
            else:
                m.false_negative.append(eid)
        elif pred:
            m.false_positive.append(eid)
    return m
