"""Pozycje tramwajów na żywo z otwartych danych ZTM Gdańsk.

Poller w wątku odpytuje feed co N sekund, filtruje tramwaje, normalizuje rekordy,
trzyma ostatni snapshot w pamięci i zapisuje historię do SQLite.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from backend.lines import Fleet, Lines, is_tram_line
from backend.store import Store

log = logging.getLogger("tramdispatch.live")

MAX_ABS_DELAY_S = 3600
STALE_AFTER_S = 120


def parse_ts(s: str | None) -> int | None:
    if not s:
        return None
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def normalize(feed: dict[str, Any], fleet: Fleet | None = None, lines: Lines | None = None) -> dict[str, Any]:
    """Z surowego JSON ZTM robi listę tramwajów z polami używanymi przez front.

    Odrzuca: nie-tramwaje, rekordy bez współrzędnych (0,0) lub z gpsQuality 0.
    """
    now = parse_ts(feed.get("lastUpdate")) or int(time.time())
    out: list[dict[str, Any]] = []
    for v in feed.get("vehicles", []):
        ref = str(v.get("routeShortName") or "")
        if not is_tram_line(ref):
            continue
        lat, lon = v.get("lat") or 0.0, v.get("lon") or 0.0
        if abs(lat) < 1 or abs(lon) < 1 or (v.get("gpsQuality") or 0) <= 0:
            continue
        delay = v.get("delay")
        if delay is not None and abs(delay) > MAX_ABS_DELAY_S:
            delay = None
        ts = parse_ts(v.get("generated")) or now
        rec: dict[str, Any] = {
            "vehicle_code": str(v.get("vehicleCode")),
            "line": ref,
            "headsign": v.get("headsign") or "",
            "lat": lat,
            "lon": lon,
            "speed": v.get("speed"),
            "direction": v.get("direction"),
            "delay": delay,
            "ts": ts,
            "age_s": max(0, now - ts),
            "trip_id": v.get("tripId"),
            "service": v.get("vehicleService"),
        }
        if fleet:
            rec.update(fleet.lookup(rec["vehicle_code"]))
        if lines:
            var = lines.match_variant(ref, rec["headsign"])
            rec["variant_id"] = var.id if var else None
        out.append(rec)
    return {"last_update": now, "trams": out}


class LivePoller:
    def __init__(self, url: str, interval_s: int, retention_h: int, store: Store, fleet: Fleet, lines: Lines):
        self.url, self.interval_s, self.retention_s = url, interval_s, retention_h * 3600
        self.store, self.fleet, self.lines = store, fleet, lines
        self.snapshot: dict[str, Any] = {"last_update": None, "trams": []}
        self.last_ok: float | None = None
        self.last_error: str | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="ztm-poller", daemon=True)
        self._last_purge = 0.0

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def poll_once(self) -> None:
        r = httpx.get(self.url, timeout=20, headers={"User-Agent": "tramdispatch-gdansk/0.1"})
        r.raise_for_status()
        snap = normalize(r.json(), self.fleet, self.lines)
        self.snapshot = snap
        self.last_ok = time.time()
        self.last_error = None
        rows = [{k: t[k] for k in ("ts", "vehicle_code", "line", "headsign", "lat", "lon", "speed", "direction", "delay")} for t in snap["trams"]]
        self.store.insert_positions(rows)
        if time.time() - self._last_purge > 3600:
            self.store.purge_older_than(int(time.time()) - self.retention_s)
            self._last_purge = time.time()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception as exc:  # noqa: BLE001
                self.last_error = str(exc)
                log.warning("feed ZTM: %s", exc)
            self._stop.wait(self.interval_s)

    def health(self) -> dict[str, Any]:
        return {
            "feed_age_s": None if self.last_ok is None else int(time.time() - self.last_ok),
            "trams": len(self.snapshot["trams"]),
            "last_error": self.last_error,
            "interval_s": self.interval_s,
        }
