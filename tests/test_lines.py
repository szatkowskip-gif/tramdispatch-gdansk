from __future__ import annotations

import pytest

from backend.graph import load_network
from backend.lines import Lines


@pytest.fixture(scope="module")
def lines():
    return Lines(load_network())


def test_all_tram_lines_present(lines):
    assert set(lines.lines) == {"2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"}


def test_variants_have_edges_and_stops(lines):
    for line in lines.lines.values():
        assert len(line.variants) >= 2, f"linia {line.ref} ma za mało wariantów"
        for v in line.variants:
            if v.incomplete:
                continue
            assert len(v.edges) > 10 and len(v.stops) > 5, v.name


def test_incomplete_variants_are_flagged_not_dropped(lines):
    inc = [v.name for line in lines.lines.values() for v in line.variants if v.incomplete]
    assert "Tram 5: Oliwa => Strzyża PKM" in inc


def test_variant_edges_are_continuous(lines):
    G = lines.net.G
    by_id = {d["id"]: (u, v) for u, v, d in G.edges(data=True)}
    for line in lines.lines.values():
        for v in line.variants:
            if v.incomplete:
                continue
            prev = None
            for eid in v.edges:
                u, w = by_id[eid]
                if prev is not None:
                    assert u == prev, f"{v.name}: przerwa przed krawędzią {eid}"
                prev = w


def test_match_variant_headsigns(lines):
    assert lines.match_variant("3", "Brzeźno").to.startswith("Brzeźno")
    assert lines.match_variant("2", "Strzyża PKM").to.startswith("Strzyża")
    assert lines.match_variant("12", "Zaspa").to.startswith("Zaspa")
    assert lines.match_variant("99", "x") is None
