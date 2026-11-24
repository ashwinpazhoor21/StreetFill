"""Pack highlights placed in a routing graph's projection, for waypoint rewards (6.3) and scoring (6.4)."""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .geo import XY, LocalProjection, point_segment_distance

CELL_M = 150.0


@dataclass(frozen=True)
class HighlightPoint:
    id: int
    name: str
    category: str
    xy: XY


def load_highlights(path: str | Path, projection: LocalProjection) -> list[HighlightPoint]:
    """The pack's highlights, placed in ``projection`` (pass the graph's)."""
    con = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT id, name, category, lat, lon FROM highlights ORDER BY id").fetchall()
    finally:
        con.close()
    return [HighlightPoint(i, name, cat, projection.to_xy((lat, lon))) for i, name, cat, lat, lon in rows]


class HighlightGrid:
    """Highlights in 150 m cells, for finding the ones near a route segment or a node."""


    def __init__(self, highlights: Iterable[HighlightPoint]) -> None:
        self.cells: dict[tuple[int, int], list[HighlightPoint]] = {}
        for h in highlights:
            self.cells.setdefault(self._cell(h.xy), []).append(h)

    @staticmethod
    def _cell(xy: XY) -> tuple[int, int]:
        return math.floor(xy[0] / CELL_M), math.floor(xy[1] / CELL_M)

    def near_segment(self, a: XY, b: XY, within: float) -> Iterable[HighlightPoint]:
        x0, y0 = self._cell((min(a[0], b[0]) - within, min(a[1], b[1]) - within))
        x1, y1 = self._cell((max(a[0], b[0]) + within, max(a[1], b[1]) + within))
        for cx in range(x0, x1 + 1):
            for cy in range(y0, y1 + 1):
                for h in self.cells.get((cx, cy), ()):
                    if point_segment_distance(h.xy, a, b) <= within:
                        yield h

    def count_near(self, xy: XY, within: float) -> int:
        return sum(1 for _ in self.near_segment(xy, xy, within))
