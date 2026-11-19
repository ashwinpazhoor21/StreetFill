"""Elevation per edge (plan 6.6). Synthetic elevation grids only."""

import json
import sqlite3
from pathlib import Path

import pytest
from test_matcher import PROJ, make_network

from streetfill.cli import main
from streetfill.elevation import AsciiGrid, Mosaic, add_elevation, edge_profile, gain_loss, sample_points
from streetfill.geo import haversine_m
from streetfill.network import build_network
from streetfill.osm import OsmData, Way
from streetfill.pack import decode_elevation, encode_elevation, write_pack

FIXTURE = Path(__file__).parent / "fixtures" / "mini_area.json"  # lat 41.894-41.907, lon -87.65 to -87.6461
CELL = 0.0001  # about 11 m by 8 m at Chicago's latitude


def plane(lat, lon):
    """A gentle slope: 180 m at the origin, rising 0.5 m per 0.0001 deg east and 0.2 m per 0.0001 deg north."""
    return 180 + (lon + 87.66) * 5000 + (lat - 41.88) * 2000


def write_asc(path, south, west, nrows, ncols, fn=plane, nodata=None, center=False, cell=CELL):
    rows = []
    for r in range(nrows):
        lat = south + (nrows - r - 0.5) * cell
        rows.append(" ".join(f"{fn(lat, west + (c + 0.5) * cell):.4f}" for c in range(ncols)))
    if center:
        origin = [f"xllcenter {west + cell / 2}", f"yllcenter {south + cell / 2}"]
    else:
        origin = [f"xllcorner {west}", f"yllcorner {south}"]
    header = [f"ncols {ncols}", f"nrows {nrows}", *origin, f"cellsize {cell}"]
    if nodata is not None:
        header.append(f"NODATA_value {nodata}")
    path.write_text("\n".join(header + rows) + "\n")
    return path


@pytest.fixture()
def grid(tmp_path):
    return AsciiGrid.load(write_asc(tmp_path / "g.asc", 41.88, -87.66, 300, 300))


def test_bilinear_sampling_reproduces_a_plane(grid):
    for lat, lon in [(41.9, -87.65), (41.8956, -87.6432), (41.881, -87.659)]:
        assert grid.sample(lat, lon) == pytest.approx(plane(lat, lon), abs=1e-6)
    assert grid.sample(41.0, -87.65) is None  # outside the grid


def test_header_variants_and_errors(tmp_path, grid):
    centred = AsciiGrid.load(write_asc(tmp_path / "c.asc", 41.88, -87.66, 300, 300, center=True))
    assert centred.sample(41.9, -87.65) == pytest.approx(grid.sample(41.9, -87.65))
    bad = tmp_path / "bad.asc"
    bad.write_text("ncols 2\nnrows 2\nxllcorner 0\nyllcorner 0\ncellsize 0.1\n1 2 3\n")
    with pytest.raises(ValueError, match="expected 4 values"):
        AsciiGrid.load(bad)
    bad.write_text("ncols 1\nnrows 1\nxllcorner 440000\nyllcorner 4640000\ncellsize 10\n5\n")
    with pytest.raises(ValueError, match="geographic"):
        AsciiGrid.load(bad)


def test_nodata_and_mosaic(tmp_path):
    holes = write_asc(tmp_path / "h.asc", 41.88, -87.66, 50, 50, fn=lambda la, lo: -9999 if lo > -87.6575 else 7.0,
                      nodata=-9999)
    full = write_asc(tmp_path / "f.asc", 41.88, -87.66, 50, 50, fn=lambda la, lo: 3.0)
    g = AsciiGrid.load(holes)
    assert g.sample(41.882, -87.659) == pytest.approx(7.0)
    assert g.sample(41.882, -87.656) is None
    assert g.sample(41.882, -87.65752) == pytest.approx(7.0)  # between a cell and nodata: renormalised, not dragged down
    m = Mosaic.load([holes, full])
    assert m.sample(41.882, -87.659) == pytest.approx(7.0) and m.sample(41.882, -87.656) == pytest.approx(3.0)


def test_sample_points_are_even_with_ends():
    a, b = PROJ.to_latlon((0, 0)), PROJ.to_latlon((100, 0))
    pts = sample_points([a, b])
    assert len(pts) == 5 and pts[0] == a and pts[-1] == b  # 100 m / 30 m -> 4 gaps of 25 m
    gaps = [haversine_m(p, q) for p, q in zip(pts, pts[1:])]
    assert gaps == pytest.approx([25] * 4, rel=1e-3)
    bent = [PROJ.to_latlon(p) for p in [(0, 0), (40, 0), (40, 50)]]  # 90 m with a corner
    assert len(sample_points(bent)) == 4
    assert len(sample_points([a, PROJ.to_latlon((10, 0))])) == 2


