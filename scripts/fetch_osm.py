"""Pobiera sieć tramwajową Gdańska z Overpass API i zapisuje do data/osm_tram.json.

Uruchamiać rzadko (dane są commitowane). Wymaga: httpx.
    python scripts/fetch_osm.py
"""
from __future__ import annotations

import json
import sys
import time
import tomllib
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
QUERY = (ROOT / "scripts" / "overpass_query.ql").read_text(encoding="utf-8")
OUT = ROOT / "data" / "osm_tram.json"


def main() -> int:
    cfg = tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8"))["osm"]
    print(f"Overpass: {cfg['overpass_url']}")
    urls = [cfg["overpass_url"], *cfg.get("overpass_fallbacks", [])]
    data = None
    for attempt in range(6):
        url = urls[attempt % len(urls)]
        try:
            r = httpx.post(
                url,
                data={"data": QUERY},
                headers={"User-Agent": cfg["user_agent"], "Accept": "application/json"},
                timeout=300,
            )
            r.raise_for_status()
            data = r.json()
            break
        except (httpx.HTTPError, ValueError) as exc:
            print(f"  próba {attempt + 1} ({url}) nieudana: {exc}")
            time.sleep(10)
    if data is None:
        print("Nie udało się pobrać danych z żadnego serwera Overpass.")
        return 1
    els = data.get("elements", [])
    counts: dict[str, int] = {}
    for e in els:
        key = e["type"] + ":" + e.get("tags", {}).get("railway", e.get("tags", {}).get("route", "?"))
        counts[key] = counts.get(key, 0) + 1
    OUT.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"Zapisano {len(els)} elementów do {OUT.relative_to(ROOT)}")
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
