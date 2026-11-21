"""Routing graph, connectors and A* (plan 5.2, 6.1). Synthetic networks only."""

import random
import time

import pytest
from test_elevation import write_asc
from test_matcher import GRID, PROJ
from test_path_matching import make

from streetfill.elevation import AsciiGrid, add_elevation
from streetfill.pack import write_pack
from streetfill.routing import Graph, length_cost


def graph_of(net, tmp_path, name="p.sqlite", **kw):
    path = tmp_path / name
    write_pack(net, path)
    return Graph.from_pack(path, **kw)


def local(g, i):
    """A node's position in the tests' projection (the graph uses the pack's own origin)."""
    return PROJ.to_xy(g.coords[i])


def node_at(g, xy, tol=0.5):
    hits = [i for i in range(len(g.coords)) if abs(local(g, i)[0] - xy[0]) < tol and abs(local(g, i)[1] - xy[1]) < tol]
    assert len(hits) == 1, (xy, hits)
    return hits[0]


# a street, a footway joined to it, a footway drawn up to the kerb but not joined (8 m short),
# one that stops 20 m short, and steps
STREETS = make([
    (1, {"highway": "residential", "name": "Main Street"}, [(0, 0), (100, 0), (200, 0)]),
    (2, {"highway": "footway", "name": "Joined Walk"}, [(100, 0), (100, 80)]),
    (3, {"highway": "footway", "name": "Kerb Walk"}, [(200, 8), (200, 90)]),
    (4, {"highway": "footway", "name": "Short Walk"}, [(0, 20), (0, 90)]),
    (5, {"highway": "steps"}, [(100, 80), (130, 80)]),
])


def test_graph_has_every_layer_in_both_directions(tmp_path):
    g = graph_of(STREETS, tmp_path, connectors=False)
    layers = sorted({e.layer for e in g.edges.values()})
    assert layers == ["path", "steps", "street"]
    a, b = node_at(g, (0, 0)), node_at(g, (100, 0))
    assert any(to == b and fwd for to, _, fwd in g.adj[a]) and any(to == a and not fwd for to, _, fwd in g.adj[b])


def test_connectors_join_paths_that_stop_at_the_kerb(tmp_path):
    g = graph_of(STREETS, tmp_path)
    conns = [e for e in g.edges.values() if e.layer == "connector"]
    assert len(conns) == 1
    (c,) = conns
    ends = {tuple(round(v) for v in local(g, c.u)), tuple(round(v) for v in local(g, c.v))}
    assert ends == {(200, 8), (200, 0)} and c.length_m == pytest.approx(8, abs=0.05) and c.id < 0
    # the kerb walk is now reachable from the street; the short walk (20 m away) still is not
    start = node_at(g, (0, 0))
    assert g.shortest_path(start, node_at(g, (200, 90))).length_m == pytest.approx(200 + 8 + 82, abs=0.1)
    assert g.shortest_path(start, node_at(g, (0, 90))) is None
    assert g.components()[0] == len(g.node_ids) - 2  # only the short walk's two nodes are apart


def test_no_connector_back_onto_the_same_way_or_a_close_neighbour(tmp_path):
    net = make([
        (1, {"highway": "residential", "name": "A"}, [(0, 0), (100, 0)]),
        (2, {"highway": "footway", "name": "Stub"}, [(100, 0), (100, 10)]),  # 10 m stub off the street end
    ])
    g = graph_of(net, tmp_path)
    assert not [e for e in g.edges.values() if e.layer == "connector"]


def test_shortest_path_on_the_grid(tmp_path):
    g = graph_of(GRID, tmp_path)
    a, b = node_at(g, (0, 0)), node_at(g, (200, 80))
    r = g.shortest_path(a, b)
    assert r.length_m == pytest.approx(280, abs=0.5) and r.cost == pytest.approx(r.length_m)
    assert r.nodes[0] == a and r.nodes[-1] == b and len(r.arcs) == len(r.nodes) - 1
    back = g.shortest_path(b, a)
    assert back.length_m == pytest.approx(r.length_m) and back.nodes[0] == b and back.nodes[-1] == a

    # a cost that makes one edge very expensive routes around it
    first = r.arcs[0][0]
    detour = g.shortest_path(a, b, lambda e, f: e.length_m * (50 if e.id == first else 1))
    assert first not in [e for e, _ in detour.arcs]


