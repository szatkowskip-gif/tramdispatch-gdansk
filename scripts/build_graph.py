"""Buduje graf torów z data/osm_tram.json + data/overrides.json i wypisuje raport jakości.

    python scripts/build_graph.py            # raport na ekran
    python scripts/build_graph.py --geojson  # dodatkowo zapisuje data/network.geojson
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.graph import DATA, load_network  # noqa: E402


def main() -> int:
    net = load_network()
    print(net.report.text())
    (DATA / "graph_report.md").write_text("```\n" + net.report.text() + "\n```\n", encoding="utf-8")
    if "--geojson" in sys.argv:
        out = DATA / "network.geojson"
        out.write_text(json.dumps(net.to_geojson(), ensure_ascii=False), encoding="utf-8")
        print(f"\nZapisano {out.relative_to(DATA.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
