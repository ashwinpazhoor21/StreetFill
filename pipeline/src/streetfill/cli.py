"""Command-line entry point: ``streetfill <command>``."""

from __future__ import annotations

import argparse
import json
import sys
import time

from . import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="streetfill", description=__doc__)
    parser.add_argument("--version", action="version", version=f"streetfill {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    bp = sub.add_parser("build-pack", help="build a SQLite street pack from OpenStreetMap")
    src = bp.add_mutually_exclusive_group(required=True)
    src.add_argument("--bbox", help="download from Overpass: south,west,north,east")
    src.add_argument("--osm-json", metavar="PATH", help="use a saved Overpass JSON file")
    bp.add_argument("--out", required=True, help="output .sqlite path")
    bp.add_argument("--save-osm", metavar="PATH", help="also save the downloaded Overpass JSON")
    bp.add_argument("--overpass-url", default=None, help="Overpass interpreter URL")
    bp.add_argument("--city", metavar="GEOJSON", help="clip to this city boundary (all features' polygons)")
    bp.add_argument("--city-name", help="city name (default: the first feature's name property)")
    bp.add_argument("--city-source", default="", help="where the city boundary comes from, for attribution")
    bp.add_argument("--neighborhoods", metavar="GEOJSON", help="split edges by these neighborhood polygons")
    bp.add_argument("--neighborhood-id-property", default="id", help="feature property holding the id")
    bp.add_argument("--neighborhood-name-property", default="name", help="feature property holding the name")
    bp.add_argument("--neighborhood-source", default="", help="where the neighborhoods come from, for attribution")

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

    network = build_network(data)
    if network.edges and (city or hoods):
        network = assign_areas(network, city=city, neighborhoods=hoods)
    if not network.edges:
        where = " inside the city boundary" if city else ""
        print(f"error: no runnable streets found in the input{where}", file=sys.stderr)
        return 1
    meta = write_pack(
        network,
        args.out,
        bbox=bbox,
        source=source,
        city=city,
        city_source=args.city_source,
        neighborhoods=hoods,
        neighborhood_source=args.neighborhood_source,
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
    if hoods:
        street_m = float(meta["street_length_m"])
        none = float(meta["unassigned_street_length_m"]) / street_m if street_m else 0.0
        print(f"{len(hoods)} neighborhoods; {none:.1%} of street length is in none of them")
    return 0


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
        "match": cmd_match,
        "label-sheet": cmd_label_sheet,
        "evaluate": cmd_evaluate,
    }
    if args.command in commands:
        return commands[args.command](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
