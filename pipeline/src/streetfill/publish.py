"""Stage a validated pack for publishing: gzip, sha256 and ``manifest.json`` (plan 5.3).

``stage_pack`` writes into a publish folder (git-ignored, for example
``pipeline/publish/``):

* ``packs/<city>-v<version>.sqlite.gz``: the pack, gzip-compressed
  deterministically (no file name or time in the gzip header), so the same
  pack always gives the same bytes and hash;
* ``manifest.json``: every city's current pack, which the app reads to detect
  the home city and to download packs;
* ``preview/<city>-v<version>.html``: the coverage report with nothing covered,
  for the visual check on a city's first publish (plan 5.7).

The manifest (``schema`` 1)::

    {"schema": 1, "updated_at": "...", "cities": [
      {"id": "chicago", "name": "Chicago", "version": 3, "pack_schema": 7,
       "path": "packs/chicago-v3.sqlite.gz", "sha256": "...", "bytes": 4100000,
       "uncompressed_bytes": 15000000, "built_at": "...", "bbox": [s, w, n, e],
       "street_length_m": ..., "street_count": ..., "edge_count": ...,
       "attribution": "© OpenStreetMap contributors"}]}

``path`` is relative to the manifest, so the folder can be uploaded as-is
behind any CDN. The statistics are kept so the next version can be compared
with this one (3% rule) without the old pack.

Validation runs first, and nothing is written when it fails.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .validate import MAX_COMPRESSED_BYTES, STATS, Report, validate_pack

MANIFEST_SCHEMA = 1
CITY_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


class PublishError(Exception):
    def __init__(self, report: Report):
        super().__init__(report.text())
        self.report = report


def load_manifest(path: str | Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {"schema": MANIFEST_SCHEMA, "cities": []}
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("schema") != MANIFEST_SCHEMA:
        raise ValueError(f"{path}: unsupported manifest schema {doc.get('schema')!r}")
    return doc


def gzip_file(src: Path, dst: Path) -> None:
    with open(src, "rb") as fin, open(dst, "wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=9) as gz:
            shutil.copyfileobj(fin, gz, 1 << 20)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stage_pack(
    pack: str | Path,
    city_id: str,
    out_dir: str | Path,
    *,
    name: str | None = None,
    allow_change: bool = False,
    max_compressed_bytes: int = MAX_COMPRESSED_BYTES,
) -> tuple[dict, Report]:
    """Validate ``pack`` and add it to ``out_dir/manifest.json``. Raises :class:`PublishError` on errors."""
    if not CITY_ID.match(city_id):
        raise ValueError("city id must be lowercase letters, digits and hyphens, for example 'chicago'")
    pack, out = Path(pack), Path(out_dir)
    (out / "packs").mkdir(parents=True, exist_ok=True)
    manifest_path = out / "manifest.json"
    manifest = load_manifest(manifest_path)
    previous = next((c for c in manifest["cities"] if c["id"] == city_id), None)
    version = (previous["version"] + 1) if previous else 1

    tmp_gz = out / "packs" / f".{city_id}.sqlite.gz.tmp"
    gzip_file(pack, tmp_gz)
    size = tmp_gz.stat().st_size
    report = validate_pack(
        pack,
        previous={k: previous[k] for k in STATS if k in previous} if previous else None,
        allow_change=allow_change,
        compressed_bytes=size,
        max_compressed_bytes=max_compressed_bytes,
    )
    if not report.ok:
        tmp_gz.unlink()
        raise PublishError(report)

    rel = f"packs/{city_id}-v{version}.sqlite.gz"
    os.replace(tmp_gz, out / rel)
    con = sqlite3.connect(pack.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        meta = dict(con.execute("SELECT key, value FROM meta"))
    finally:
        con.close()

    from .report import write_report

    (out / "preview").mkdir(exist_ok=True)
    preview = f"preview/{city_id}-v{version}.html"
    write_report(pack, {"edges": {}, "summary": {"workouts": 0}}, out / preview)

    entry = {
        "id": city_id,
        "name": name or meta.get("city_name") or city_id.replace("-", " ").title(),
        "version": version,
        "pack_schema": int(meta["schema_version"]),
        "path": rel,
        "sha256": sha256_file(out / rel),
        "bytes": size,
        "uncompressed_bytes": pack.stat().st_size,
        "built_at": meta.get("built_at"),
        "bbox": [float(v) for v in meta["bbox"].split(",")],
        **{k: report.stats[k] for k in STATS},
        "attribution": meta.get("attribution", "© OpenStreetMap contributors"),
        "preview": preview,
    }
    for k in ("street_count", "edge_count"):
        entry[k] = int(entry[k])
    manifest["cities"] = sorted([c for c in manifest["cities"] if c["id"] != city_id] + [entry], key=lambda c: c["id"])
    manifest["updated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    tmp = manifest_path.with_name("manifest.json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, manifest_path)
    return entry, report
