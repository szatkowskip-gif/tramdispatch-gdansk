"""Testy grafu torów na prawdziwych danych OSM z data/osm_tram.json."""
from __future__ import annotations

import pytest

from backend.graph import _norm_stop, load_network

EXPECTED_LOOPS = {"jelitkowo", "oliwa", "strzyża pkm", "zaspa", "łostowice świętokrzyska", "ujeścisko", "chełm witosa"}


@pytest.fixture(scope="module")
def net():
    return load_network()


def test_graph_is_one_main_component(net):
    assert net.report.component_sizes[0] > 800
    assert sum(net.report.component_sizes[1:]) < 10, "poza głównym komponentem mogą być tylko pojedyncze śmieci"


def test_all_line_relations_are_continuous(net):
    assert net.report.broken_relations == []


def test_every_line_has_edges(net):
    refs = {r["tags"].get("ref") for r in net.relations} - {None}
    for ref in refs:
        assert any(ref in d["lines"] for _, _, d in net.G.edges(data=True)), f"linia {ref} bez krawędzi"


def test_known_loops_detected(net):
    names = {_norm_stop(t.name) for t in net.turnbacks if t.kind == "loop" and t.terminus}
    missing = EXPECTED_LOOPS - names
    assert not missing, f"brak pętli: {missing}"


def test_every_terminus_has_turnback(net):
    turnback_names = {_norm_stop(t.name) for t in net.turnbacks if t.kind in {"loop", "stub", "triangle"}}
    for term in net.terminus_names():
        assert term in turnback_names or term == "lawendowe wzgóze", f"terminus {term} bez punktu zawracania"


def test_crossovers_are_bidirectional_only(net):
    for t in net.turnbacks:
        if t.kind == "crossover":
            assert t.for_bidirectional_only


def test_geojson_shape(net):
    gj = net.to_geojson()
    kinds = {f["properties"]["kind"] for f in gj["features"]}
    assert {"edge", "switch", "tram_stop", "turnback"} <= kinds
    assert "report" in gj
