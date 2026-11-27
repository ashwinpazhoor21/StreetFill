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

Both files are GeoJSON polygons or multipolygons. Edges are cut where they cross a boundary. Pieces outside the city are dropped, and each piece is tagged with the neighborhood that contains it (schema v3: a `neighborhoods` table and `edges.neighborhood_id`). Neighborhood lengths plus the unassigned length add up to the city total, and `build-pack` prints the unassigned share. Check the licence of any neighborhood data before you publish a pack built from it (product plan 5.6). To take the boundaries from OpenStreetMap instead, pass `--osm-boundaries` with a saved Overpass document (`streetfill boundary-query --bbox ...` prints the query), or `--fetch-boundaries` together with `--bbox`. The city is the `admin_level=8` relation containing the centre of the area; use `--admin-level` and `--city-osm-name` to override. Neighborhoods are the polygons inside it of the first kind with at least two members: `place=neighbourhood`, `quarter`, `suburb`, then `admin_level` 10 and 9. `--city` and `--neighborhoods` GeoJSON (official data) take precedence, and OSM fills in only what they leave out. If OSM has no neighborhood polygons there, approximate regions are drawn around named `place=neighbourhood|quarter|suburb` points instead (Voronoi cells, labelled approximate in `neighborhood_source`); `--no-approximate-regions` turns this off.

Per-city settings live in `pipeline/cities/<city>.json`. A config can set any of `name`, `bbox` or `osm_json`, `admin_level`, `osm_name`, `city`, `neighborhoods` (and their id, name and source fields), `osm_boundaries`, `fetch_boundaries` and `approximate_regions`. Options given on the command line win, and relative paths are read relative to the config file:

```bash
streetfill build-pack --city-config pipeline/cities/chicago.json --out pipeline/out/chicago.sqlite
```

### Elevation

`--dem tile.asc [...]` adds an elevation profile to every edge (one sample about every 30 m, bridges interpolated, whole decimetres), plus gain and loss in each direction (schema v4). Tiles are ESRI ASCII grids in lon/lat. See [DATA_SOURCES.md](DATA_SOURCES.md) for preparing USGS 3DEP tiles, and for the licence of every data source.

### Highlights

