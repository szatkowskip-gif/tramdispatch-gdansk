"""Graf torów tramwajowych Gdańska zbudowany z danych OSM.

Węzły: punkty OSM będące zwrotnicami, przystankami, skrzyżowaniami torów,
końcami odcinków lub miejscami łączenia odcinków. Krawędzie: skierowane
fragmenty torów między takimi węzłami. Odcinki `oneway=yes` dają jedną
krawędź, pozostałe dwie (jedną w każdą stronę).

Dodatkowo wykrywane są punkty zawracania:
- loop: pętla (krótki cykl w grafie przy przystanku końcowym),
- crossover: przejazd międzytorowy (krótki odcinek między zwrotnicami, poza
  trasami linii lub oznaczony service=crossover), dostępny tylko dla taboru
  dwukierunkowego,
- triangle: trójkąt torowy, wyłącznie z pliku overrides.json.

Plik data/overrides.json pozwala ręcznie dodać/usunąć krawędzie i dopisać
punkty zawracania. Każdy wpis ma pole `reason`.
"""
from __future__ import annotations

import json
import math
import tomllib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def polyline_length_m(coords: list[tuple[float, float]]) -> float:
    return sum(haversine_m(a[0], a[1], b[0], b[1]) for a, b in zip(coords, coords[1:]))


def _norm_stop(name: str) -> str:
    """'Jelitkowo 02' -> 'jelitkowo'; usuwa numer peronu i wielkość liter."""
    parts = name.strip().split()
    if parts and parts[-1].isdigit():
        parts = parts[:-1]
    return " ".join(parts).lower()


def _strip_platform(name: str) -> str:
    parts = name.strip().split()
    if len(parts) > 1 and parts[-1].isdigit():
        parts = parts[:-1]
    return " ".join(parts)


@dataclass
class Turnback:
    id: str
    kind: str  # loop | crossover | triangle
    name: str
    node: int
    lat: float
    lon: float
    nodes: list[int] = field(default_factory=list)
    for_bidirectional_only: bool = False
    source: str = "osm"  # osm | override
    terminus: bool = False  # pętla przy przystanku końcowym którejś linii

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class QualityReport:
    nodes: int = 0
    edges: int = 0
    ways: int = 0
    ways_without_oneway: list[int] = field(default_factory=list)
    components: int = 0
    component_sizes: list[int] = field(default_factory=list)
    dead_ends: list[dict[str, Any]] = field(default_factory=list)
    broken_relations: list[dict[str, Any]] = field(default_factory=list)
    loops: list[str] = field(default_factory=list)
    rings: list[str] = field(default_factory=list)
    termini_without_loop: list[str] = field(default_factory=list)
    isolated_ways: list[int] = field(default_factory=list)
    stubs: list[str] = field(default_factory=list)
    crossovers: int = 0
    triangles: int = 0
    overrides_applied: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()

    def text(self) -> str:
        lines = [
            "RAPORT JAKOŚCI GRAFU TORÓW",
            f"Odcinków OSM: {self.ways}, węzłów grafu: {self.nodes}, krawędzi: {self.edges}",
            f"Komponenty spójności: {self.components} (rozmiary: {self.component_sizes})",
            f"Odcinki bez tagu oneway (dają ruch w obie strony): {len(self.ways_without_oneway)}",
            f"Ślepe zakończenia poza pętlami: {len(self.dead_ends)}",
            f"Relacje linii z przerwami w trasie: {len(self.broken_relations)}",
            f"Pętle końcowe: {len(self.loops)}: {', '.join(self.loops)}",
            f"Inne krótkie pierścienie/trójkąty do weryfikacji: {len(self.rings)}: {', '.join(self.rings)}",
            f"Przystanki końcowe z relacji BEZ wykrytej pętli (dopisać w overrides): {', '.join(self.termini_without_loop) or 'brak'}",
            f"Izolowane odcinki (osobne komponenty): {self.isolated_ways or 'brak'}",
            f"Końcówki bez pętli (tylko tabor dwukierunkowy): {len(self.stubs)}: {', '.join(self.stubs)}",
            f"Przejazdy międzytorowe: {self.crossovers}, trójkąty (z overrides): {self.triangles}",
            f"Overrides: {self.overrides_applied}",
        ]
        if self.broken_relations:
            lines.append("")
            lines.append("Relacje z przerwami (sprawdzić brakujące zwrotnice / kierunek oneway):")
            for b in self.broken_relations:
                lines.append(f"  - {b['name']} (rel {b['relation']}): przerwa po odcinku {b['after_way']} przy węźle {b['node']}")
        if self.dead_ends:
            lines.append("")
            lines.append("Ślepe zakończenia (pierwsze 30):")
            for d in self.dead_ends[:30]:
                lines.append(f"  - węzeł {d['node']} ({d['lat']:.5f}, {d['lon']:.5f}) {d['why']}")
        return "\n".join(lines)


