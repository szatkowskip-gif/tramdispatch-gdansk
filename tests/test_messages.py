"""Komunikaty z szablonów: brak pustych pól, obie wersje językowe, strategie."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from backend.graph import load_config, load_network
from backend.incidents import IncidentAnalyzer
from backend.lines import Fleet, Lines
from backend.live import normalize
from backend.messages import build_context, render_all

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def incident():
    net = load_network()
    lines = Lines(net)
    an = IncidentAnalyzer(net, lines, load_config())
    feed = json.loads((FIX / "gpsPositions_sample.json").read_text(encoding="utf-8"))
    snap = normalize(feed, Fleet(), lines)
    analysis = an.analyze(["1488892824:0"], True, snap["trams"])
    return {"id": "t", "created_at": int(time.time()), "status": "active", "location_text": "al. Grunwaldzka przy Galerii Bałtyckiej",
            "cause": "kolizja", "expected_until": "ok. 45 min", "both_directions": True, "decision": {}, "analysis": analysis}


def test_render_all_keys_and_no_placeholders(incident):
    m = render_all(incident)
    assert set(m) == {"passenger_pl", "passenger_en", "drivers", "restored_pl", "restored_en"}
    for k, v in m.items():
        assert "None" not in v and "{{" not in v and "()" not in v, k
        assert v.strip(), k
    assert "UTRUDNIENIA" in m["passenger_pl"] and "DISRUPTION" in m["passenger_en"]
    assert "Galeria Bałtycka" in m["passenger_pl"]
    assert "ok. 45 min" in m["passenger_pl"]
    assert "kolizja" in m["passenger_pl"] and "collision" in m["passenger_en"]
    assert "KOMUNIKAT SŁUŻBOWY" in m["drivers"]
    assert "Linie 5, 6" in m["restored_pl"]


def test_strategy_override_changes_text(incident):
    inc = dict(incident)
    inc["decision"] = {"lines": {"6": "suspended"}, "replacement_bus": "Z6"}
    m = render_all(inc)
    assert "Linia 6 zawieszona" in m["passenger_pl"]
    assert "Line 6 suspended" in m["passenger_en"]
    assert "Z6" in m["passenger_pl"]
    ctx = build_context(inc)
    assert next(l for l in ctx["lines"] if l["ref"] == "6")["strategy"] == "suspended"
