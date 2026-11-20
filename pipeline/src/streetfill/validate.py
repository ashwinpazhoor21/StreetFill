"""Pack validation before publishing (plan 5.7).

``validate_pack`` returns a :class:`Report` of *errors* (block publishing) and
*warnings* (shown, do not block):

* **Integrity:** SQLite ``integrity_check``, the schema version, foreign keys
  (every edge's street and neighborhood exist, every grid row's edge exists),
  meta counts and lengths match the tables, every street's length is the sum
  of its edges, every edge is in the grid.
* **Neighborhoods sum to the city:** neighborhood street lengths plus the
  unassigned length equal the street length (within 0.1% or 1 m).
* **Change against the last published version:** street length, street count
  or edge count changing by more than 3% [Tune] blocks publishing unless
  explicitly allowed. A city's first publish has nothing to compare with, and
  needs the visual check instead (the staged ``preview.html``).
* **Size:** compressed size above the target (10 MB [Tune]) is an error.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from .pack import SCHEMA_VERSION

MAX_CHANGE = 0.03
MAX_COMPRESSED_BYTES = 10 * 1024 * 1024
SUM_TOLERANCE = 0.001
#: Pack statistics compared between versions (and kept in the manifest for that).
STATS = ("street_length_m", "street_count", "edge_count")


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, float] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def text(self) -> str:
        lines = [f"error: {e}" for e in self.errors] + [f"warning: {w}" for w in self.warnings]
        lines.append("validation passed" if self.ok else f"validation failed: {len(self.errors)} error(s)")
        return "\n".join(lines)


def _close(a: float, b: float, rel: float = SUM_TOLERANCE, abs_m: float = 1.0) -> bool:
    return abs(a - b) <= max(abs_m, rel * max(abs(a), abs(b)))


def validate_pack(
    pack: str | Path,
    *,
    previous: Mapping[str, float] | None = None,
    allow_change: bool = False,
    compressed_bytes: int | None = None,
    max_compressed_bytes: int = MAX_COMPRESSED_BYTES,
) -> Report:
    """Check a pack; ``previous`` is the last published version's :data:`STATS`."""
    r = Report()
    try:
        con = sqlite3.connect(Path(pack).resolve().as_uri() + "?mode=ro", uri=True)
        con.execute("SELECT 1 FROM meta LIMIT 1")
    except sqlite3.Error as exc:
        r.errors.append(f"cannot open pack: {exc}")
        return r
    try:
        _check(con, r)
    except sqlite3.Error as exc:
        r.errors.append(f"pack is missing tables or columns: {exc}")
    finally:
        con.close()

    if previous:
        for key in STATS:
            old, new = previous.get(key), r.stats.get(key)
            if not old or new is None:
                continue
            change = (new - old) / old
            if abs(change) > MAX_CHANGE:
                msg = f"{key} changed {change:+.1%} since the last version ({old:g} -> {new:g}); the limit is 3%"
                (r.warnings if allow_change else r.errors).append(msg + (" (allowed)" if allow_change else ""))
    else:
        r.warnings.append("first publish of this city: check preview.html by eye before uploading")

    if compressed_bytes is not None and compressed_bytes > max_compressed_bytes:
        r.errors.append(
            f"compressed pack is {compressed_bytes / 1e6:.1f} MB; the target is {max_compressed_bytes / 1e6:.1f} MB or less"
        )
    return r


def _check(con: sqlite3.Connection, r: Report) -> None:
    ok = con.execute("PRAGMA integrity_check").fetchone()[0]
    if ok != "ok":
        r.errors.append(f"SQLite integrity check failed: {ok}")
    meta = dict(con.execute("SELECT key, value FROM meta"))
    if meta.get("schema_version") != str(SCHEMA_VERSION):
        r.errors.append(f"schema version {meta.get('schema_version')!r}, expected {SCHEMA_VERSION}")

    def count(sql: str) -> int:
        return con.execute(sql).fetchone()[0]

    edges, streets = count("SELECT count(*) FROM edges"), count("SELECT count(*) FROM streets")
    if edges == 0:
        r.errors.append("pack has no edges")
    for key, actual in (("edge_count", edges), ("street_count", streets)):
        if meta.get(key) != str(actual):
            r.errors.append(f"meta {key} is {meta.get(key)!r} but the table has {actual}")
    for what, sql in (
        ("edges with a missing street", "SELECT count(*) FROM edges WHERE street_id NOT IN (SELECT id FROM streets)"),
        ("edges with a missing neighborhood",
         "SELECT count(*) FROM edges WHERE neighborhood_id IS NOT NULL "
         "AND neighborhood_id NOT IN (SELECT id FROM neighborhoods)"),
        ("grid rows for missing edges", "SELECT count(*) FROM grid WHERE edge_id NOT IN (SELECT id FROM edges)"),
        ("edges not in the grid", "SELECT count(*) FROM edges WHERE id NOT IN (SELECT DISTINCT edge_id FROM grid)"),
        ("streets with no edges", "SELECT count(*) FROM streets WHERE id NOT IN (SELECT DISTINCT street_id FROM edges)"),
        ("streets whose length is not the sum of their edges",
         "SELECT count(*) FROM streets s JOIN (SELECT street_id, sum(length_m) AS m FROM edges GROUP BY street_id) e "
         "ON e.street_id = s.id WHERE abs(s.length_m - e.m) > 0.01 + 1e-6 * e.m"),
    ):
        n = count(sql)
        if n:
            r.errors.append(f"{n} {what}")

    street_m = con.execute("SELECT coalesce(sum(length_m), 0) FROM edges WHERE layer = 'street'").fetchone()[0]
    if not _close(street_m, float(meta.get("street_length_m", "nan"))):
        r.errors.append(f"meta street_length_m {meta.get('street_length_m')} but edges sum to {street_m:.2f}")
    hoods = count("SELECT count(*) FROM neighborhoods")
    if hoods:
        hood_m = con.execute("SELECT sum(street_length_m) FROM neighborhoods").fetchone()[0]
        unassigned = float(meta.get("unassigned_street_length_m", 0))
        if not _close(hood_m + unassigned, street_m):
            r.errors.append(
                f"neighborhoods ({hood_m:.1f} m) plus unassigned ({unassigned:.1f} m) do not sum to the city "
                f"street length ({street_m:.1f} m)"
            )
        if street_m and unassigned / street_m > 0.05:
            r.warnings.append(f"{unassigned / street_m:.1%} of street length is in no neighborhood")
    r.stats = {"street_length_m": round(street_m, 2), "street_count": float(streets), "edge_count": float(edges)}
