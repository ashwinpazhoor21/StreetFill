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
    return parser


def cmd_build_pack(args: argparse.Namespace) -> int:
    from . import overpass
    from .network import build_network
    from .osm import load_overpass_file, parse_overpass
    from .pack import write_pack

    start = time.perf_counter()
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
    if not network.edges:
        print("error: no runnable streets found in the input", file=sys.stderr)
        return 1
    meta = write_pack(network, args.out, bbox=bbox, source=source)
    elapsed = time.perf_counter() - start
    km = float(meta["total_length_m"]) / 1000
    print(
        f"wrote {args.out}: {meta['street_count']} streets, {meta['edge_count']} edges, "
        f"{km:.1f} km in {elapsed:.1f}s"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "build-pack":
        return cmd_build_pack(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