`--osm-features features.json` (saved from `streetfill feature-query --bbox ...`) or `--fetch-features` with `--bbox` adds a `highlights` table (schema v5). It holds named beaches, parks of 1 ha or more, attractions, viewpoints, artwork, museums, lighthouses, bridges, piers, fountains and historic places inside the city. Each is reduced to a point with a placeholder category (beach, park, landmark, water, historic), a route-matching radius (150 m for beaches and parks, 60 m otherwise) and a score; the best 2,000 are kept (`--max-highlights`). With `--resolve-photos` (and `--photo-cache` so rebuilds don't ask again), each highlight's freely licensed photo and description are looked up on Wikimedia Commons and Wikidata. Only public domain, CC0, CC BY and CC BY-SA photos are kept, with their author and licence; see [DATA_SOURCES.md](DATA_SOURCES.md). The thumbnails are not yet mirrored to a CDN, so `photo_url` stays empty and the app shows the category placeholder. The same document sets **scenery flags** on every edge (schema v6, `edges.scenery`): 1 for water within 100 m, 2 for a beach within 150 m, 4 for a park within 50 m and 8 for a highlight within 75 m. Inside the feature counts too, for example a pier in the lake or a path in a park.

The public Overpass server can be slow or rate-limited. If a download fails, retry later, pass another server with `--overpass-url`, or export the area as Overpass JSON yourself and use `--osm-json`.

## Validate and stage a pack for publishing

```bash
streetfill validate --pack pipeline/out/chicago.sqlite
streetfill stage    --pack pipeline/out/chicago.sqlite --city-id chicago --out-dir pipeline/publish
```

`validate` checks integrity, foreign keys, meta counts and lengths, grid coverage, and that neighborhoods sum to the city. Against the last published version, any change above 3% in street length, street count or edge count blocks publishing unless you pass `--allow-change`. `stage` runs the same checks plus the 10 MB compressed target (`--max-mb`). It then writes `packs/<city>-v<n>.sqlite.gz` (a deterministic gzip), its sha256, an entry in `manifest.json` and `preview/<city>-v<n>.html` for the visual check on a city's first publish (product plan 5.7). If validation fails, nothing is written. `pipeline/publish/` is git-ignored.

```bash
streetfill upload --dir pipeline/publish --dry-run   # check every hash and show the plan
STREETFILL_S3_ENDPOINT=https://... STREETFILL_S3_BUCKET=... AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... \
  streetfill upload --dir pipeline/publish
```

`upload` sends the folder to any S3-compatible store (AWS S3, Cloudflare R2 and others; set `STREETFILL_S3_REGION` if needed). It signs requests with AWS Signature V4 and uses only the standard library. It checks every pack against its sha256 first, then uploads the packs (immutable, cached for a year, skipped if already there) and `manifest.json` last (cached for 5 minutes), so the app never sees a manifest that points at a missing pack. Settings come only from the environment, never from arguments or files in the repository.

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

## Fixtures for the Swift port

```bash
streetfill fixtures   # rewrites pipeline/fixtures/matcher.json and routes.json
```

The Swift matcher must agree with this one on 99.5% or more of checkpoints and must generate checkpoints the same way (product plan 5.3 and 5.4).

`pipeline/fixtures/matcher.json` is self-contained, so the Swift tests need no pack file. It holds:

- the projection origin
- every matching threshold
- the edges with their geometry
- every checkpoint (edge, index, offset, position, bearing)
- 12 synthetic recorded routes, each with the checkpoints this matcher visits

The routes cover a plain run, an out-and-back, inaccurate points, a GPS jump, a long pause, a trail beside a primary road (both ways), a tie between two streets, a corner, points without times, a short edge and a bending road. GPS error is simulated as seeded drift.

`pipeline/fixtures/routes.json` is for the route generator, which must reproduce at least 95% of each route's length on the same seed (plan 6.5). It holds:

- the decoded edge rows of a synthetic pack: a 2.4 km grid with a primary road, footways and steps, a hill, a waterfront, a park and three highlights
- the coverage
- 9 cases (start, distance, shape, preferences, seed), each with the three chosen routes

Each chosen route has its arcs in order (pack edge, from and to positions, length), its score terms and its waypoints. `Graph.from_rows` builds the graph from exactly those rows.

Tests fail when either file no longer matches what the generators produce. After a deliberate matching or routing change, run `streetfill fixtures` and commit the new files with the change.

## Gate 2: generate routes to rate

Routes use your coverage (from `streetfill match`) and start where you run, so write them under `data/` too.

```bash
streetfill routes --pack pipeline/out/pack.sqlite --start 41.90,-87.65 --distance 5mi \
  --coverage data/match.json --newness 0.7 --scenery water,park --terrain rolling --out-dir data/routes/01
```

This writes `preview.html` and `option-1.gpx` to `option-3.gpx`. Each GPX file is one track, which watches and route apps import as a course. The page loads nothing from the network. Each option gets a card with:

- a map with new streets (under 50% covered) marked
- the elevation profile
- distance, gain and new share
- highlights in route order with the mile point
- the score terms

Options:

- `--shape out-and-back` turns at a waypoint about half the distance out.
- `--quiet` prefers quiet streets.
- `--seed` gives a different but repeatable set.
- `--scenery` takes water, beach, park and landmark.
- `--terrain` takes flat, rolling or hilly, or a number from -1 to 1.

Without `--coverage`, every street counts as new.

How routes are built (product plan 6.2–6.4), with every weight still to be tuned in this spike:

1. Each edge costs its length × a factor for terrain, quiet streets, reuse, newness and scenery.
2. 24 candidates go out on different bearings. Their waypoints snap to rewarding nodes, and one can be pulled toward the selected scenery.
3. Each candidate is fitted to the distance.
4. Candidates are scored, and the three best are chosen so that no two share 40% or more of their length.

## Personal data

Apple Health exports contain your location history. Keep them under `data/` at the repository root, which is git-ignored, and never commit them.
