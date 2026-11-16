"""Shared test helpers: a synthetic Apple Health export (no real data)."""

from __future__ import annotations

import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

TZ = timezone(timedelta(hours=-6))
BASE = datetime(2026, 5, 1, 7, 0, 0, tzinfo=TZ)

HEADER = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE HealthData [
<!ELEMENT HealthData (ExportDate,Me,(Record|Workout)*)>
]>
<HealthData locale="en_US">
 <ExportDate value="2026-11-01 09:00:00 -0600"/>
 <Me HKCharacteristicTypeIdentifierBiologicalSex="HKBiologicalSexNotSet"/>
"""


def hdate(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S %z")


def record(i: int) -> str:
    t = hdate(BASE + timedelta(minutes=i))
    return (
        f' <Record type="HKQuantityTypeIdentifierStepCount" sourceName="Phone" unit="count" '
        f'creationDate="{t}" startDate="{t}" endDate="{t}" value="{i % 90}"/>\n'
    )


def workout_xml(i: int, activity: str, *, route: str | None, legacy_distance: bool, indoor: bool) -> str:
    start = BASE + timedelta(days=i)
    end = start + timedelta(minutes=30)
    attrs = (
        f'workoutActivityType="HKWorkoutActivityType{activity}" duration="30" durationUnit="min" '
        f'sourceName="Watch" creationDate="{hdate(end)}" startDate="{hdate(start)}" endDate="{hdate(end)}"'
    )
    if legacy_distance:
        attrs += ' totalDistance="5.2" totalDistanceUnit="km"'
    parts = [f" <Workout {attrs}>\n"]
    parts.append(f'  <MetadataEntry key="HKIndoorWorkout" value="{1 if indoor else 0}"/>\n')
    if not legacy_distance:
        parts.append(
            f'  <WorkoutStatistics type="HKQuantityTypeIdentifierDistanceWalkingRunning" '
            f'startDate="{hdate(start)}" endDate="{hdate(end)}" sum="3.1" unit="mi"/>\n'
        )
    if route:
        parts.append(
            f'  <WorkoutRoute sourceName="Watch" startDate="{hdate(start)}" endDate="{hdate(end)}">\n'
            f'   <MetadataEntry key="HKMetadataKeySyncVersion" value="2"/>\n'
            f'   <FileReference path="/workout-routes/{route}"/>\n'
            f"  </WorkoutRoute>\n"
        )
    parts.append(" </Workout>\n")
    return "".join(parts)


def gpx_xml(start: datetime, n_points: int = 5) -> str:
    pts = []
    for k in range(n_points):
        t = (start + timedelta(seconds=k)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        pts.append(
            f'<trkpt lon="{-87.65 + k * 0.00003:.6f}" lat="{41.9:.6f}"><ele>180.{k}</ele><time>{t}</time>'
            f"<extensions><speed>2.9</speed><course>90.0</course><hAcc>{3 + k}.5</hAcc><vAcc>2.0</vAcc>"
            f"</extensions></trkpt>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="Apple Health Export" xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><name>Route</name><trkseg>{''.join(pts)}</trkseg></trk></gpx>\n"
    )


ACTIVITIES = ["Running", "Walking", "Hiking", "Cycling", "TraditionalStrengthTraining"]


def build_export(root: Path, n_workouts: int = 10, records_per_workout: int = 3) -> Path:
    """Write ``root/apple_health_export/`` and return that folder.

    Workout i has activity ACTIVITIES[i % 5]; every running/walking/hiking workout
    except multiples of 7 has a route; even i use the legacy distance attribute;
    i % 9 == 4 is indoor.
    """
    folder = root / "apple_health_export"
    (folder / "workout-routes").mkdir(parents=True)
    rec = 0
    with open(folder / "export.xml", "w", encoding="utf-8") as fh:
        fh.write(HEADER)
        for i in range(n_workouts):
            for _ in range(records_per_workout):
                fh.write(record(rec))
                rec += 1
            activity = ACTIVITIES[i % len(ACTIVITIES)]
            route = None
            if activity in ("Running", "Walking", "Hiking") and i % 7 != 0:
                route = f"route_{i}.gpx"
                (folder / "workout-routes" / route).write_text(gpx_xml(BASE + timedelta(days=i)))
            fh.write(workout_xml(i, activity, route=route, legacy_distance=i % 2 == 0, indoor=i % 9 == 4))
        fh.write("</HealthData>\n")
    return folder


def zip_export(folder: Path, out: Path) -> Path:
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(folder.rglob("*")):
            if p.is_file():
                zf.write(p, Path("apple_health_export") / p.relative_to(folder))
    return out


@pytest.fixture()
def health_dir(tmp_path):
    return build_export(tmp_path)


@pytest.fixture()
def health_zip(tmp_path):
    folder = build_export(tmp_path / "src")
    return zip_export(folder, tmp_path / "export.zip")