def test_profiles_bridges_and_gain():
    class Valley:  # flat ground at 20 m with a 15 m-deep river between x = 40 and 80
        def sample(self, lat, lon):
            x, _ = PROJ.to_xy((lat, lon))
            return 5.0 if 40 <= x <= 80 else 20.0

    coords = [PROJ.to_latlon((0, 0)), PROJ.to_latlon((120, 0))]
    ground = edge_profile(coords, Valley())
    bridge = edge_profile(coords, Valley(), flat=True)
    assert min(ground) < 20 and bridge == [20.0] * len(bridge)
    assert all(round(v * 10) == v * 10 for v in ground)  # whole decimetres
    assert edge_profile(coords, Mosaic([])) is None

    assert gain_loss([10.0, 11.0, 10.5, 12.0]) == (2.5, 0.5)
    assert gain_loss([12.0, 10.5, 11.0, 10.0]) == (0.5, 2.5)  # the other direction swaps them


def test_bridge_flag_from_tags():
    nodes = {i: PROJ.to_latlon((i * 50.0, 0)) for i in range(1, 9)}
    ways = [
        Way(1, (1, 2), {"highway": "residential", "name": "A", "bridge": "yes"}),
        Way(2, (3, 4), {"highway": "residential", "name": "B", "bridge": "viaduct"}),
        Way(3, (5, 6), {"highway": "footway", "name": "Pier Walk", "man_made": "pier"}),
        Way(4, (7, 8), {"highway": "residential", "name": "D", "bridge": "no"}),
    ]
    assert [e.bridge for e in build_network(OsmData(nodes, ways)).edges] == [True, True, True, False]


def test_pack_stores_profiles_gain_and_loss(tmp_path, grid):
    net = make_network(
        [
            (1, "East Street", "residential", [(0, 0), (200, 0), (400, 0)]),
            (2, "Cross Street", "residential", [(200, -100), (200, 0), (200, 100)]),
            (3, "Far Street", "residential", [(90000, 0), (90100, 0)]),  # outside the grid
        ]
    )
    with_ele, covered = add_elevation(net, grid)
    assert covered == len(net.edges) - 1
    # every edge meeting at a node agrees on its elevation there
    at_node = {}
    for e in with_ele.edges:
        if e.elevation:
            for node, v in ((e.from_node, e.elevation[0]), (e.to_node, e.elevation[-1])):
                assert at_node.setdefault(node, v) == v

    pack = tmp_path / "p.sqlite"
    meta = write_pack(with_ele, pack, elevation_source="test grid")
    assert meta["schema_version"] == "4" and meta["elevation_edge_count"] == str(covered)
    assert meta["elevation_source"] == "test grid" and meta["elevation_spacing_m"] == "30.0"
    con = sqlite3.connect(pack)
    by_id = {e.id: e for e in with_ele.edges}
    for eid, blob, gain, loss in con.execute("SELECT id, elevation, gain_m, loss_m FROM edges"):
        e = by_id[eid]
        if e.elevation is None:
            assert (blob, gain, loss) == (None, None, None)
        else:
            assert decode_elevation(blob) == e.elevation
            assert (gain, loss) == gain_loss(e.elevation)
    east = next(e for e in with_ele.edges if e.street_key == "name:east street")
    assert east.elevation[-1] > east.elevation[0]  # the plane rises to the east
    assert write_pack(net, tmp_path / "plain.sqlite")["elevation_edge_count"] == "0"


def test_encode_elevation_range():
    assert decode_elevation(encode_elevation([-12.3, 0.0, 3276.7])) == [-12.3, 0.0, 3276.7]
    with pytest.raises(ValueError, match="int16"):
        encode_elevation([3300.0])


def test_build_pack_with_dem(tmp_path, capsys):
    write_asc(tmp_path / "tile.asc", 41.89, -87.655, 200, 120)
    out = tmp_path / "pack.sqlite"
    assert main(["build-pack", "--osm-json", str(FIXTURE), "--out", str(out), "--dem", str(tmp_path / "tile.asc")]) == 0
    assert "elevation for 13 of 13 edges" in capsys.readouterr().out
    meta = dict(sqlite3.connect(out).execute("SELECT key, value FROM meta"))
    assert meta["elevation_source"] == "USGS 3DEP 1/3 arc-second DEM"

    cfg = tmp_path / "town.json"
    cfg.write_text(json.dumps({"osm_json": str(FIXTURE), "dem": ["tile.asc"], "dem_source": "test"}))
    assert main(["build-pack", "--city-config", str(cfg), "--out", str(out)]) == 0
    assert dict(sqlite3.connect(out).execute("SELECT key, value FROM meta"))["elevation_source"] == "test"

    (tmp_path / "broken.asc").write_text("ncols 1\n")
    assert main(["build-pack", "--osm-json", str(FIXTURE), "--out", str(out), "--dem", str(tmp_path / "broken.asc")]) == 2
    assert "elevation:" in capsys.readouterr().err
