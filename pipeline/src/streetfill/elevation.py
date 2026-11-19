"""Elevation per edge from a public elevation model (plan 6.6).

Input is one or more **ESRI ASCII grids** (``.asc``) in geographic lon/lat
degrees, for example USGS 3DEP 1/3 arc-second tiles converted with
``gdal_translate -of AAIGrid``. Several tiles act as one mosaic: the first tile
with data at a point wins. Reading ASCII keeps the pipeline free of
dependencies; see ``pipeline/DATA_SOURCES.md`` for where the data comes from.

For each edge:

1. **Sample** every ``spacing_m`` (30 m) along the edge, with both ends
   included and the samples spread evenly. Values are bilinear between cell
   centres. Missing samples are filled linearly from their neighbours.
2. **Bridges and piers** (``bridge=*`` other than ``no``, or ``man_made=pier``)
   are interpolated between their end samples, because the elevation model
   shows the water or ground below.
3. **Smooth** the interior with a 3-point moving average. The ends are kept as
   sampled, so every edge meeting at a node agrees on its elevation.
4. **Round** to whole decimetres. That is what the pack stores, and gain and
   loss are summed from the rounded values so Swift can recompute them exactly.

``gain_m`` and ``loss_m`` are for the edge's own direction (``from_node`` to
``to_node``); going the other way, gain and loss swap.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Sequence

from .geo import LatLon, haversine_m
from .network import Edge, Network

SPACING_M = 30.0


@dataclass
class AsciiGrid:
    ncols: int
    nrows: int
    west: float  # lon of the left edge of the first column (cell corner)
    south: float  # lat of the bottom edge of the last row
    cellsize: float  # degrees
    nodata: float | None
    values: list[list[float]]  # rows from north to south

    @classmethod
    def load(cls, path: str | Path) -> "AsciiGrid":
        with open(path, encoding="ascii") as fh:
            header: dict[str, str] = {}
            line = ""
            while True:
                line = fh.readline()
                if not line:
                    break
                parts = line.split()
                if parts and parts[0][0].isalpha():
                    header[parts[0].lower()] = parts[1]
                else:
                    break
            try:
                ncols, nrows, cellsize = int(header["ncols"]), int(header["nrows"]), float(header["cellsize"])
            except KeyError as exc:
                raise ValueError(f"{path}: missing ASCII grid header {exc}") from None
            if "xllcorner" in header:
                west, south = float(header["xllcorner"]), float(header["yllcorner"])
            elif "xllcenter" in header:
                west = float(header["xllcenter"]) - cellsize / 2
                south = float(header["yllcenter"]) - cellsize / 2
            else:
                raise ValueError(f"{path}: needs xllcorner/yllcorner or xllcenter/yllcenter")
            nodata = float(header["nodata_value"]) if "nodata_value" in header else None
            numbers = [float(v) for v in line.split()]
            numbers += [float(v) for v in fh.read().split()]
        if len(numbers) != ncols * nrows:
            raise ValueError(f"{path}: expected {ncols * nrows} values, found {len(numbers)}")
        if not (-180 <= west <= 180 and -90 <= south <= 90 and cellsize < 1):
            raise ValueError(f"{path}: the grid must be in geographic lon/lat degrees")
        values = [numbers[r * ncols : (r + 1) * ncols] for r in range(nrows)]
        return cls(ncols, nrows, west, south, cellsize, nodata, values)

    def _value(self, row: int, col: int) -> float | None:
        if not (0 <= row < self.nrows and 0 <= col < self.ncols):
            return None
        v = self.values[row][col]
        return None if self.nodata is not None and v == self.nodata else v

    def sample(self, lat: float, lon: float) -> float | None:
        """Bilinear elevation between the four nearest cell centres, or None."""
        north = self.south + self.nrows * self.cellsize
        fx = (lon - self.west) / self.cellsize - 0.5
        fy = (north - lat) / self.cellsize - 0.5
        if not (-0.5 <= fx <= self.ncols - 0.5 and -0.5 <= fy <= self.nrows - 0.5):
            return None
        fx = min(max(fx, 0.0), self.ncols - 1.0)  # half a cell at the border: clamp
        fy = min(max(fy, 0.0), self.nrows - 1.0)
        c0, r0 = int(math.floor(fx)), int(math.floor(fy))
        c1, r1 = min(c0 + 1, self.ncols - 1), min(r0 + 1, self.nrows - 1)
        tx, ty = fx - c0, fy - r0
        corners = [
            (self._value(r0, c0), (1 - tx) * (1 - ty)),
            (self._value(r0, c1), tx * (1 - ty)),
            (self._value(r1, c0), (1 - tx) * ty),
            (self._value(r1, c1), tx * ty),
        ]
        got = [(v, w) for v, w in corners if v is not None]
        weight = sum(w for _, w in got)
        if not got or weight <= 1e-12:
            return None
        return sum(v * w for v, w in got) / weight  # renormalise next to nodata cells


class Mosaic:
    """Several grids as one; the first with data at a point wins."""

    def __init__(self, grids: Sequence[AsciiGrid]):
        self.grids = list(grids)

    @classmethod
    def load(cls, paths: Iterable[str | Path]) -> "Mosaic":
        return cls([AsciiGrid.load(p) for p in paths])

    def sample(self, lat: float, lon: float) -> float | None:
        for g in self.grids:
            v = g.sample(lat, lon)
            if v is not None:
                return v
        return None


# --- profiles ---------------------------------------------------------------------

def sample_points(coords: Sequence[LatLon], spacing_m: float = SPACING_M) -> list[LatLon]:
    """Evenly spread points along a polyline, about ``spacing_m`` apart, ends included."""
    seg = [haversine_m(a, b) for a, b in zip(coords, coords[1:])]
    total = sum(seg)
    n = max(1, math.ceil(total / spacing_m - 1e-9))
    out = [coords[0]]
    i, start = 0, 0.0  # current segment and the distance at its start
    for k in range(1, n):
        d = total * k / n
        while i < len(seg) - 1 and start + seg[i] < d:
            start += seg[i]
            i += 1
        t = (d - start) / seg[i] if seg[i] else 0.0
        (a_lat, a_lon), (b_lat, b_lon) = coords[i], coords[i + 1]
        out.append((a_lat + (b_lat - a_lat) * t, a_lon + (b_lon - a_lon) * t))
    out.append(coords[-1])
    return out


def _fill(values: list[float | None]) -> list[float] | None:
    known = [i for i, v in enumerate(values) if v is not None]
    if not known:
        return None
    out = []
    for i, v in enumerate(values):
        if v is not None:
            out.append(v)
            continue
        before = max((k for k in known if k < i), default=None)
        after = min((k for k in known if k > i), default=None)
        if before is None or after is None:
            out.append(values[before if after is None else after])
        else:
            t = (i - before) / (after - before)
            out.append(values[before] + (values[after] - values[before]) * t)
    return out


def edge_profile(coords: Sequence[LatLon], dem, *, flat: bool = False, spacing_m: float = SPACING_M):
    """Elevations (m, whole decimetres) along an edge, or None without data. ``flat`` = bridge."""
    raw = _fill([dem.sample(lat, lon) for lat, lon in sample_points(coords, spacing_m)])
    if raw is None:
        return None
    n = len(raw)
    if flat:
        prof = [raw[0] + (raw[-1] - raw[0]) * k / (n - 1) for k in range(n)]
    else:
        prof = [raw[0]] + [(raw[k - 1] + raw[k] + raw[k + 1]) / 3 for k in range(1, n - 1)] + [raw[-1]]
    return [round(v * 10) / 10 for v in prof]


def gain_loss(profile: Sequence[float]) -> tuple[float, float]:
    """Total climb and descent (m) along ``profile``, in its own direction."""
    gain = loss = 0
    for a, b in zip(profile, profile[1:]):
        d = round(b * 10) - round(a * 10)  # integer decimetres: exact, like the Swift port
        if d > 0:
            gain += d
        else:
            loss -= d
    return gain / 10, loss / 10


def add_elevation(network: Network, dem, spacing_m: float = SPACING_M) -> tuple[Network, int]:
    """Copy of ``network`` with ``Edge.elevation`` set where the model has data; and that count."""
    edges: list[Edge] = []
    covered = 0
    for e in network.edges:
        prof = edge_profile(e.coords, dem, flat=e.bridge, spacing_m=spacing_m)
        covered += prof is not None
        edges.append(replace(e, elevation=prof))
    return Network(streets=network.streets, edges=edges), covered