def test_astar_matches_dijkstra_with_varied_costs(tmp_path):
    g = graph_of(GRID, tmp_path)
    rng = random.Random(4)
    factor = {eid: rng.uniform(0.15, 3.0) for eid in g.edges}

    def cost(e, fwd):
        return e.length_m * factor[e.id] * (1.2 if fwd else 1.0)

    for _ in range(30):
        a, b = rng.randrange(len(g.node_ids)), rng.randrange(len(g.node_ids))
        astar = g.shortest_path(a, b, cost, min_factor=0.15)
        dijkstra = g.shortest_path(a, b, cost, min_factor=0.0)
        assert (astar is None) == (dijkstra is None)
        if astar:
            assert astar.cost == pytest.approx(dijkstra.cost)


def test_nearest_node_and_elevation(tmp_path):
    grid = AsciiGrid.load(write_asc(tmp_path / "g.asc", 41.88, -87.66, 300, 300))
    with_ele, _ = add_elevation(GRID, grid)
    g = graph_of(with_ele, tmp_path)
    i = g.nearest_node(PROJ.to_latlon((3, 4)))
    assert local(g, i) == pytest.approx((0, 0), abs=0.5)
    assert g.nearest_node(PROJ.to_latlon((0, 600))) is None  # more than 150 m from any node
    assert all(v is not None for v in g.elevation)
    e = next(iter(g.edges.values()))
    assert e.rise(True) == e.gain_m and e.rise(False) == e.loss_m


def test_city_sized_graph(tmp_path):
    # a 12 x 12 km grid of streets 100 m apart: about 29,000 edges and 14,600 nodes
    xs = range(0, 12001, 100)
    lines = [(i + 1, {"highway": "residential", "name": f"H{i}"}, [(x, i * 100) for x in xs]) for i in range(121)]
    lines += [(1000 + i, {"highway": "residential", "name": f"V{i}"}, [(i * 100, y) for y in xs]) for i in range(121)]
    t0 = time.perf_counter()
    g = graph_of(make(lines), tmp_path)
    load = time.perf_counter() - t0
    t0 = time.perf_counter()
    r = g.shortest_path(node_at(g, (0, 0)), node_at(g, (12000, 12000)), min_factor=1.0)
    query = time.perf_counter() - t0
    assert r.length_m == pytest.approx(24000, rel=1e-3)
    assert load < 30 and query < 5, (load, query)


def test_edges_are_split_where_a_path_meets_them_mid_block(tmp_path):
    g = graph_of(STREETS, tmp_path, connectors=False)
    mid = node_at(g, (100, 0))  # the footway's end, an interior vertex of the street edge
    pieces = [e for e in g.edges.values() if e.layer == "street"]
    assert len(pieces) == 2 and {e.pack_id for e in pieces} == {1} and all(e.id < 0 for e in pieces)
    assert sum(e.length_m for e in pieces) == pytest.approx(200, abs=0.05)
    assert g.shortest_path(node_at(g, (0, 0)), node_at(g, (100, 80))).length_m == pytest.approx(180, abs=0.1)
    assert mid in {e.u for e in pieces} | {e.v for e in pieces}


def test_split_pieces_share_the_elevation_profile(tmp_path):
    grid = AsciiGrid.load(write_asc(tmp_path / "g.asc", 41.88, -87.66, 300, 300))
    with_ele, _ = add_elevation(STREETS, grid)
    g = graph_of(with_ele, tmp_path)
    parent = next(e for e in with_ele.edges if e.layer == "street")
    pieces = sorted((e for e in g.edges.values() if e.pack_id == 1 and e.layer == "street"), key=lambda e: local(g, e.u)[0])
    assert g.elevation[pieces[0].u] == parent.elevation[0] and g.elevation[pieces[-1].v] == parent.elevation[-1]
    # the plane rises steadily to the east, so the pieces' climbs add up to the parent's
    assert sum(p.gain_m for p in pieces) == pytest.approx(sum(max(0, b - a) for a, b in zip(parent.elevation, parent.elevation[1:])), abs=0.2)
