# StreetFill pipeline

Python reference implementation for StreetFill's street packs and street matching. The iOS app's Swift code is ported from this, and shared fixtures keep the two in agreement (product plan, section 5.4).

Standard library only, Python 3.11+.

## Setup

```bash
cd pipeline
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest
```

## Build a street pack

```bash
# download from the Overpass API (south,west,north,east) and keep a copy of the raw data
streetfill build-pack --bbox 41.905,-87.665,41.932,-87.629 --out pipeline/out/pack.sqlite --save-osm pipeline/out/area.json

# rebuild later from the saved file, without the network
streetfill build-pack --osm-json pipeline/out/area.json --out pipeline/out/pack.sqlite
```

The pack format (schema v1: `meta`, `streets`, `edges`, `grid`) is documented at the top of `src/streetfill/pack.py`. Packs carry OpenStreetMap data, © OpenStreetMap contributors, under the ODbL. `pipeline/out/` is git-ignored.

The public Overpass server can be slow or rate-limited. If a download fails, retry later, pass another server with `--overpass-url`, or export the area as Overpass JSON yourself and use `--osm-json`.

## Personal data

Apple Health exports contain your location history. Keep them under `data/` at the repository root, which is git-ignored, and never commit them.
