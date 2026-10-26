"""Testy normalizacji feedu ZTM i dopasowania wariantów na zapisanej próbce."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.graph import load_network
from backend.lines import Fleet, Lines, is_tram_line, norm_headsign
from backend.live import normalize
from backend.store import Store

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def lines():
    return Lines(load_network())


def test_is_tram_line():
    assert is_tram_line("2") and is_tram_line("12")
    assert not is_tram_line("132") and not is_tram_line("N5") and not is_tram_line("T8") and not is_tram_line("")


def test_norm_headsign():
    assert norm_headsign("Łostowice Świętokrz.") == "lostowice swietokrz"
    assert norm_headsign("Jelitkowo 02") == "jelitkowo"


def test_normalize_filters_and_fields():
    feed = json.loads((FIX / "gpsPositions_sample.json").read_text(encoding="utf-8"))
    feed["vehicles"].append({"routeShortName": "5", "vehicleCode": "1099", "lat": 0.0, "lon": 0.0, "gpsQuality": 0, "generated": feed["lastUpdate"]})
    feed["vehicles"].append({"routeShortName": "5", "vehicleCode": "1098", "lat": 54.3, "lon": 18.6, "gpsQuality": 3, "delay": 99999, "generated": feed["lastUpdate"]})
    snap = normalize(feed, Fleet())
    codes = {t["vehicle_code"] for t in snap["trams"]}
    assert "1099" not in codes, "rekord z zerowymi współrzędnymi odrzucony"
    assert "1098" in codes
    bad = next(t for t in snap["trams"] if t["vehicle_code"] == "1098")
    assert bad["delay"] is None, "absurdalne opóźnienie zamienione na brak danych"
    assert all(is_tram_line(t["line"]) for t in snap["trams"])
    assert all("type" in t and "age_s" in t for t in snap["trams"])


def test_every_sample_tram_matches_variant(lines):
    feed = json.loads((FIX / "gpsPositions_sample.json").read_text(encoding="utf-8"))
    snap = normalize(feed, Fleet(), lines)
    unmatched = [(t["line"], t["headsign"]) for t in snap["trams"] if t["variant_id"] is None]
    assert unmatched == []


def test_fleet_lookup():
    f = Fleet()
    assert f.lookup("1062")["bidirectional"] is True
    assert f.lookup("1020")["bidirectional"] is False
    assert f.lookup("abc")["bidirectional"] is None


def test_store_roundtrip(tmp_path):
    s = Store(tmp_path / "t.db")
    rows = [{"ts": 1000 + i * 15, "vehicle_code": "1001", "line": "2", "headsign": "x", "lat": 54.0 + i * 0.001, "lon": 18.0, "speed": 10, "direction": 90, "delay": 30} for i in range(5)]
    assert s.insert_positions(rows) == 5
    assert s.insert_positions(rows) == 0, "duplikaty ignorowane"
    assert len(s.trail("1001", 1030)) == 3
    snap = s.snapshot_at(1046)
    assert len(snap) == 1 and snap[0]["ts"] == 1045
    assert s.purge_older_than(1030) == 2
    s.close()
