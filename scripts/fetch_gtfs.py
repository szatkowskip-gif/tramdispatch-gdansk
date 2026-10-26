"""Pobiera rozkład GTFS ZTM Gdańsk i rozpakowuje wybrane pliki do data/gtfs/.

    python scripts/fetch_gtfs.py
"""
from __future__ import annotations

import io
import sys
import tomllib
import zipfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "gtfs"
KEEP = {"agency.txt", "stops.txt", "routes.txt", "trips.txt", "stop_times.txt", "shapes.txt", "calendar.txt", "calendar_dates.txt"}


def main() -> int:
    cfg = tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8"))["ztm"]
    print(f"GTFS: {cfg['gtfs_zip']}")
    r = httpx.get(cfg["gtfs_zip"], timeout=300, follow_redirects=True)
    r.raise_for_status()
    OUT.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = z.namelist()
        print("W archiwum:", ", ".join(names))
        for n in names:
            if n in KEEP:
                (OUT / n).write_bytes(z.read(n))
                print(f"  {n}: {(OUT / n).stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
