"""Read workouts and workout routes from an Apple Health export.

Works on the ``export.zip`` that the Health app produces or on its unzipped
``apple_health_export`` folder. Files are streamed in place: nothing is
extracted or copied anywhere, because the export holds the owner's location
history.

``export.xml`` is parsed incrementally (it is often hundreds of megabytes, almost
all ``Record`` elements we skip). Each ``Workout`` links its routes through
``WorkoutRoute/FileReference@path``, which points at a GPX file under
``workout-routes/``.
"""

from __future__ import annotations

import posixpath
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import IO, Iterable, Iterator
from xml.etree.ElementTree import iterparse

#: Health activity types we keep, mapped to short names.
ACTIVITY_TYPES = {
    "HKWorkoutActivityTypeRunning": "running",
    "HKWorkoutActivityTypeWalking": "walking",
    "HKWorkoutActivityTypeHiking": "hiking",
}
DEFAULT_ACTIVITIES = frozenset(ACTIVITY_TYPES.values())

DISTANCE_TO_M = {"m": 1.0, "km": 1000.0, "mi": 1609.344, "ft": 0.3048, "yd": 0.9144}
DURATION_TO_S = {"s": 1.0, "min": 60.0, "hr": 3600.0, "h": 3600.0}

DISTANCE_STAT_TYPES = (
    "HKQuantityTypeIdentifierDistanceWalkingRunning",
    "HKQuantityTypeIdentifierDistanceCycling",
)


@dataclass
class Workout:
    activity: str
    start: datetime
    end: datetime
    duration_s: float | None
    distance_m: float | None
    source: str | None
    indoor: bool
    route_paths: list[str] = field(default_factory=list)


def parse_health_date(text: str) -> datetime:
    """Parse Health's ``2024-05-01 07:30:00 -0500`` format (timezone-aware)."""
    return datetime.strptime(text.strip(), "%Y-%m-%d %H:%M:%S %z")


def _to_metres(value: str | None, unit: str | None) -> float | None:
    if value is None or unit not in DISTANCE_TO_M:
        return None
    try:
        return float(value) * DISTANCE_TO_M[unit]
    except ValueError:
        return None


def _to_seconds(value: str | None, unit: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value) * DURATION_TO_S.get(unit or "min", 60.0)
    except ValueError:
        return None


def _safe_relpath(path: str) -> str | None:
    """Normalise a FileReference path to ``workout-routes/x.gpx``; reject escapes."""
    norm = posixpath.normpath("/" + path.replace("\\", "/")).lstrip("/")
    if not norm or norm.startswith("..") or norm == ".":
        return None
    return norm


def _workout_from_element(el) -> Workout | None:
    activity = ACTIVITY_TYPES.get(el.get("workoutActivityType", ""))
    if activity is None:
        return None
    try:
        start = parse_health_date(el.get("startDate", ""))
        end = parse_health_date(el.get("endDate", ""))
    except ValueError:
        return None

    # Older exports put distance on the Workout; newer ones in WorkoutStatistics.
    distance = _to_metres(el.get("totalDistance"), el.get("totalDistanceUnit"))
    indoor = False
    routes: list[str] = []
    for child in el:
        if child.tag == "WorkoutStatistics" and distance is None and child.get("type") in DISTANCE_STAT_TYPES:
            distance = _to_metres(child.get("sum"), child.get("unit"))
        elif child.tag == "MetadataEntry" and child.get("key") == "HKIndoorWorkout":
            indoor = child.get("value", "0").strip() in ("1", "true", "yes")
        elif child.tag == "WorkoutRoute":
            for ref in child.iter("FileReference"):
                rel = _safe_relpath(ref.get("path", ""))
                if rel:
                    routes.append(rel)

    return Workout(
        activity=activity,
        start=start,
        end=end,
        duration_s=_to_seconds(el.get("duration"), el.get("durationUnit")),
        distance_m=distance,
        source=el.get("sourceName"),
        indoor=indoor,
        route_paths=routes,
    )


def iter_workouts(fh: IO[bytes], activities: Iterable[str] = DEFAULT_ACTIVITIES) -> Iterator[Workout]:
    """Stream workouts out of an ``export.xml`` file object."""
    wanted = frozenset(activities)
    depth = 0
    root = None
    for event, el in iterparse(fh, events=("start", "end")):
        if event == "start":
            if root is None:
                root = el
            depth += 1
            continue
        depth -= 1
        if depth == 1:  # finished a direct child of <HealthData>
            if el.tag == "Workout":
                workout = _workout_from_element(el)
                if workout is not None and workout.activity in wanted:
                    yield workout
            root.clear()


class HealthExport:
    """An Apple Health export, read in place from a zip file or a folder."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._zip: zipfile.ZipFile | None = None
        if self.path.is_file():
            self._zip = zipfile.ZipFile(self.path)
            self._prefix = self._find_zip_prefix(self._zip)
        elif self.path.is_dir():
            self._root = self._find_dir_root(self.path)
        else:
            raise FileNotFoundError(f"no Health export at {self.path}")

    # --- locating files -------------------------------------------------

    @staticmethod
    def _find_zip_prefix(zf: zipfile.ZipFile) -> str:
        for name in zf.namelist():
            if posixpath.basename(name) == "export.xml":
                return posixpath.dirname(name)
        raise FileNotFoundError("export.xml not found in the zip")

    @staticmethod
    def _find_dir_root(path: Path) -> Path:
        for candidate in (path, path / "apple_health_export"):
            if (candidate / "export.xml").is_file():
                return candidate
        raise FileNotFoundError(f"export.xml not found under {path}")

    def open(self, relpath: str) -> IO[bytes]:
        """Open a file inside the export, e.g. ``workout-routes/route_1.gpx``."""
        rel = _safe_relpath(relpath)
        if rel is None:
            raise ValueError(f"unsafe path in export: {relpath!r}")
        if self._zip is not None:
            return self._zip.open(posixpath.join(self._prefix, rel) if self._prefix else rel)
        return open(self._root / rel, "rb")

    def has(self, relpath: str) -> bool:
        try:
            with self.open(relpath):
                return True
        except (KeyError, FileNotFoundError, ValueError):
            return False

    # --- reading ---------------------------------------------------------

    def workouts(self, activities: Iterable[str] = DEFAULT_ACTIVITIES) -> Iterator[Workout]:
        with self.open("export.xml") as fh:
            yield from iter_workouts(fh, activities)

    def close(self) -> None:
        if self._zip is not None:
            self._zip.close()

    def __enter__(self) -> "HealthExport":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
