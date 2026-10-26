"""SQLite: historia pozycji tramwajów (etap 2), awarie i decyzje (etap 3+)."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

from backend.graph import DATA

SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
  ts INTEGER NOT NULL,            -- epoch s (czas 'generated' z feedu)
  vehicle_code TEXT NOT NULL,
  line TEXT NOT NULL,
  headsign TEXT,
  lat REAL NOT NULL,
  lon REAL NOT NULL,
  speed REAL,
  direction REAL,
  delay INTEGER,
  PRIMARY KEY (vehicle_code, ts)
);
CREATE INDEX IF NOT EXISTS positions_ts ON positions(ts);
"""


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or DATA / "tramdispatch.db"
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)

    def insert_positions(self, rows: list[dict[str, Any]]) -> int:
        with self._lock:
            cur = self._conn.executemany(
                "INSERT OR IGNORE INTO positions(ts, vehicle_code, line, headsign, lat, lon, speed, direction, delay) "
                "VALUES (:ts, :vehicle_code, :line, :headsign, :lat, :lon, :speed, :direction, :delay)",
                rows,
            )
            self._conn.commit()
            return cur.rowcount

    def trail(self, vehicle_code: str, since_ts: int) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT ts, lat, lon, speed, delay, line, headsign FROM positions WHERE vehicle_code=? AND ts>=? ORDER BY ts",
                (vehicle_code, since_ts),
            )
            return [dict(zip(("ts", "lat", "lon", "speed", "delay", "line", "headsign"), r)) for r in cur.fetchall()]

    def snapshot_at(self, ts: int, max_age_s: int = 120) -> list[dict[str, Any]]:
        """Ostatnia pozycja każdego pojazdu nie późniejsza niż ts i nie starsza niż max_age_s."""
        with self._lock:
            cur = self._conn.execute(
                """SELECT p.vehicle_code, p.ts, p.lat, p.lon, p.speed, p.direction, p.delay, p.line, p.headsign
                   FROM positions p JOIN (
                     SELECT vehicle_code, MAX(ts) AS mts FROM positions WHERE ts<=? AND ts>=? GROUP BY vehicle_code
                   ) m ON m.vehicle_code=p.vehicle_code AND m.mts=p.ts""",
                (ts, ts - max_age_s),
            )
            keys = ("vehicle_code", "ts", "lat", "lon", "speed", "direction", "delay", "line", "headsign")
            return [dict(zip(keys, r)) for r in cur.fetchall()]

    def bounds(self) -> tuple[int | None, int | None]:
        with self._lock:
            lo, hi = self._conn.execute("SELECT MIN(ts), MAX(ts) FROM positions").fetchone()
            return lo, hi

    def purge_older_than(self, ts: int) -> int:
        with self._lock:
            cur = self._conn.execute("DELETE FROM positions WHERE ts<?", (ts,))
            self._conn.commit()
            return cur.rowcount

    def close(self) -> None:
        with self._lock:
            self._conn.close()
