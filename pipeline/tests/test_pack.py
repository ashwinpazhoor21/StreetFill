import sqlite3
import time
from pathlib import Path

import pytest

from streetfill.geo import LocalProjection
from streetfill.network import Network, build_network
from streetfill.osm import OsmData, Way, load_overpass_file
from streetfill.pack import (
    GRID_CELL_M,
    cell_of,
    decode_geometry,
    edge_cells,
    encode_geometry,
    write_pack,
)

FIXTURE = Path(__file__).parent / "fixtures" / "mini_area.json"


@pytest.fixture(scope="module")
def net():
    return build_network(load_overpass_file(FIXTURE))


@pytest.fixture()
def pack(net, tmp_path):
    out = tmp_path / "pack.sqlite"
    write_pack(net, out)
    con = sqlite3.connect(out)
    yield con
    con.close()


def test_geometry_round_trip():
    coords = [(41.9, -87.65), (41.90123456789, -87.6512345678)]
    assert decode_geometry(encode_geometry(coords)) == coords


def test_tables_and_counts(pack, net):
    tables = {r[0] for r in pack.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"meta", "streets", "edges", "grid"} <= tables
    assert pack.execute("SELECT count(*) FROM edges").fetchone()[0] == len(net.edges) == 13
    assert pack.execute("SELECT count(*) FROM streets").fetchone()[0] == len(net.streets) == 8
    layers = dict(pack.execute("SELECT layer, count(*) FROM edges GROUP BY layer"))
    assert layers == {"street": 12, "path": 1}
    assert pack.execute("SELECT layer FROM streets WHERE key = 'path:way:311'").fetchone() == ("path",)


def test_meta(pack, net):
    meta = dict(pack.execute("SELECT key, value FROM meta"))
    assert meta["schema_version"] == "4"
    assert meta["attribution"] == "© OpenStreetMap contributors"
    assert meta["edge_count"] == "13"
    assert float(meta["total_length_m"]) == pytest.approx(sum(e.length_m for e in net.edges), abs=0.01)
    street = sum(e.length_m for e in net.edges if e.layer == "street")
    path = sum(e.length_m for e in net.edges if e.layer == "path")
    assert float(meta["street_length_m"]) == pytest.approx(street, abs=0.01)
    assert float(meta["path_length_m"]) == pytest.approx(path, abs=0.01) and path > 0
    south, west, north, east = map(float, meta["bbox"].split(","))
    assert south < north and west < east


def test_edges_link_to_streets_and_keep_geometry(pack, net):
    rows = pack.execute(
        "SELECT e.id, s.key, e.geometry, e.length_m FROM edges e JOIN streets s ON s.id = e.street_id ORDER BY e.id"
    ).fetchall()
    for (edge_id, key, blob, length), edge in zip(rows, net.edges):
        assert edge_id == edge.id
        assert key == edge.street_key
        assert decode_geometry(blob) == edge.coords
        assert length == pytest.approx(edge.length_m)


def test_street_lengths_sum_edges(pack):
    rows = pack.execute(
        "SELECT s.length_m, sum(e.length_m) FROM streets s JOIN edges e ON e.street_id = s.id GROUP BY s.id"
    ).fetchall()
    for street_len, edge_sum in rows:
        assert street_len == pytest.approx(edge_sum)


def test_every_edge_point_is_in_an_indexed_cell(pack, net):
    meta = dict(pack.execute("SELECT key, value FROM meta"))
    proj = LocalProjection(float(meta["origin_lat"]), float(meta["origin_lon"]))
    grid = set(pack.execute("SELECT cell_x, cell_y, edge_id FROM grid"))
    for e in net.edges:
        for p in e.coords:
            cx, cy = cell_of(*proj.to_xy(p))
            assert (cx, cy, e.id) in grid


def test_grid_lookup_finds_nearby_edge(pack):
    # Node 10 sits midway along the first Oak Street edge (1 -> 10 -> 2).
    meta = dict(pack.execute("SELECT key, value FROM meta"))
    proj = LocalProjection(float(meta["origin_lat"]), float(meta["origin_lon"]))
    cx, cy = cell_of(*proj.to_xy((41.9, -87.65 + 0.5 * 0.0013)))
    ids = {r[0] for r in pack.execute("SELECT edge_id FROM grid WHERE cell_x=? AND cell_y=?", (cx, cy))}
    assert 1 in ids


def test_edge_cells_covers_a_diagonal_segment():
    proj = LocalProjection(0.0, 0.0)
    a = proj.to_latlon((10.0, 10.0))
    b = proj.to_latlon((250.0, 150.0))
    cells = edge_cells([a, b], proj)
    assert cells == {(x, y) for x in range(0, 3) for y in range(0, 2)}


def test_overwrites_existing_file(net, tmp_path):
    out = tmp_path / "pack.sqlite"
    out.write_text("not a database")
    write_pack(net, out)
    con = sqlite3.connect(out)
    assert con.execute("SELECT count(*) FROM edges").fetchone()[0] == 13
    con.close()
    assert not (tmp_path / "pack.sqlite.tmp").exists()


def test_empty_network_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        write_pack(Network(streets=[], edges=[]), tmp_path / "pack.sqlite")


def synthetic_grid(size_m: float = 3000.0, block_m: float = 80.0) -> OsmData:
    """A Manhattan-style grid of residential streets about size_m on a side."""
    proj = LocalProjection(41.88, -87.63)
    n = int(size_m / block_m) + 1
    nodes, ways = {}, []
    for i in range(n):
        for j in range(n):
            nodes[i * n + j + 1] = proj.to_latlon((j * block_m, i * block_m))
    for i in range(n):
        ways.append(Way(len(ways) + 1, tuple(i * n + j + 1 for j in range(n)),
                        {"highway": "residential", "name": f"Row {i}"}))
        ways.append(Way(len(ways) + 1, tuple(j * n + i + 1 for j in range(n)),
                        {"highway": "residential", "name": f"Column {i}"}))
    return OsmData(nodes, ways)


def test_3km_pack_builds_quickly(tmp_path):
    start = time.perf_counter()
    net = build_network(synthetic_grid())
    write_pack(net, tmp_path / "pack.sqlite")
    elapsed = time.perf_counter() - start
    assert len(net.edges) > 2500
    assert elapsed < 60, f"pack took {elapsed:.1f}s"
