"""Command-line entry point: ``streetfill <command>``."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="streetfill", description=__doc__)
    parser.add_argument("--version", action="version", version=f"streetfill {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    bp = sub.add_parser("build-pack", help="build a SQLite street pack from OpenStreetMap")
    src = bp.add_mutually_exclusive_group()
    src.add_argument("--bbox", help="download from Overpass: south,west,north,east")
    src.add_argument("--osm-json", metavar="PATH", help="use a saved Overpass JSON file")
    bp.add_argument("--out", required=True, help="output .sqlite path")
    bp.add_argument("--city-config", metavar="JSON",
                    help="per-city settings (see pipeline/cities/); options given on the command line win")
    bp.add_argument("--save-osm", metavar="PATH", help="also save the downloaded Overpass JSON")
    bp.add_argument("--overpass-url", default=None, help="Overpass interpreter URL")
    bp.add_argument("--city", metavar="GEOJSON", help="clip to this city boundary (all features' polygons)")
    bp.add_argument("--city-name", help="city name (default: the first feature's name property)")
    bp.add_argument("--city-source", help="where the city boundary comes from, for attribution")
    bp.add_argument("--neighborhoods", metavar="GEOJSON", help="split edges by these neighborhood polygons")
    bp.add_argument("--neighborhood-id-property", help="feature property holding the id (default id)")
    bp.add_argument("--neighborhood-name-property", help="feature property holding the name (default name)")
    bp.add_argument("--neighborhood-source", help="where the neighborhoods come from, for attribution")
    osm_b = bp.add_mutually_exclusive_group()
    osm_b.add_argument("--osm-boundaries", metavar="PATH",
                       help="saved Overpass JSON of boundaries (see boundary-query); fills in a missing --city "
                            "or --neighborhoods from OpenStreetMap")
    osm_b.add_argument("--fetch-boundaries", action="store_true", help="with --bbox: download the boundaries too")
    bp.add_argument("--save-boundaries", metavar="PATH", help="also save the downloaded boundary JSON")
    bp.add_argument("--admin-level", help="OSM admin_level of the city boundary (default 8)")
    bp.add_argument("--city-osm-name", help="pick the OSM city boundary by name (default: the one containing "
                                            "the centre of the area)")
    bp.add_argument("--no-approximate-regions", dest="approximate_regions", action="store_false", default=None,
                    help="without OSM neighborhood polygons, leave the pack without neighborhoods instead of "
                         "making approximate regions around place points")

    bp.add_argument("--dem", nargs="+", metavar="ASC",
                    help="elevation model tiles as ESRI ASCII grids in lon/lat (see pipeline/DATA_SOURCES.md)")
    bp.add_argument("--dem-source", help="elevation data source, for attribution "
                                         "(default: USGS 3DEP 1/3 arc-second DEM)")

    feat = bp.add_mutually_exclusive_group()
    feat.add_argument("--osm-features", metavar="PATH",
                      help="saved Overpass JSON of highlight candidates and scenery (see feature-query)")
    feat.add_argument("--fetch-features", action="store_true", help="with --bbox: download highlight candidates too")
    bp.add_argument("--save-features", metavar="PATH", help="also save the downloaded feature JSON")
    bp.add_argument("--max-highlights", type=int, help="keep this many highlights, best first (default 2000)")
    bp.add_argument("--resolve-photos", action="store_true",
                    help="look up freely licensed photos and descriptions on Wikidata and Wikimedia Commons")
    bp.add_argument("--photo-cache", metavar="PATH", help="JSON cache for those lookups, reused on rebuilds")

    fq = sub.add_parser("feature-query", help="print the Overpass query for highlight candidates and scenery")
    fq.add_argument("--bbox", required=True, help="south,west,north,east")

    bq = sub.add_parser("boundary-query", help="print the Overpass query for city and neighborhood boundaries")
    bq.add_argument("--bbox", required=True, help="south,west,north,east")

    mp = sub.add_parser("match", help="match every run in a Health export against a pack")
    mp.add_argument("--pack", required=True)
    mp.add_argument("--export", required=True, help="export.zip or the unzipped folder")
    mp.add_argument("--out", required=True, help="match result .json (keep it under data/)")

    lp = sub.add_parser("label-sheet", help="write edges near your runs for hand labelling")
    lp.add_argument("--pack", required=True)
    lp.add_argument("--export", required=True)
    lp.add_argument("--out-dir", required=True, help="folder for edges.geojson and labels.csv")
    lp.add_argument("--near-m", type=float, default=50.0, help="include edges this close to a run")
    lp.add_argument("--sample", type=int, default=None, help="label a random sample of this many street edges")
    lp.add_argument("--path-sample", type=int, default=None, help="and this many path edges (plan: about 20)")
    lp.add_argument("--seed", type=int, default=1)

    ep = sub.add_parser("evaluate", help="agreement and recall of a match result against labels")
    ep.add_argument("--labels", required=True, help="filled-in labels.csv")
    ep.add_argument("--match", required=True, help="match result .json")
    ep.add_argument("--ran-threshold", type=float, default=0.5,
                    help="fraction of an edge's checkpoints needed to predict 'ran'")

    rp = sub.add_parser("report", help="self-contained HTML map of covered and uncovered streets and paths")
    rp.add_argument("--pack", required=True)
    rp.add_argument("--match", required=True, help="match result .json")
    rp.add_argument("--out", required=True, help="output .html")
    rp.add_argument("--ran-threshold", type=float, default=0.5)
    return parser


PRIVACY_NOTE = "note: this output contains your location history; keep it under data/ (git-ignored)"


def cmd_match(args: argparse.Namespace) -> int:
    from .evaluation import match_export
    from .health import HealthExport
    from .matcher import Matcher

    matcher = Matcher.from_pack(args.pack)
    with HealthExport(args.export) as hx:
        result = match_export(matcher, hx)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(result, fh)
    s = result["summary"]
    km, total = s["covered_length_m"] / 1000, s["total_length_m"] / 1000
    print(f"matched {s['workouts']} workouts: {km:.1f} of {total:.1f} km covered, "
          f"{s['complete_streets']} streets complete; paths {s['path_covered_m'] / 1000:.1f} of "
          f"{s['path_length_m'] / 1000:.1f} km, {s['complete_trails']} trails complete -> {args.out}")
    print(PRIVACY_NOTE, file=sys.stderr)
    return 0


def cmd_label_sheet(args: argparse.Namespace) -> int:
    from .evaluation import label_sheet
    from .health import HealthExport
    from .matcher import Matcher

    matcher = Matcher.from_pack(args.pack)
    with HealthExport(args.export) as hx:
        geojson, csv_path, n = label_sheet(
            matcher, hx, args.out_dir, near_m=args.near_m, sample=args.sample,
            path_sample=args.path_sample, seed=args.seed,
        )
    print(f"{n} edges to label: fill the label column of {csv_path} with ran or not_run")
    print(f"map for reference: {geojson} (edges and your route traces)")
    print(PRIVACY_NOTE, file=sys.stderr)
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    from .evaluation import edge_layers, evaluate_layers, layered_report, load_result, predicted_ran, read_labels

    try:
        labels = read_labels(args.labels)
        result = load_result(args.match)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    metrics = evaluate_layers(labels, predicted_ran(result, args.ran_threshold), edge_layers(result))
    print(layered_report(metrics))
    return 0


def cmd_build_pack(args: argparse.Namespace) -> int:
    from . import overpass
    from .boundaries import assign_areas
    from .network import build_network
    from .osm import load_overpass_file, parse_overpass
    from .pack import write_pack

    start = time.perf_counter()
    try:
        apply_city_config(args)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not args.bbox and not args.osm_json:
        print("error: give --bbox or --osm-json (or a bbox in --city-config)", file=sys.stderr)
        return 2
    try:
        city, hoods = _load_boundaries(args)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    bbox = None
    if args.bbox:
        try:
            bbox = overpass.parse_bbox(args.bbox)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        try:
            doc = overpass.fetch(bbox, url=args.overpass_url or overpass.DEFAULT_URL)
        except (OSError, ValueError) as exc:  # URLError, timeouts, bad JSON
            print(f"error: Overpass request failed: {exc}", file=sys.stderr)
            print("hint: retry later, try another --overpass-url, or use --osm-json", file=sys.stderr)
            return 1
        if args.save_osm:
            with open(args.save_osm, "w", encoding="utf-8") as fh:
                json.dump(doc, fh)
        data = parse_overpass(doc)
        source = "OpenStreetMap via Overpass API"
    else:
        data = load_overpass_file(args.osm_json)
        source = "OpenStreetMap (saved Overpass JSON)"

    city_source, hood_source = args.city_source, args.neighborhood_source
    if args.osm_boundaries or args.fetch_boundaries:
        try:
            doc = _boundary_doc(args, bbox)
        except (OSError, ValueError) as exc:
            print(f"error: boundaries: {exc}", file=sys.stderr)
            return 1 if args.fetch_boundaries else 2
        city, hoods, city_source, hood_source = _osm_boundaries(
            args, doc, data, bbox, city, hoods, city_source, hood_source
        )

    network = build_network(data)
    if network.edges and (city or hoods):
        network = assign_areas(network, city=city, neighborhoods=hoods)
    if not network.edges:
        where = " inside the city boundary" if city else ""
        print(f"error: no runnable streets found in the input{where}", file=sys.stderr)
        return 1
    elevation_note = None
    if args.dem:
        from .elevation import Mosaic, add_elevation

        try:
            dem = Mosaic.load(args.dem)
        except (OSError, ValueError) as exc:
            print(f"error: elevation: {exc}", file=sys.stderr)
            return 2
        network, covered = add_elevation(network, dem)  # after clipping, so pieces get their own profile
        elevation_note = f"elevation for {covered} of {len(network.edges)} edges"
        if covered < len(network.edges):
            elevation_note += " (the rest are outside the elevation tiles)"
    highlights = []
    if args.osm_features or args.fetch_features:
        from .highlights import extract

        try:
            fdoc = _feature_doc(args, bbox)
        except (OSError, ValueError) as exc:
            print(f"error: features: {exc}", file=sys.stderr)
            return 1 if args.fetch_features else 2
        highlights = extract(fdoc, city=city, limit=args.max_highlights)
        if args.resolve_photos and highlights:
            from .photos import CachedFetch, http_fetch_json, resolve_photos

            fetch = CachedFetch(http_fetch_json, args.photo_cache, pause_s=1.0)
            try:
                highlights = resolve_photos(highlights, fetch)
            except (OSError, ValueError) as exc:
                print(f"error: photo lookup failed: {exc}", file=sys.stderr)
                return 1
            finally:
                fetch.save()
        from .scenery import add_scenery, scenery_features

        polygons, coast = scenery_features(fdoc)
        network = add_scenery(network, polygons, coast, [h.point for h in highlights])
    meta = write_pack(
        network,
        args.out,
        bbox=bbox,
        source=source,
        city=city,
        city_source=city_source,
        neighborhoods=hoods,
        neighborhood_source=hood_source,
        elevation_source=args.dem_source,
        highlights=highlights,
        highlight_source="OpenStreetMap",
    )
    elapsed = time.perf_counter() - start
    layers = {}
    for st in network.streets:
        layers[st.layer] = layers.get(st.layer, 0) + 1
    street_km = float(meta["street_length_m"]) / 1000
    path_km = float(meta["path_length_m"]) / 1000
    print(
        f"wrote {args.out}: {layers.get('street', 0)} streets ({street_km:.1f} km), "
        f"{layers.get('path', 0)} paths and trails ({path_km:.1f} km), "
        f"{meta['edge_count']} edges in {elapsed:.1f}s"
    )
    if city:
        print(f"clipped to {city.name}")
    if elevation_note:
        print(elevation_note)
    if args.osm_features or args.fetch_features:
        by_cat: dict[str, int] = {}
        for h in highlights:
            by_cat[h.category] = by_cat.get(h.category, 0) + 1
        detail = ", ".join(f"{n} {c}" for c, n in sorted(by_cat.items())) or "none found"
        if args.resolve_photos:
            photos = sum(1 for h in highlights if h.photo)
            print(f"{len(highlights)} highlights ({detail}); {photos} with a freely licensed photo "
                  "(not mirrored to a CDN yet, so the app still shows placeholders)")
        else:
            print(f"{len(highlights)} highlights ({detail}); photos not resolved yet, placeholders used")
        from .scenery import NAMES

        counts = ", ".join(
            f"{sum(1 for e in network.edges if e.scenery & bit)} {name}" for bit, name in NAMES.items()
        )
        print(f"scenery flags: {meta['scenery_edges']} of {meta['edge_count']} edges ({counts})")
    if hoods:
        street_m = float(meta["street_length_m"])
        none = float(meta["unassigned_street_length_m"]) / street_m if street_m else 0.0
        print(f"{len(hoods)} neighborhoods; {none:.1%} of street length is in none of them")
    return 0


#: Keys a --city-config file may set, and the build-pack option each one fills in.
CITY_CONFIG_KEYS = {
    "name": "city_name",
    "bbox": "bbox",
    "osm_json": "osm_json",
    "admin_level": "admin_level",
    "osm_name": "city_osm_name",
    "city": "city",
    "city_source": "city_source",
    "neighborhoods": "neighborhoods",
    "neighborhood_id_property": "neighborhood_id_property",
    "neighborhood_name_property": "neighborhood_name_property",
    "neighborhood_source": "neighborhood_source",
    "osm_boundaries": "osm_boundaries",
    "fetch_boundaries": "fetch_boundaries",
    "approximate_regions": "approximate_regions",
    "dem": "dem",
    "dem_source": "dem_source",
    "osm_features": "osm_features",
    "fetch_features": "fetch_features",
    "max_highlights": "max_highlights",
    "resolve_photos": "resolve_photos",
    "photo_cache": "photo_cache",
}
PATH_KEYS = {"osm_json", "city", "neighborhoods", "osm_boundaries", "dem", "osm_features", "photo_cache"}
BUILD_DEFAULTS = {
    "admin_level": "8",
    "neighborhood_id_property": "id",
    "neighborhood_name_property": "name",
    "city_source": "",
    "neighborhood_source": "",
    "approximate_regions": True,
    "dem_source": "USGS 3DEP 1/3 arc-second DEM",
    "max_highlights": 2000,
}


def apply_city_config(args: argparse.Namespace) -> None:
    """Fill options the command line left unset from ``--city-config``, then apply defaults.

    Relative paths in the config are relative to the config file.
    """
    if getattr(args, "city_config", None):
        path = Path(args.city_config)
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
        if not isinstance(cfg, dict):
            raise ValueError(f"{path}: expected a JSON object")
        unknown = sorted(set(cfg) - CITY_CONFIG_KEYS.keys() - {"comment"})
        if "bbox" in cfg and "osm_json" in cfg:
            raise ValueError(f"{path}: give bbox or osm_json, not both")
        if unknown:
            raise ValueError(f"{path}: unknown keys {unknown}")
        for key, attr in CITY_CONFIG_KEYS.items():
            if key not in cfg or getattr(args, attr, None) not in (None, False):
                continue
            value = cfg[key]
            if key == "bbox" and isinstance(value, list):
                value = ",".join(str(v) for v in value)
            if key in PATH_KEYS:
                if key == "dem":
                    value = [str((path.parent / v).resolve()) for v in ([value] if isinstance(value, str) else value)]
                else:
                    value = str((path.parent / value).resolve())
            if key in ("bbox", "osm_json") and (args.bbox or args.osm_json):
                continue  # the command line already chose the source
            if key in ("osm_boundaries", "fetch_boundaries") and (args.osm_boundaries or args.fetch_boundaries):
                continue  # likewise for the boundary source
            if key in ("osm_features", "fetch_features") and (args.osm_features or args.fetch_features):
                continue  # and for highlight features
            setattr(args, attr, value)
    for attr, default in BUILD_DEFAULTS.items():
        if getattr(args, attr, None) is None:
            setattr(args, attr, default)


def _load_boundaries(args: argparse.Namespace):
    from dataclasses import replace

    from .boundaries import load_areas

    city = None
    if args.city:
        parts = load_areas(args.city)
        rings = tuple(r for a in parts for r in a.rings)
        first = parts[0]
        named = first.name != first.id  # load_areas falls back to the id when there is no name
        city = replace(first, name=args.city_name or (first.name if named else "City"), rings=rings)
    hoods = []
    if args.neighborhoods:
        hoods = load_areas(args.neighborhoods, args.neighborhood_id_property, args.neighborhood_name_property)
    return city, hoods


def _boundary_doc(args: argparse.Namespace, bbox):
    from . import overpass

    if args.osm_boundaries:
        with open(args.osm_boundaries, encoding="utf-8") as fh:
            return json.load(fh)
    if bbox is None:
        raise ValueError("--fetch-boundaries needs --bbox")
    url = args.overpass_url or overpass.DEFAULT_URL
    doc = overpass.fetch(bbox, url=url, query=overpass.build_boundary_query(bbox))
    if args.save_boundaries:
        with open(args.save_boundaries, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
    return doc


def _osm_boundaries(args, doc, data, bbox, city, hoods, city_source, hood_source):
    """Fill in whatever the GeoJSON options left out (plan 5.6: official data first, then OSM)."""
    from .osm_boundaries import approximate_regions, find_city, find_neighborhoods, osm_areas, place_points

    areas = osm_areas(doc)
    if city is None:
        if bbox is not None:
            centre = ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
        else:
            lats = [lat for lat, _ in data.nodes.values()] or [0.0]
            lons = [lon for _, lon in data.nodes.values()] or [0.0]
            centre = ((min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2)
        city = find_city(areas, admin_level=args.admin_level, name=args.city_osm_name, point=centre)
        if city is None:
            how = f"named {args.city_osm_name!r}" if args.city_osm_name else "containing the area's centre"
            print(f"warning: no OSM admin_level={args.admin_level} boundary {how}; not clipping", file=sys.stderr)
        else:
            city_source = city_source or f"OpenStreetMap ({city.id})"
            if args.city_name:
                from dataclasses import replace

                city = replace(city, name=args.city_name)
    if not hoods:
        hoods, kind = find_neighborhoods(areas, city)
        if hoods:
            hood_source = hood_source or f"OpenStreetMap ({kind})"
            print(f"neighborhoods from OpenStreetMap: {len(hoods)} ({kind})")
        elif args.approximate_regions:
            hoods, kind = approximate_regions(place_points(doc), city)
            if hoods:
                hood_source = hood_source or f"OpenStreetMap {kind}, approximate regions"
                print(f"approximate neighborhoods around OpenStreetMap {kind}: {len(hoods)}")
        if not hoods:
            print("no OpenStreetMap neighborhoods found; the pack has none", file=sys.stderr)
    return city, hoods, city_source, hood_source


def _feature_doc(args: argparse.Namespace, bbox):
    from . import overpass

    if args.osm_features:
        with open(args.osm_features, encoding="utf-8") as fh:
            return json.load(fh)
    if bbox is None:
        raise ValueError("--fetch-features needs --bbox")
    url = args.overpass_url or overpass.DEFAULT_URL
    doc = overpass.fetch(bbox, url=url, query=overpass.build_feature_query(bbox))
    if args.save_features:
        with open(args.save_features, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
    return doc


def cmd_feature_query(args: argparse.Namespace) -> int:
    from . import overpass

    try:
        bbox = overpass.parse_bbox(args.bbox)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(overpass.build_feature_query(bbox))
    return 0


def cmd_boundary_query(args: argparse.Namespace) -> int:
    from . import overpass

    try:
        bbox = overpass.parse_bbox(args.bbox)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(overpass.build_boundary_query(bbox))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from .evaluation import load_result
    from .report import write_report

    try:
        result = load_result(args.match)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    out = write_report(args.pack, result, args.out, ran_threshold=args.ran_threshold)
    print(f"wrote {out} (opens offline; paths dashed, no route traces)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    commands = {
        "report": cmd_report,
        "build-pack": cmd_build_pack,
        "boundary-query": cmd_boundary_query,
        "feature-query": cmd_feature_query,
        "match": cmd_match,
        "label-sheet": cmd_label_sheet,
        "evaluate": cmd_evaluate,
    }
    if args.command in commands:
        return commands[args.command](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
