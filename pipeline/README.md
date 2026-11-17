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

## Gate 1: measure matching accuracy

Everything here reads your Health export, so write outputs under `data/` (git-ignored).

```bash
streetfill match       --pack pipeline/out/pack.sqlite --export data/export.zip --out data/match.json
streetfill label-sheet --pack pipeline/out/pack.sqlite --export data/export.zip --out-dir data/labels --sample 150
# open data/labels/edges.geojson in any GeoJSON viewer (it shows the edges and your route traces),
# then fill the label column of data/labels/labels.csv with ran or not_run (leave blank to skip)
streetfill evaluate    --labels data/labels/labels.csv --match data/match.json
streetfill report      --pack pipeline/out/pack.sqlite --match data/match.json --out data/report.html
```

`report` writes one self-contained HTML file (an SVG street map coloured by coverage plus a street table). It loads nothing from the network and draws streets only, not your route traces.

The label sheet carries no matcher predictions, so labelling stays blind. An edge counts as *predicted ran* when at least half its checkpoints were visited (`--ran-threshold`). Agreement = correct ÷ labelled; recall = found ÷ labelled ran. Gate 1 passes at 95% or higher on both (product plan 5.8, section 14).

## Personal data

Apple Health exports contain your location history. Keep them under `data/` at the repository root, which is git-ignored, and never commit them.
