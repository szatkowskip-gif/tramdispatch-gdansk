"""Linie tramwajowe: warianty tras z relacji OSM, nazwy przystanków z GTFS, tabor.

Wariant = jedna relacja `route=tram` z OSM (kierunek + ewentualne skrócenie).
Każdy wariant ma uporządkowaną listę krawędzi grafu i przystanków.
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.graph import DATA, TramNetwork, _norm_stop

TRAM_LINE_RE = re.compile(r"^\d{1,2}$")
MIN_VARIANT_EDGES = 10


def is_tram_line(ref: str) -> bool:
    """Linie tramwajowe w Gdańsku mają numery 1–19; autobusy od 100, nocne N, metropolitalne M, tymczasowe T."""
    return bool(TRAM_LINE_RE.match(ref or "")) and int(ref) < 20


def norm_headsign(text: str) -> str:
    """Normalizacja do porównań: małe litery, bez polskich znaków, bez kropek, bez numeru peronu."""
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = t.replace("ł", "l").replace(".", "")
    parts = t.split()
    if parts and parts[-1].isdigit():
        parts = parts[:-1]
    return " ".join(parts)


@dataclass
class Variant:
    id: int
    ref: str
    name: str
    from_: str
    to: str
    edges: list[str]
    stops: list[dict[str, Any]]  # {node, name}
    length_m: float = 0.0
    incomplete: bool = False  # relacja OSM ma za mało odcinków, żeby być pełną trasą

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "ref": self.ref, "name": self.name, "from": self.from_, "to": self.to,
                "edges": self.edges, "stops": self.stops, "length_m": round(self.length_m), "incomplete": self.incomplete}


@dataclass
class Line:
    ref: str
    variants: list[Variant] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"ref": self.ref, "variants": [v.to_dict() for v in self.variants]}


class Lines:
    def __init__(self, net: TramNetwork, gtfs_dir: Path | None = None, headsigns_path: Path | None = None):
        self.net = net
        self.lines: dict[str, Line] = {}
        self.gtfs_stops: dict[str, list[dict[str, Any]]] = defaultdict(list)  # norm name -> [{stop_id, name, lat, lon}]
        self.headsign_map: dict[str, str] = {}
        self._load_gtfs_stops(gtfs_dir or DATA / "gtfs")
        self._load_headsigns(headsigns_path or DATA / "headsigns.json")
        self._build()

    def _load_gtfs_stops(self, gtfs_dir: Path) -> None:
        p = gtfs_dir / "stops.txt"
        if not p.exists():
            return
        with p.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                self.gtfs_stops[norm_headsign(row["stop_name"])].append(
                    {"stop_id": row["stop_id"], "name": row["stop_name"], "lat": float(row["stop_lat"]), "lon": float(row["stop_lon"])})

    def _load_headsigns(self, path: Path) -> None:
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8")).get("map", {})
            self.headsign_map = {norm_headsign(k): norm_headsign(v) for k, v in raw.items()}

    def _build(self) -> None:
        edge_by_way: dict[int, list[tuple[int, int, dict]]] = defaultdict(list)
        for u, v, d in self.net.G.edges(data=True):
            if d.get("way") is not None:
                edge_by_way[d["way"]].append((u, v, d))

        for rel in self.net.relations:
            t = rel["tags"]
            ref = t.get("ref")
            if not ref or not is_tram_line(ref):
                continue
            way_ids = [m["ref"] for m in rel["members"] if m["type"] == "way" and m["role"] == ""]
            edges = self._walk_ways(way_ids, edge_by_way)
            stops = []
            for m in rel["members"]:
                if m["type"] == "node" and m["role"].startswith("stop"):
                    info = self.net.node_info.get(m["ref"])
                    if info:
                        stops.append({"node": m["ref"], "name": info.get("name") or "?"})
            length = sum(self.net.G.edges[u, v]["length_m"] for u, v in edges)
            edge_ids = [self.net.G.edges[u, v]["id"] for u, v in edges]
            v = Variant(id=rel["id"], ref=ref, name=t.get("name", f"Tram {ref}"), from_=t.get("from", ""), to=t.get("to", ""),
                        edges=edge_ids, stops=stops, length_m=length, incomplete=len(edge_ids) < MIN_VARIANT_EDGES)
            self.lines.setdefault(ref, Line(ref=ref)).variants.append(v)
        for line in self.lines.values():
            line.variants.sort(key=lambda v: -v.length_m)

    def _walk_ways(self, way_ids: list[int], edge_by_way: dict[int, list[tuple[int, int, dict]]]) -> list[tuple[int, int]]:
        """Zamienia kolejne odcinki OSM relacji na ciąg skierowanych krawędzi grafu.

        Dla odcinka dwukierunkowego wybiera kierunek zgodny z poprzednim odcinkiem.
        """
        result: list[tuple[int, int]] = []
        prev_end: int | None = None
        # OSM bywa zduplikowane (ten sam odcinek kilka razy pod rząd w relacji)
        way_ids = [w for i, w in enumerate(way_ids) if i == 0 or w != way_ids[i - 1]]
        for wid in way_ids:
            segs = edge_by_way.get(wid, [])
            fwd = sorted([(u, v, d) for u, v, d in segs if not d["id"].endswith(":r")], key=lambda x: int(x[2]["id"].split(":")[1]))
            if not fwd:
                continue
            start, end = fwd[0][0], fwd[-1][1]
            has_rev = any(d["id"].endswith(":r") for _, _, d in segs)
            use_rev = False
            if prev_end is not None and prev_end != start and prev_end == end and has_rev:
                use_rev = True
            elif prev_end is None and len(way_ids) > 1 and has_rev:
                # pierwszy odcinek: dopasuj do początku drugiego
                nxt = edge_by_way.get(way_ids[1], [])
                nxt_nodes = {u for u, _, _ in nxt} | {v for _, v, _ in nxt}
                if start in nxt_nodes and end not in nxt_nodes:
                    use_rev = True
            if use_rev:
                seq = [(v, u) for u, v, _ in reversed(fwd)]
            else:
                seq = [(u, v) for u, v, _ in fwd]
            result.extend(seq)
            prev_end = seq[-1][1]
        return result

    # ------------------------------------------------------------------ query
    def to_dict(self) -> dict[str, Any]:
        return {"lines": [self.lines[k].to_dict() for k in sorted(self.lines, key=int)]}

    def match_variant(self, ref: str, headsign: str) -> Variant | None:
        """Dobiera wariant linii po tekście kierunku z feedu ZTM."""
        line = self.lines.get(ref)
        if not line:
            return None
        h = norm_headsign(headsign)
        h = self.headsign_map.get(h, h)
        best: Variant | None = None
        for v in line.variants:
            if v.incomplete:
                continue
            to = norm_headsign(v.to)
            if to == h or to.startswith(h) or h.startswith(to):
                if best is None or v.length_m > best.length_m:
                    best = v
        return best


# ---------------------------------------------------------------------- fleet
class Fleet:
    def __init__(self, path: Path | None = None):
        p = path or DATA / "fleet.json"
        self.types: list[dict[str, Any]] = json.loads(p.read_text(encoding="utf-8")).get("types", []) if p.exists() else []

    def lookup(self, vehicle_code: str | int) -> dict[str, Any]:
        try:
            n = int(str(vehicle_code))
        except ValueError:
            return {"type": "nieznany", "bidirectional": None}
        for t in self.types:
            if t["from"] <= n <= t["to"]:
                return {"type": t["type"], "bidirectional": bool(t["bidirectional"])}
        return {"type": "nieznany", "bidirectional": None}
