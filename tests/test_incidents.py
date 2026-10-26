"""Testy analizy awarii: graf syntetyczny (pierścień + odnogi) i realne dane Gdańska."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.graph import TramNetwork, load_config, load_network
from backend.incidents import IncidentAnalyzer, point_to_polyline_m
from backend.lines import Fleet, Lines
from backend.live import normalize

FIX = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------- syntetyczny
def _node(i, lat, lon, kind=None, name=None):
    tags = {}
    if kind:
        tags["railway"] = kind
    if name:
        tags["name"] = name
    return {"type": "node", "id": i, "lat": lat, "lon": lon, "tags": tags}


def _way(i, nodes, coords, oneway="yes", **tags):
    return {"type": "way", "id": i, "nodes": nodes, "geometry": [{"lat": a, "lon": b} for a, b in coords],
            "tags": {"railway": "tram", "oneway": oneway, **tags}}


def synthetic():
    """Linia W-E po torze głównym 1->2->3->4->5 (oneway) i z powrotem 5->6->7->8->1 (drugi tor).
    Między 2 i 4 dodatkowy łącznik 2->9->4 (objazd). Pętle na końcach: 1 i 5 (cykle).
    Przejazd międzytorowy między 3 i 7 (krótki, obie strony zwrotnice).
    """
    lat0, lon0 = 54.0, 18.0
    d = 0.01  # ~650 m; pierścień ~5 km, więc nie zostanie wzięty za pętlę
    nodes = [
        _node(1, lat0, lon0, "tram_stop", "Zachód 01"), _node(2, lat0, lon0 + d, "switch"), _node(3, lat0, lon0 + 2 * d, "switch"),
        _node(4, lat0, lon0 + 3 * d, "switch"), _node(5, lat0, lon0 + 4 * d, "tram_stop", "Wschód 01"),
        _node(6, lat0 + 0.00015, lon0 + 3 * d), _node(7, lat0 + 0.00015, lon0 + 2 * d, "switch"), _node(8, lat0 + 0.00015, lon0 + d),
        _node(9, lat0 + 0.002, lon0 + 2 * d, "tram_stop", "Objazdowa"),
        _node(10, lat0 - 0.001, lon0, "switch"), _node(11, lat0 - 0.001, lon0 + 4 * d, "switch"),
        _node(14, lat0 - 0.001, lon0 + 0.001), _node(15, lat0 - 0.001, lon0 + 4 * d - 0.001),
        _node(12, lat0, lon0 + 1.5 * d, "tram_stop", "Środek A"), _node(13, lat0, lon0 + 2.5 * d, "tram_stop", "Środek B"),
    ]
    c = {n["id"]: (n["lat"], n["lon"]) for n in nodes}
    ways = [
        _way(101, [1, 2], [c[1], c[2]]), _way(102, [2, 12, 3], [c[2], c[12], c[3]]), _way(103, [3, 13, 4], [c[3], c[13], c[4]]), _way(104, [4, 5], [c[4], c[5]]),
        _way(105, [5, 6], [c[5], c[6]]), _way(106, [6, 7], [c[6], c[7]]), _way(107, [7, 8], [c[7], c[8]]), _way(108, [8, 1], [c[8], c[1]]),
        _way(109, [2, 9], [c[2], c[9]]), _way(110, [9, 4], [c[9], c[4]]),  # objazd
        _way(111, [3, 7], [c[3], c[7]], oneway="no", service="crossover"),  # przejazd
        _way(112, [1, 10], [c[1], c[10]]), _way(113, [10, 14, 1], [c[10], c[14], c[1]]),  # pętla zachód (cykl 1-10-14-1)
        _way(114, [5, 11], [c[5], c[11]]), _way(115, [11, 15, 5], [c[11], c[15], c[5]]),  # pętla wschód
    ]
    rel_e = {"type": "relation", "id": 9001, "tags": {"type": "route", "route": "tram", "ref": "1", "name": "Tram 1: Zachód => Wschód", "from": "Zachód 01", "to": "Wschód 01"},
             "members": [{"type": "node", "ref": 1, "role": "stop"}, {"type": "node", "ref": 12, "role": "stop"}, {"type": "node", "ref": 13, "role": "stop"}, {"type": "node", "ref": 5, "role": "stop"}]
             + [{"type": "way", "ref": w, "role": ""} for w in (101, 102, 103, 104)]}
    rel_w = {"type": "relation", "id": 9002, "tags": {"type": "route", "route": "tram", "ref": "1", "name": "Tram 1: Wschód => Zachód", "from": "Wschód 01", "to": "Zachód 01"},
             "members": [{"type": "node", "ref": 5, "role": "stop"}, {"type": "node", "ref": 1, "role": "stop"}] + [{"type": "way", "ref": w, "role": ""} for w in (105, 106, 107, 108)]}
    return {"elements": nodes + ways + [rel_e, rel_w]}


@pytest.fixture(scope="module")
def syn():
    cfg = load_config()
    net = TramNetwork(synthetic(), {}, cfg)
    lines = Lines(net, gtfs_dir=Path("/nonexistent"), headsigns_path=Path("/nonexistent"))
    # obniż próg kompletności na potrzeby małego grafu
    for line in lines.lines.values():
        for v in line.variants:
            v.incomplete = False
    return net, lines, IncidentAnalyzer(net, lines, cfg)


def test_synthetic_loops_and_crossover(syn):
    net, _, _ = syn
    kinds = {t.kind for t in net.turnbacks}
    assert "loop" in kinds and "crossover" in kinds
    assert all(t.for_bidirectional_only for t in net.turnbacks if t.kind == "crossover")


def test_detour_found_on_ring(syn):
    net, lines, an = syn
    eid = net.G.edges[2, 12]["id"]
    res = an.analyze([eid], both_directions=False)
    l = next(r for r in res["affected_lines"] if r["variant_id"] == 9001)
    assert l["detour"]["found"], "między 2 a 4 jest łącznik przez 9"
    assert "Objazdowa" in l["detour"]["added_stops"]
    assert "Środek A" in l["detour"]["skipped_stops"]


def test_no_detour_when_link_blocked(syn):
    net, lines, an = syn
    eids = [net.G.edges[2, 12]["id"], net.G.edges[2, 9]["id"]]
    res = an.analyze(eids, both_directions=False)
    l = next(r for r in res["affected_lines"] if r["variant_id"] == 9001)
    assert not l["detour"]["found"]
    # zawracanie: przed blokadą (od Zachodu) tylko pętla zachód dla jednokierunkowych
    a = l["side_a"]
    assert a["default_unidirectional"]["kind"] == "loop"
    # za blokadą: przejazd 3-7 dostępny tylko dwukierunkowym, pętla wschód dla wszystkich
    b = l["side_b"]
    assert b["default_bidirectional"]["kind"] == "crossover"
    assert b["default_unidirectional"]["kind"] == "loop"


def test_both_directions_adds_parallel_track(syn):
    net, lines, an = syn
    eid = net.G.edges[3, 13]["id"]
    res = an.analyze([eid], both_directions=True)
    assert len(res["blocked_edges"]) >= 2
    assert {r["variant_id"] for r in res["affected_lines"]} == {9001, 9002}


def test_vehicle_situations(syn):
    net, lines, an = syn
    eid = net.G.edges[3, 13]["id"]
    c = {n: (d["lat"], d["lon"]) for n, d in net.G.nodes(data=True)}
    trams = [
        {"vehicle_code": "A", "line": "1", "headsign": "Wschód", "lat": c[12][0], "lon": c[12][1], "variant_id": 9001, "bidirectional": False},
        {"vehicle_code": "B", "line": "1", "headsign": "Wschód", "lat": c[4][0], "lon": c[4][1] + 0.0001, "variant_id": 9001, "bidirectional": False},
        {"vehicle_code": "C", "line": "1", "headsign": "Zachód", "lat": c[8][0], "lon": c[8][1], "variant_id": 9002, "bidirectional": True},
    ]
    res = an.analyze([eid], both_directions=False, live_trams=trams)
    sit = {v["vehicle_code"]: v["situation"] for v in res["affected_vehicles"]}
    assert sit["A"] == "approaching"
    assert sit["B"] == "beyond", "za blokadą, ale ma pętlę wschód"
    assert sit["C"] == "unaffected", "drugi tor nie jest zablokowany"


def test_point_to_polyline():
    d, along = point_to_polyline_m(54.0, 18.0005, [(54.0, 18.0), (54.0, 18.001)])
    assert d < 1 and 30 < along < 36


# ----------------------------------------------------------------- realne dane
@pytest.fixture(scope="module")
def real():
    net = load_network()
    lines = Lines(net)
    return net, lines, IncidentAnalyzer(net, lines, load_config())


def _edge_near(an, name_part):
    stop = next(i for i in an.net.node_info.values() if i["kind"] == "tram_stop" and i["name"] and name_part in i["name"])
    return min((e for e in an.edges.values() if e.lines), key=lambda e: point_to_polyline_m(stop["lat"], stop["lon"], e.geometry)[0]).id


def test_real_block_galeria_baltycka(real):
    net, lines, an = real
    feed = json.loads((FIX / "gpsPositions_sample.json").read_text(encoding="utf-8"))
    snap = normalize(feed, Fleet(), lines)
    res = an.analyze([_edge_near(an, "Galeria Ba")], True, snap["trams"])
    assert {"5", "6", "12"} <= set(res["lines_hit"])
    for l in res["affected_lines"]:
        assert l["side_a"]["candidates"] or l["side_b"]["candidates"]
    assert "Galeria Bałtycka" in res["unserved_stops_all"]
    assert any(v["situation"] != "unaffected" for v in res["affected_vehicles"])


def test_real_block_hucisko_has_detour_or_turnbacks(real):
    net, lines, an = real
    res = an.analyze([_edge_near(an, "Hucisko")], True)
    assert res["affected_lines"], "Hucisko to węzeł, musi dotykać linii"
    for l in res["affected_lines"]:
        assert l["detour"]["found"] or l["side_a"]["default_bidirectional"] or l["side_b"]["default_bidirectional"]
