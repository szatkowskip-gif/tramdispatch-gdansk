"""Awarie: blokada odcinków, objazdy, zawracanie, składy dotknięte.

Wejście: lista zablokowanych krawędzi grafu (+ opcjonalnie oba kierunki).
Wyjście: dla każdego wariantu linii przechodzącego przez blokadę — objazd (jeśli
istnieje), punkty zawracania po obu stronach z podziałem na tabor jedno- i
dwukierunkowy, przystanki nieobsługiwane; dla każdego tramwaju z feedu — jego
sytuacja względem blokady.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import networkx as nx

from backend.graph import TramNetwork, Turnback, _norm_stop, haversine_m
from backend.lines import Lines, Variant

# --------------------------------------------------------------------- geometria

def _proj(lat0: float):
    k = math.cos(math.radians(lat0))

    def f(lat: float, lon: float) -> tuple[float, float]:
        return (lon * k * 111320.0, lat * 110540.0)

    return f


def point_to_polyline_m(lat: float, lon: float, geom: list[tuple[float, float]]) -> tuple[float, float]:
    """Odległość punktu od łamanej (m) i odległość wzdłuż łamanej do rzutu (m)."""
    f = _proj(lat)
    px, py = f(lat, lon)
    best, best_along = float("inf"), 0.0
    along = 0.0
    for (a_lat, a_lon), (b_lat, b_lon) in zip(geom, geom[1:]):
        ax, ay = f(a_lat, a_lon)
        bx, by = f(b_lat, b_lon)
        dx, dy = bx - ax, by - ay
        seg_len = math.hypot(dx, dy)
        if seg_len == 0:
            continue
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (seg_len * seg_len)))
        qx, qy = ax + t * dx, ay + t * dy
        d = math.hypot(px - qx, py - qy)
        if d < best:
            best, best_along = d, along + t * seg_len
        along += seg_len
    return best, best_along


# ------------------------------------------------------------------------ model

@dataclass
class EdgeRef:
    id: str
    u: int
    v: int
    length_m: float
    geometry: list[tuple[float, float]]
    lines: list[str]


class IncidentAnalyzer:
    def __init__(self, net: TramNetwork, lines: Lines, cfg: dict[str, Any]):
        self.net, self.lines, self.cfg = net, lines, cfg["routing"]
        self.edges: dict[str, EdgeRef] = {}
        for u, v, d in net.G.edges(data=True):
            self.edges[d["id"]] = EdgeRef(d["id"], u, v, d["length_m"], d["geometry"], d["lines"])
        self.turnbacks_by_node: dict[int, list[Turnback]] = defaultdict(list)
        for t in net.turnbacks:
            for n in t.nodes:
                self.turnbacks_by_node[n].append(t)

    # ------------------------------------------------------------ pomocnicze
    def parallel_edges(self, edge_ids: list[str], radius_m: float = 20.0) -> list[str]:
        """Krawędzie równoległe (drugi tor) do podanych: środek w promieniu radius_m od łamanej."""
        out: list[str] = []
        base = [self.edges[e] for e in edge_ids if e in self.edges]
        for e in self.edges.values():
            if e.id in edge_ids:
                continue
            mid = e.geometry[len(e.geometry) // 2]
            if any(point_to_polyline_m(mid[0], mid[1], b.geometry)[0] <= radius_m for b in base):
                # pomiń krawędź odwrotną tego samego odcinka (ten sam tor): ma ten sam way i geometrię
                out.append(e.id)
        return out

    def edge_name(self, edge_id: str) -> str:
        """Nazwa opisowa odcinka: najbliższe przystanki z linii, które tędy jeżdżą."""
        e = self.edges[edge_id]
        mid = e.geometry[len(e.geometry) // 2]
        best, best_d = None, 400.0
        for n, info in self.net.node_info.items():
            if info["kind"] == "tram_stop" and info["name"]:
                d = haversine_m(mid[0], mid[1], info["lat"], info["lon"])
                if d < best_d:
                    best, best_d = info["name"], d
        return f"przy {_strip(best)}" if best else f"odcinek {edge_id}"

    # ------------------------------------------------------------------ analiza
    def analyze(self, blocked: list[str], both_directions: bool = True, live_trams: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        blocked = [b for b in blocked if b in self.edges]
        if both_directions:
            blocked = list(dict.fromkeys(blocked + self.parallel_edges(blocked)))
        blocked_set = set(blocked)
        H = self.net.G.copy()
        H.remove_edges_from([(self.edges[e].u, self.edges[e].v) for e in blocked])

        affected: list[dict[str, Any]] = []
        variant_results: dict[int, dict[str, Any]] = {}
        for line in self.lines.lines.values():
            for var in line.variants:
                if var.incomplete:
                    continue
                res = self._analyze_variant(var, blocked_set, H)
                if res:
                    affected.append(res)
                    variant_results[var.id] = res

        vehicles = self._analyze_vehicles(live_trams or [], blocked_set, variant_results)
        unserved_all = sorted({s for r in affected for s in r["unserved_stops"]})
        lines_hit = sorted({r["ref"] for r in affected}, key=int)
        return {
            "blocked_edges": blocked,
            "blocked_names": sorted({self.edge_name(e) for e in blocked}),
            "both_directions": both_directions,
            "affected_lines": affected,
            "affected_vehicles": vehicles,
            "unserved_stops_all": unserved_all,
            "lines_hit": lines_hit,
            "summary_pl": self._summary(affected, vehicles),
        }

    def _analyze_variant(self, var: Variant, blocked: set[str], H: nx.DiGraph) -> dict[str, Any] | None:
        idx = [i for i, e in enumerate(var.edges) if e in blocked]
        if not idx:
            return None
        a, b = idx[0], idx[-1]
        u = self.edges[var.edges[a]].u
        v = self.edges[var.edges[b]].v
        blocked_len = sum(self.edges[e].length_m for e in var.edges[a : b + 1])

        # objazd: szukamy pary (węzeł przed blokadą, węzeł za blokadą) połączonej drogą
        # po pozostałych torach; cofamy się/idziemy do przodu po trasie maksymalnie o LOOKBACK krawędzi
        detour: dict[str, Any] = {"found": False}
        LOOKBACK = 12
        best: tuple[float, int, int, list[int]] | None = None
        for i in range(a, max(a - LOOKBACK, 0) - 1, -1):
            ui = self.edges[var.edges[i]].u
            if ui not in H:
                continue
            dist, paths = nx.single_source_dijkstra(H, ui, weight="length_m")
            for j in range(b, min(b + LOOKBACK, len(var.edges) - 1) + 1):
                vj = self.edges[var.edges[j]].v
                if vj in dist and vj != ui:
                    replaced = sum(self.edges[e].length_m for e in var.edges[i : j + 1])
                    extra = dist[vj] - replaced
                    if best is None or extra < best[0]:
                        best = (extra, i, j, paths[vj])
                    break
            if best is not None and best[1] == i and i < a:
                # dalsze cofanie tylko wydłuża; wystarczy pierwsze trafienie od strony blokady
                break
        if best is not None and best[0] <= self.cfg["max_detour_extra_m"]:
            extra, i, j, path = best
            path_edges = [H.edges[x, y]["id"] for x, y in zip(path, path[1:])]
            new_edges = var.edges[:i] + path_edges + var.edges[j + 1 :]
            new_nodes = {self.edges[e].u for e in new_edges} | {self.edges[e].v for e in new_edges}
            stop_nodes = {s["node"] for s in var.stops}
            skipped = [s["name"] for s in var.stops if s["node"] not in new_nodes]
            added = [self.net.node_info[n]["name"] for n in path if self.net.node_info[n]["kind"] == "tram_stop" and n not in stop_nodes and self.net.node_info[n].get("name")]
            via = [self.net.node_info[n]["name"] for n in path if self.net.node_info[n]["kind"] == "tram_stop" and self.net.node_info[n].get("name")]
            detour = {"found": True, "edges": path_edges, "from_index": i, "to_index": j, "extra_length_m": round(extra),
                      "skipped_stops": _uniq(map(_strip, skipped)), "added_stops": _uniq(map(_strip, added)), "via_names": _uniq(map(_strip, via))}

        side_a = self._turnbacks_side(var, a, forward=False)
        side_b = self._turnbacks_side(var, b, forward=True)

        # przystanki nieobsługiwane przy domyślnym (najbliższym) zawracaniu dla taboru jednokierunkowego
        unserved = self._unserved(var, a, b, side_a, side_b)
        short_variants = {_norm_stop(x.to): x.name for x in self.lines.lines[var.ref].variants if not x.incomplete}

        def enrich(side: dict[str, Any]) -> dict[str, Any]:
            for c in side["candidates"]:
                c["existing_variant"] = short_variants.get(_norm_stop(c["name"]))
            return side

        return {
            "ref": var.ref,
            "variant_id": var.id,
            "name": var.name,
            "from": _strip(var.from_),
            "to": _strip(var.to),
            "block_index": [a, b],
            "block_from_node": u,
            "block_to_node": v,
            "blocked_length_m": round(blocked_len),
            "detour": detour,
            "side_a": enrich(side_a),
            "side_b": enrich(side_b),
            "unserved_stops": unserved,
        }

    def _turnbacks_side(self, var: Variant, block_idx: int, forward: bool) -> dict[str, Any]:
        """Punkty zawracania przed blokadą (forward=False, patrząc od początku trasy) lub za nią."""
        radius = self.cfg["turnback_search_radius_m"]
        found: dict[str, dict[str, Any]] = {}
        dist = 0.0
        rng = range(block_idx + 1, len(var.edges)) if forward else range(block_idx - 1, -1, -1)
        for i in rng:
            e = self.edges[var.edges[i]]
            node = e.v if forward else e.u
            dist += e.length_m
            for t in self.turnbacks_by_node.get(node, []):
                if t.id not in found:
                    found[t.id] = {"id": t.id, "kind": t.kind, "name": t.name, "distance_to_block_m": round(dist),
                                   "for": "bidirectional" if t.for_bidirectional_only else "all", "node": node, "edge_index": i,
                                   "lat": t.lat, "lon": t.lon, "far": dist > radius, "verified": t.kind != "loop" or t.terminus}
        # własny terminus na tej stronie
        terminus = var.from_ if not forward else var.to
        cands = sorted(found.values(), key=lambda c: c["distance_to_block_m"])
        nearest_all = next((c for c in cands if c["for"] == "all"), None)
        nearest_bi = cands[0] if cands else None
        return {"terminus": _strip(terminus), "candidates": cands, "default_unidirectional": nearest_all, "default_bidirectional": nearest_bi}

    def _unserved(self, var: Variant, a: int, b: int, side_a: dict[str, Any], side_b: dict[str, Any]) -> list[str]:
        """Przystanki między domyślnymi punktami zawracania (dla taboru jednokierunkowego) a blokadą."""
        node_pos = {}
        for i, e in enumerate(var.edges):
            node_pos.setdefault(self.edges[e].u, i)
            node_pos.setdefault(self.edges[e].v, i + 1)
        lo = side_a["default_unidirectional"]["edge_index"] + 1 if side_a["default_unidirectional"] else 0
        hi = side_b["default_unidirectional"]["edge_index"] if side_b["default_unidirectional"] else len(var.edges)
        out = []
        for s in var.stops:
            p = node_pos.get(s["node"])
            if p is None:
                continue
            if lo <= p <= hi:
                out.append(_strip(s["name"]))
        return _uniq(out)

    # ------------------------------------------------------------------ składy
    def _analyze_vehicles(self, trams: list[dict[str, Any]], blocked: set[str], variant_results: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
        radius = self.cfg["position_match_radius_m"]
        out: list[dict[str, Any]] = []
        for t in trams:
            vid = t.get("variant_id")
            var = self._variant(vid) if vid else None
            rec = {k: t.get(k) for k in ("vehicle_code", "line", "headsign", "lat", "lon", "delay", "type", "bidirectional", "age_s")}
            if var is None or vid not in variant_results:
                rec.update(situation="unaffected", reason="wariant nie przechodzi przez blokadę" if var else "brak dopasowania do trasy")
                out.append(rec)
                continue
            res = variant_results[vid]
            match = self._project(t["lat"], t["lon"], var, radius)
            if match is None:
                rec.update(situation="unaffected", reason="pozycja poza trasą wariantu")
                out.append(rec)
                continue
            idx, along_in_edge = match
            a, b = res["block_index"]
            bidir = bool(t.get("bidirectional"))
            if idx < a:
                dist = (self.edges[var.edges[idx]].length_m - along_in_edge) + sum(self.edges[e].length_m for e in var.edges[idx + 1 : a])
                side = res["side_a"]
                tb = side["default_bidirectional"] if bidir else side["default_unidirectional"]
                usable = [c for c in side["candidates"] if c["edge_index"] >= idx and (bidir or c["for"] == "all")]
                rec.update(situation="approaching", distance_to_block_m=round(dist),
                           nearest_turnback=usable[0] if usable else None,
                           can_turn_before_block=bool(usable))
            elif idx > b:
                side = res["side_b"]
                usable = [c for c in side["candidates"] if c["edge_index"] >= idx and (bidir or c["for"] == "all")]
                rec.update(situation="beyond" if usable else "trapped_between",
                           nearest_turnback=usable[0] if usable else None,
                           distance_to_block_m=round(sum(self.edges[e].length_m for e in var.edges[b + 1 : idx]) + along_in_edge))
            else:
                rec.update(situation="on_block", distance_to_block_m=0)
            out.append(rec)
        order = {"trapped_between": 0, "on_block": 1, "approaching": 2, "beyond": 3, "unaffected": 4}
        out.sort(key=lambda r: (order[r["situation"]], r.get("distance_to_block_m", 0)))
        return out

    def _variant(self, vid: int) -> Variant | None:
        for line in self.lines.lines.values():
            for v in line.variants:
                if v.id == vid:
                    return v
        return None

    def _project(self, lat: float, lon: float, var: Variant, radius: float) -> tuple[int, float] | None:
        best = None
        for i, eid in enumerate(var.edges):
            d, along = point_to_polyline_m(lat, lon, self.edges[eid].geometry)
            if d <= radius and (best is None or d < best[0]):
                best = (d, i, along)
        return (best[1], best[2]) if best else None

    # ------------------------------------------------------------------ opis
    def _summary(self, affected: list[dict[str, Any]], vehicles: list[dict[str, Any]]) -> str:
        if not affected:
            return "Blokada nie dotyka żadnej linii."
        refs = sorted({r["ref"] for r in affected}, key=int)
        parts = [f"Linie: {', '.join(refs)}."]
        no_detour = sorted({r["ref"] for r in affected if not r["detour"]["found"]}, key=int)
        with_detour = sorted({r["ref"] for r in affected if r["detour"]["found"]}, key=int)
        if with_detour:
            parts.append(f"Objazd możliwy: {', '.join(with_detour)}.")
        if no_detour:
            parts.append(f"Brak objazdu, zawracanie: {', '.join(no_detour)}.")
        trapped = [v["vehicle_code"] for v in vehicles if v["situation"] == "trapped_between"]
        appr = [v for v in vehicles if v["situation"] == "approaching"]
        if trapped:
            parts.append(f"Składy bez możliwości zawrócenia: {', '.join(trapped)}.")
        if appr:
            parts.append(f"Jadą w stronę blokady: {len(appr)}.")
        return " ".join(parts)


def _strip(name: str | None) -> str:
    if not name:
        return ""
    parts = name.strip().split()
    if len(parts) > 1 and parts[-1].isdigit():
        parts = parts[:-1]
    return " ".join(parts)


def _uniq(items) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out