class TramNetwork:
    def __init__(self, osm: dict[str, Any], overrides: dict[str, Any] | None, cfg: dict[str, Any]):
        self.cfg = cfg
        self.overrides = overrides or {}
        self.G = nx.DiGraph()
        self.node_info: dict[int, dict[str, Any]] = {}
        self.ways: dict[int, dict[str, Any]] = {}
        self.relations: list[dict[str, Any]] = []
        self.way_lines: dict[int, set[str]] = defaultdict(set)
        self.turnbacks: list[Turnback] = []
        self.report = QualityReport()
        self._build(osm)

    # ------------------------------------------------------------------ build
    def _build(self, osm: dict[str, Any]) -> None:
        els = osm["elements"]
        for e in els:
            if e["type"] == "node":
                t = e.get("tags", {})
                self.node_info[e["id"]] = {
                    "lat": e["lat"],
                    "lon": e["lon"],
                    "kind": t.get("railway", "plain"),
                    "name": t.get("name"),
                    "ref": t.get("ref"),
                }
            elif e["type"] == "way" and e.get("tags", {}).get("railway") == "tram":
                self.ways[e["id"]] = e
            elif e["type"] == "relation" and e.get("tags", {}).get("route") == "tram":
                self.relations.append(e)

        for rel in self.relations:
            ref = rel["tags"].get("ref")
            if not ref:
                continue
            for m in rel["members"]:
                if m["type"] == "way" and m["role"] == "":
                    self.way_lines[m["ref"]].add(ref)

        usage = Counter()
        for w in self.ways.values():
            for n in w["nodes"]:
                usage[n] += 1
        for w in self.ways.values():
            for i, (nid, g) in enumerate(zip(w["nodes"], w["geometry"])):
                if nid not in self.node_info:
                    self.node_info[nid] = {"lat": g["lat"], "lon": g["lon"], "kind": "plain", "name": None, "ref": None}
        self.report.ways = len(self.ways)

        def topological(nid: int, first_last: bool) -> bool:
            if first_last or usage[nid] > 1:
                return True
            return self.node_info[nid]["kind"] in {"switch", "tram_stop", "railway_crossing"}

        for wid, w in self.ways.items():
            tags = w.get("tags", {})
            oneway = tags.get("oneway")
            if oneway is None:
                self.report.ways_without_oneway.append(wid)
            nodes = w["nodes"]
            geom = [(g["lat"], g["lon"]) for g in w["geometry"]]
            seg_start = 0
            seg_idx = 0
            for i in range(1, len(nodes)):
                if topological(nodes[i], i == len(nodes) - 1):
                    seg_nodes = nodes[seg_start : i + 1]
                    seg_geom = geom[seg_start : i + 1]
                    self._add_segment(wid, seg_idx, seg_nodes, seg_geom, oneway == "yes", tags)
                    seg_idx += 1
                    seg_start = i

        self._apply_overrides()
        self._attach_node_attrs()
        self._detect_turnbacks()
        self._quality()

    def _add_segment(self, wid: int, idx: int, nodes: list[int], geom: list[tuple[float, float]], oneway: bool, tags: dict) -> None:
        u, v = nodes[0], nodes[-1]
        length = polyline_length_m(geom)
        base = {
            "way": wid,
            "length_m": round(length, 1),
            "lines": sorted(self.way_lines.get(wid, ())),
            "service": tags.get("service"),
            "name": tags.get("name"),
        }
        self.G.add_edge(u, v, id=f"{wid}:{idx}", geometry=geom, **base)
        if not oneway:
            self.G.add_edge(v, u, id=f"{wid}:{idx}:r", geometry=list(reversed(geom)), **base)

    def _apply_overrides(self) -> None:
        applied = Counter()
        for e in self.overrides.get("remove_edges", []):
            eid = e["id"]
            for u, v, d in list(self.G.edges(data=True)):
                if d["id"] == eid:
                    self.G.remove_edge(u, v)
                    applied["remove_edges"] += 1
        for e in self.overrides.get("add_edges", []):
            u, v = e["from"], e["to"]
            if u in self.node_info and v in self.node_info:
                a, b = self.node_info[u], self.node_info[v]
                geom = [(a["lat"], a["lon"]), (b["lat"], b["lon"])]
                self.G.add_edge(u, v, id=e.get("id", f"override:{u}-{v}"), geometry=geom, way=None,
                                length_m=round(polyline_length_m(geom), 1), lines=[], service="override", name=e.get("reason"))
                applied["add_edges"] += 1
        self.report.overrides_applied = dict(applied)

    def _attach_node_attrs(self) -> None:
        for n in self.G.nodes:
            info = self.node_info[n]
            self.G.nodes[n].update(info)

    # -------------------------------------------------------------- turnbacks
    def _detect_turnbacks(self) -> None:
        loop_max = self.cfg["routing"]["loop_max_length_m"]
        cross_max = self.cfg["routing"]["crossover_max_length_m"]

        # Pętle. Szukamy krótkich cykli, ale bez "cykli" złożonych z odcinka i jego
        # odwrotności (odcinki bez tagu oneway dają obie krawędzie). Dwa przebiegi:
        # tylko krawędzie "w przód" i tylko krawędzie "w tył" nietagowanych odcinków.
        fwd = nx.DiGraph(((u, v, d) for u, v, d in self.G.edges(data=True) if not d["id"].endswith(":r")))
        bwd = nx.DiGraph(((u, v, d) for u, v, d in self.G.edges(data=True) if d["id"].endswith(":r") or self.ways.get(d.get("way"), {}).get("tags", {}).get("oneway") == "yes"))
        found: list[set[int]] = []
        for H in (fwd, bwd):
            for u, v, d in H.edges(data=True):
                if d["length_m"] > loop_max:
                    continue
                try:
                    _, path = nx.single_source_dijkstra(H, v, u, cutoff=loop_max - d["length_m"], weight="length_m")
                except (nx.NetworkXNoPath, KeyError):
                    continue
                cyc = set(path)
                for s in found:
                    if cyc & s:
                        s |= cyc
                        break
                else:
                    found.append(cyc)
        merged: list[set[int]] = []
        for s in found:
            for m in merged:
                if m & s:
                    m |= s
                    break
            else:
                merged.append(s)
        termini = self.terminus_names()
        loop_nodes: set[int] = set()
        for i, s in enumerate(merged):
            stop_names = {self.node_info[n]["name"] for n in s if self.node_info[n]["kind"] == "tram_stop" and self.node_info[n]["name"]}
            name = self._nearest_stop_name(s) or f"pętla {i + 1}"
            is_terminus = any(_norm_stop(x) in termini for x in stop_names | {name})
            center = self._centroid(s)
            self.turnbacks.append(Turnback(id=f"loop:{min(s)}", kind="loop", name=_strip_platform(name), node=min(s),
                                           lat=center[0], lon=center[1], nodes=sorted(s), terminus=is_terminus))
            loop_nodes |= s
        self._loop_nodes = loop_nodes

        # Przejazdy międzytorowe
        for u, v, d in self.G.edges(data=True):
            if d["length_m"] > cross_max or u in loop_nodes or v in loop_nodes:
                continue
            ku, kv = self.node_info[u]["kind"], self.node_info[v]["kind"]
            if ku != "switch" or kv != "switch":
                continue
            tagged = d.get("service") == "crossover"
            off_route = not d["lines"]
            if not (tagged or off_route):
                continue
            tid = f"crossover:{min(u, v)}-{max(u, v)}"
            if any(t.id == tid for t in self.turnbacks):
                continue
            a, b = self.node_info[u], self.node_info[v]
            name = self._nearest_stop_name({u, v}, radius_m=250) or "przejazd międzytorowy"
            self.turnbacks.append(Turnback(id=tid, kind="crossover", name=f"przejazd {name}", node=u,
                                           lat=(a["lat"] + b["lat"]) / 2, lon=(a["lon"] + b["lon"]) / 2,
                                           nodes=[u, v], for_bidirectional_only=True))

        # Końcówki bez pętli: przystanek końcowy linii, przy którym nie ma pętli.
        # Zawracają tam tylko składy dwukierunkowe (lub pętla nie jest w OSM; patrz raport).
        loop_termini = {_norm_stop(t.name) for t in self.turnbacks if t.kind == "loop"}
        by_name: dict[str, list[int]] = defaultdict(list)
        for n, info in self.node_info.items():
            if info["kind"] == "tram_stop" and info["name"] and n in self.G:
                by_name[_norm_stop(info["name"])].append(n)
        for term in sorted(termini - loop_termini):
            nodes = by_name.get(term)
            if not nodes:
                continue
            c = self._centroid(set(nodes))
            self.turnbacks.append(Turnback(id=f"stub:{min(nodes)}", kind="stub", name=_strip_platform(self.node_info[nodes[0]]["name"]),
                                           node=min(nodes), lat=c[0], lon=c[1], nodes=sorted(nodes),
                                           for_bidirectional_only=True, terminus=True))

        # Trójkąty i inne punkty z overrides
        for t in self.overrides.get("turnbacks", []):
            n = t["node"]
            if n not in self.node_info:
                continue
            info = self.node_info[n]
            self.turnbacks.append(Turnback(id=f"{t['kind']}:{n}", kind=t["kind"], name=t.get("name", t["kind"]), node=n,
                                           lat=info["lat"], lon=info["lon"], nodes=[n],
                                           for_bidirectional_only=t.get("for_bidirectional_only", t["kind"] == "crossover"),
                                           source="override"))

    def terminus_names(self) -> set[str]:
        """Znormalizowane nazwy przystanków końcowych ze wszystkich relacji linii."""
        out: set[str] = set()
        for rel in self.relations:
            for k in ("from", "to"):
                v = rel["tags"].get(k)
                if v:
                    out.add(_norm_stop(v))
        return out

    def _centroid(self, nodes: set[int]) -> tuple[float, float]:
        lat = sum(self.node_info[n]["lat"] for n in nodes) / len(nodes)
        lon = sum(self.node_info[n]["lon"] for n in nodes) / len(nodes)
        return lat, lon

    def _nearest_stop_name(self, nodes: set[int], radius_m: float = 150) -> str | None:
        inside = [self.node_info[n]["name"] for n in nodes if self.node_info[n]["kind"] == "tram_stop" and self.node_info[n]["name"]]
        if inside:
            return Counter(inside).most_common(1)[0][0]
        c = self._centroid(nodes)
        best, best_d = None, radius_m
        for n, info in self.node_info.items():
            if info["kind"] == "tram_stop" and info["name"]:
                d = haversine_m(c[0], c[1], info["lat"], info["lon"])
                if d < best_d:
                    best, best_d = info["name"], d
        return best

    # ---------------------------------------------------------------- quality
    def _quality(self) -> None:
        r = self.report
        r.nodes = self.G.number_of_nodes()
        r.edges = self.G.number_of_edges()
        comps = sorted((len(c) for c in nx.weakly_connected_components(self.G)), reverse=True)
        r.components = len(comps)
        r.component_sizes = comps[:10]
        for n in self.G.nodes:
            if n in self._loop_nodes:
                continue
            outd, ind = self.G.out_degree(n), self.G.in_degree(n)
            if outd == 0 or ind == 0:
                info = self.node_info[n]
                # końce w zajezdniach / bocznicach są normalne
                svc = {d.get("service") for _, _, d in self.G.in_edges(n, data=True)} | {d.get("service") for _, _, d in self.G.out_edges(n, data=True)}
                if svc & {"yard", "siding", "spur"}:
                    continue
                r.dead_ends.append({"node": n, "lat": info["lat"], "lon": info["lon"],
                                    "why": "brak wyjazdu" if outd == 0 else "brak wjazdu"})
        for rel in self.relations:
            ways = [m["ref"] for m in rel["members"] if m["type"] == "way" and m["role"] == ""]
            prev_nodes: set[int] | None = None
            for wid in ways:
                w = self.ways.get(wid)
                if not w:
                    continue
                ns = {w["nodes"][0], w["nodes"][-1]}
                if prev_nodes is not None and not (prev_nodes & set(w["nodes"])):
                    r.broken_relations.append({"relation": rel["id"], "name": rel["tags"].get("name"), "after_way": wid, "node": list(prev_nodes)})
                    break
                prev_nodes = ns
        r.loops = [t.name for t in self.turnbacks if t.kind == "loop" and t.terminus]
        r.rings = [t.name for t in self.turnbacks if t.kind == "loop" and not t.terminus]
        loop_termini = {_norm_stop(t.name) for t in self.turnbacks if t.kind == "loop"}
        r.termini_without_loop = sorted(t for t in self.terminus_names() if t not in loop_termini)
        main = max(nx.weakly_connected_components(self.G), key=len)
        r.isolated_ways = sorted({d["way"] for u, v, d in self.G.edges(data=True) if u not in main and d.get("way")})
        r.stubs = [t.name for t in self.turnbacks if t.kind == "stub"]
        r.crossovers = sum(1 for t in self.turnbacks if t.kind == "crossover")
        r.triangles = sum(1 for t in self.turnbacks if t.kind == "triangle")

    # ----------------------------------------------------------------- export
    def to_geojson(self) -> dict[str, Any]:
        feats: list[dict[str, Any]] = []
        for u, v, d in self.G.edges(data=True):
            feats.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[lon, lat] for lat, lon in d["geometry"]]},
                "properties": {"kind": "edge", "id": d["id"], "from": u, "to": v, "length_m": d["length_m"],
                               "lines": d["lines"], "service": d.get("service"), "way": d.get("way")},
            })
        for n, info in self.G.nodes(data=True):
            if info["kind"] in {"switch", "tram_stop", "railway_crossing"}:
                feats.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [info["lon"], info["lat"]]},
                    "properties": {"kind": info["kind"], "id": n, "name": info.get("name"), "ref": info.get("ref"),
                                   "in_loop": n in self._loop_nodes},
                })
        for t in self.turnbacks:
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [t.lon, t.lat]},
                "properties": {**t.to_dict(), "tb_kind": t.kind, "kind": "turnback"},
            })
        return {"type": "FeatureCollection", "features": feats, "report": self.report.to_dict()}


def load_config() -> dict[str, Any]:
    return tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8"))


def load_network(osm_path: Path | None = None, overrides_path: Path | None = None) -> TramNetwork:
    osm = json.loads((osm_path or DATA / "osm_tram.json").read_text(encoding="utf-8"))
    op = overrides_path or DATA / "overrides.json"
    overrides = json.loads(op.read_text(encoding="utf-8")) if op.exists() else {}
    return TramNetwork(osm, overrides, load_config())
