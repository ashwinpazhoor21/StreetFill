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

The pack format (schema v2: `meta`, `streets`, `edges`, `grid`, each street and edge tagged with a `layer`) is documented at the top of `src/streetfill/pack.py`. Layers follow product plan 5.2: `street` counts toward the street percentage; `path` (footways other than sidewalks and crossings, paths, cycleways, tracks, bridleways with foot access) counts toward Paths & trails, and named paths become trails; `steps` is routable only. Packs carry OpenStreetMap data, © OpenStreetMap contributors, under the ODbL. `pipeline/out/` is git-ignored.

### City boundary and neighborhoods

```bash
streetfill build-pack --osm-json pipeline/out/area.json --out pipeline/out/pack.sqlite \
  --city pipeline/out/city.geojson --city-source "OpenStreetMap" \
  --neighborhoods pipeline/out/areas.geojson --neighborhood-id-property id --neighborhood-name-property name \
  --neighborhood-source "City open data portal"
```

Both files are GeoJSON polygons or multipolygons. Edges are cut where they cross a boundary. Pieces outside the city are dropped, and each piece is tagged with the neighborhood that contains it (schema v3: a `neighborhoods` table and `edges.neighborhood_id`). Neighborhood lengths plus the unassigned length add up to the city total, and `build-pack` prints the unassigned share. Check the licence of any neighborhood data before you publish a pack built from it (product plan 5.6). To take the boundaries from OpenStreetMap instead, pass `--osm-boundaries` with a saved Overpass document (`streetfill boundary-query --bbox ...` prints the query), or `--fetch-boundaries` together with `--bbox`. The city is the `admin_level=8` relation containing the centre of the area; use `--admin-level` and `--city-osm-name` to override. Neighborhoods are the polygons inside it of the first kind with at least two members: `place=neighbourhood`, `quarter`, `suburb`, then `admin_level` 10 and 9. `--city` and `--neighborhoods` GeoJSON (official data) take precedence, and OSM fills in only what they leave out.

The public Overpass server can be slow or rate-limited. If a download fails, retry later, pass another server with `--overpass-url`, or export the area as Overpass JSON yourself and use `--osm-json`.

## Gate 1: measure matching accuracy

Everything here reads your Health export, so write outputs under `data/` (git-ignored).

```bash
streetfill match       --pack pipeline/out/pack.sqlite --export data/export.zip --out data/match.json
streetfill label-sheet --pack pipeline/out/pack.sqlite --export data/export.zip --out-dir data/labels --sample 150 --path-sample 20
# open data/labels/edges.geojson in any GeoJSON viewer (it shows the edges and your route traces),
# then fill the label column of data/labels/labels.csv with ran or not_run (leave blank to skip)
streetfill evaluate    --labels data/labels/labels.csv --match data/match.json
streetfill report      --pack pipeline/out/pack.sqlite --match data/match.json --out data/report.html
```

`report` writes one self-contained HTML file: an SVG map coloured by coverage (paths and trails dashed, on top of streets), a street table and a trail table. The street percentage counts streets only; paths and trails have their own totals. It loads nothing from the network and does not draw your route traces.

The label sheet carries no matcher predictions, so labelling stays blind. An edge counts as *predicted ran* when at least half its checkpoints were visited (`--ran-threshold`). Agreement = correct ÷ labelled; recall = found ÷ labelled ran. Gate 1 passes at 95% or higher on both (product plan 5.8, section 14). Streets and paths are scored separately: the sheet has a `layer` column, `--sample` and `--path-sample` sample each layer on its own, and `evaluate` prints a street section (the gate) and a paths section (reported only).

## Personal data

Apple Health exports contain your location history. Keep them under `data/` at the repository root, which is git-ignored, and never commit them.
