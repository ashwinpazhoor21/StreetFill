import io
import time
from datetime import timedelta

import pytest
from conftest import BASE, build_export

from streetfill.health import HealthExport, _safe_relpath, iter_workouts, parse_health_date


def test_parse_health_date_keeps_timezone():
    dt = parse_health_date("2026-05-01 07:00:00 -0600")
    assert dt == BASE
    assert dt.utcoffset() == timedelta(hours=-6)


@pytest.mark.parametrize("source", ["health_dir", "health_zip"])
def test_reads_running_walking_hiking_only(source, request):
    with HealthExport(request.getfixturevalue(source)) as hx:
        workouts = list(hx.workouts())
    # 10 workouts cycle Running, Walking, Hiking, Cycling, Strength -> i = 0,1,2,5,6,7
    assert [w.activity for w in workouts] == ["running", "walking", "hiking"] * 2
    assert [w.start for w in workouts] == [BASE + timedelta(days=i) for i in (0, 1, 2, 5, 6, 7)]


def test_workout_fields(health_dir):
    with HealthExport(health_dir) as hx:
        by_day = {(w.start - BASE).days: w for w in hx.workouts()}
    legacy, stats = by_day[0], by_day[1]
    assert legacy.distance_m == pytest.approx(5200)
    assert stats.distance_m == pytest.approx(3.1 * 1609.344)
    assert legacy.duration_s == pytest.approx(1800)
    assert legacy.end - legacy.start == timedelta(minutes=30)
    assert legacy.source == "Watch"
    assert legacy.route_paths == []  # i = 0 is a multiple of 7: no route
    assert stats.route_paths == ["workout-routes/route_1.gpx"]
    assert by_day[7].route_paths == []
    assert by_day[5].route_paths == ["workout-routes/route_5.gpx"]


def test_indoor_flag(tmp_path):
    folder = build_export(tmp_path, n_workouts=23)
    with HealthExport(folder) as hx:
        indoor = {(w.start - BASE).days for w in hx.workouts() if w.indoor}
    # i % 9 == 4 is indoor: 4 is strength and 13 cycling (both filtered), 22 is hiking.
    assert indoor == {22}


def test_activity_filter(health_dir):
    with HealthExport(health_dir) as hx:
        assert {w.activity for w in hx.workouts(["running"])} == {"running"}


def test_accepts_parent_folder(health_dir):
    with HealthExport(health_dir.parent) as hx:
        assert len(list(hx.workouts())) == 6


def test_missing_export_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        HealthExport(tmp_path / "nope.zip")
    with pytest.raises(FileNotFoundError):
        HealthExport(tmp_path)


def test_skips_malformed_workouts():
    xml = b"""<HealthData>
    <Workout workoutActivityType="HKWorkoutActivityTypeRunning" startDate="bad" endDate="bad"/>
    <Workout workoutActivityType="HKWorkoutActivityTypeRunning" duration="x"
      startDate="2026-05-01 07:00:00 -0600" endDate="2026-05-01 07:30:00 -0600"/>
    </HealthData>"""
    workouts = list(iter_workouts(io.BytesIO(xml)))
    assert len(workouts) == 1
    assert workouts[0].duration_s is None
    assert workouts[0].distance_m is None


@pytest.mark.parametrize(
    "path, expected",
    [
        ("/workout-routes/route_1.gpx", "workout-routes/route_1.gpx"),
        ("workout-routes/route_1.gpx", "workout-routes/route_1.gpx"),
        ("/../../etc/passwd", "etc/passwd"),
        ("", None),
    ],
)
def test_safe_relpath(path, expected):
    assert _safe_relpath(path) == expected


def test_open_never_leaves_the_export(health_dir):
    with HealthExport(health_dir) as hx:
        assert not hx.has("../outside.txt")
        assert hx.has("export.xml")


def test_1000_workouts_read_quickly(tmp_path):
    folder = build_export(tmp_path, n_workouts=1000, records_per_workout=50)
    start = time.perf_counter()
    with HealthExport(folder) as hx:
        n = sum(1 for _ in hx.workouts())
    elapsed = time.perf_counter() - start
    assert n == 600
    assert elapsed < 10, f"took {elapsed:.1f}s"
