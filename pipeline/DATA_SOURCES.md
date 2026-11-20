# Data sources

Each source a street pack is built from, with its licence and how to get it. Claims marked **[Unverified]** have not yet been checked against the provider's own terms. They are part of the week-1 licence checks (product plan, week 1; issue #13). Check them before publishing a pack.

| Data | Source | Licence | Stored in the pack as |
|---|---|---|---|
| Streets, paths, bridges, boundaries, place points, highlights | OpenStreetMap via the Overpass API | ODbL 1.0; attribution "© OpenStreetMap contributors" | `meta.source`, `meta.attribution` |
| Neighborhoods (optional) | Official open data, for example a city's portal | Varies by city **[Unverified per city]**. Do not publish until it is checked; Chicago's community areas are not used yet. | `meta.neighborhood_source` |
| Elevation, US | USGS 3D Elevation Program (3DEP), 1/3 arc-second DEM | Public domain **[Unverified]** | `meta.elevation_source` |
| Elevation, elsewhere | Copernicus GLO-30 DEM | **[Unverified licence]**; not used yet | `meta.elevation_source` |

## Elevation: preparing 3DEP tiles

The pipeline reads elevation from ESRI ASCII grids (`.asc`) in geographic lon/lat degrees. This avoids needing a GeoTIFF reader. 3DEP 1/3 arc-second tiles are 1° × 1° GeoTIFFs in geographic NAD83, available from The National Map downloader. Convert and crop a tile to the city with GDAL:

```bash
# one tile (named after its north-west corner), cropped to the Chicago bbox: -projwin west north east south
gdal_translate -of AAIGrid -projwin -87.94 42.023 -87.524 41.644 USGS_13_n42w088.tif data/dem/n42w088.asc
gdal_translate -of AAIGrid -projwin -87.94 42.023 -87.524 41.644 USGS_13_n43w088.tif data/dem/n43w088.asc

streetfill build-pack --city-config pipeline/cities/chicago.json --dem data/dem/*.asc --out pipeline/out/chicago.sqlite
```

Several tiles act as one mosaic: at each point, the first tile with data wins. A cropped city tile has about 18 million cells, which takes roughly 150 MB of memory to load. The NAD83 and WGS84 datums differ by about a metre, which is far below the 30 m sample spacing. Keep DEM files out of git; `data/` is ignored.

## Elevation: how it is used

Each edge is sampled evenly, about every 30 m with both ends included. Bridges and piers are interpolated between their ends, because the model shows the water or ground below. The interior is lightly smoothed, and the profile is stored as whole decimetres, with gain and loss in the edge's direction (product plan 6.6). The details are in `src/streetfill/elevation.py`.
