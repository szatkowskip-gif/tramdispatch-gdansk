"""Komunikaty z szablonów Jinja2 (bez modeli językowych).

Wejście: zapisana awaria (z analizą i decyzją dyspozytora). Wyjście: pięć tekstów:
pasażerski PL, pasażerski EN, służbowy dla motorniczych, o przywróceniu ruchu PL i EN.
Szablony w data/templates/*.j2, słowniki etykiet poniżej.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from backend.graph import DATA

TEMPLATES = DATA / "templates"

CAUSE = {
    "awaria sieci trakcyjnej": ("awaria sieci trakcyjnej", "overhead line failure"),
    "awaria składu": ("awaria tramwaju", "tram breakdown"),
    "kolizja": ("kolizja", "collision"),
    "uszkodzenie toru": ("uszkodzenie torowiska", "track damage"),
    "zdarzenie z pieszym": ("zdarzenie drogowe", "road incident"),
    "brak zasilania": ("brak zasilania", "power outage"),
    "inne": ("utrudnienia", "disruption"),
}
STRATEGY_LABEL = {"detour": "objazd", "shorten": "trasa skrócona", "shuttle": "wahadło po jednym torze", "suspended": "zawieszona"}


def _env() -> Environment:
    return Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape([]), trim_blocks=True, lstrip_blocks=True)


def _join(items: list[str], lang: str) -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    last = " i " if lang == "pl" else " and "
    return ", ".join(items[:-1]) + last + items[-1]


def default_strategy(line: dict[str, Any]) -> str:
    if line["detour"]["found"]:
        return "detour"
    if line.get("shuttle", {}).get("possible"):
        return "shuttle"
    return "shorten"


def line_context(ref: str, variants: list[dict[str, Any]], strategy: str) -> dict[str, Any]:
    """Łączy warianty (oba kierunki) jednej linii w jeden opis do komunikatu."""
    main = max(variants, key=lambda v: len(v["unserved_stops"]))
    unserved: list[str] = []
    for v in variants:
        for s in v["unserved_stops"]:
            if s not in unserved:
                unserved.append(s)

    def tb(side: dict[str, Any]) -> str:
        c = side.get("default_unidirectional") or side.get("default_bidirectional")
        return c["name"] if c else side.get("terminus", "")

    ctx: dict[str, Any] = {"ref": ref, "strategy": strategy, "from": main["from"], "to": main["to"], "unserved": unserved}
    if strategy == "detour" and main["detour"]["found"]:
        d = main["detour"]
        ctx.update(via=d["via_names"], skipped=d["skipped_stops"])
        ctx["pl"] = "kursuje objazdem" + (f" przez {_join(d['via_names'], 'pl')}" if d["via_names"] else "") + (f", z pominięciem przystanków {_join(d['skipped_stops'], 'pl')}" if d["skipped_stops"] else "")
        ctx["en"] = "runs via a diversion" + (f" through {_join(d['via_names'], 'en')}" if d["via_names"] else "") + (f", not serving {_join(d['skipped_stops'], 'en')}" if d["skipped_stops"] else "")
        ctx["unserved"] = d["skipped_stops"]
    elif strategy == "shuttle" and main.get("shuttle", {}).get("possible"):
        sh = main["shuttle"]
        a, b = sh["crossover_before"]["name"], sh["crossover_after"]["name"]
        ctx.update(shuttle=sh)
        ctx["pl"] = f"na odcinku {a} – {b} kursuje po jednym torze (ruch wahadłowy), możliwe opóźnienia" + (f"; na przystankach {_join(sh['stops_opposite_platform'], 'pl')} tramwaje mogą zatrzymywać się po przeciwnej stronie" if sh["stops_opposite_platform"] else "")
        ctx["en"] = f"runs on a single track between {a} and {b} (shuttle operation), delays possible" + (f"; at {_join(sh['stops_opposite_platform'], 'en')} trams may stop at the opposite platform" if sh["stops_opposite_platform"] else "")
        ctx["unserved"] = []
    elif strategy == "suspended":
        ctx["pl"] = "zawieszona"
        ctx["en"] = "suspended"
    else:
        # skrócenie: od każdego krańca do najbliższego punktu zawracania
        fwd = variants[0]
        back = next((v for v in variants[1:] if v["from"] == fwd["to"]), None)
        a_term, a_tb = fwd["side_a"]["terminus"], tb(fwd["side_a"])
        b_term, b_tb = fwd["side_b"]["terminus"], tb(fwd["side_b"])
        parts_pl, parts_en = [], []
        if a_tb and a_tb != a_term:
            parts_pl.append(f"{a_term} – {a_tb}"); parts_en.append(f"{a_term} – {a_tb}")
        if b_tb and b_tb != b_term:
            parts_pl.append(f"{b_tb} – {b_term}"); parts_en.append(f"{b_tb} – {b_term}")
        ctx.update(segments=parts_pl)
        if parts_pl:
            ctx["pl"] = "kursuje na skróconej trasie " + _join(parts_pl, "pl")
            ctx["en"] = "runs on a shortened route " + _join(parts_en, "en")
        else:
            ctx["pl"] = "kursuje na skróconej trasie"
            ctx["en"] = "runs on a shortened route"
        ctx["turnback_a"], ctx["turnback_b"] = a_tb, b_tb
    return ctx


def build_context(inc: dict[str, Any]) -> dict[str, Any]:
    an = inc["analysis"]
    decision = inc.get("decision") or {}
    strategies: dict[str, str] = decision.get("lines", {})
    by_ref: dict[str, list[dict[str, Any]]] = {}
    for l in an["affected_lines"]:
        by_ref.setdefault(l["ref"], []).append(l)
    lines = []
    for ref in sorted(by_ref, key=int):
        strat = strategies.get(ref) or default_strategy(by_ref[ref][0])
        lines.append(line_context(ref, by_ref[ref], strat))
    unserved: list[str] = []
    for l in lines:
        for s in l["unserved"]:
            if s not in unserved:
                unserved.append(s)
    cause_pl, cause_en = CAUSE.get(inc.get("cause", "inne"), CAUSE["inne"])
    started = time.strftime("%H:%M", time.localtime(inc["created_at"]))
    return {
        "location": inc.get("location_text") or ", ".join(an.get("blocked_names", [])),
        "cause_pl": cause_pl, "cause_en": cause_en, "cause_raw": inc.get("cause", ""),
        "expected": inc.get("expected_until") or "",
        "started": started,
        "now": time.strftime("%d.%m.%Y %H:%M"),
        "lines": lines,
        "line_refs": [l["ref"] for l in lines],
        "unserved": unserved,
        "replacement_bus": decision.get("replacement_bus", ""),
        "note": decision.get("note", ""),
        "both_directions": inc.get("both_directions", True),
        "vehicles": [v for v in an.get("affected_vehicles", []) if v["situation"] != "unaffected"],
        "strategy_label": STRATEGY_LABEL,
    }


def render_all(inc: dict[str, Any]) -> dict[str, str]:
    env = _env()
    ctx = build_context(inc)
    out = {}
    for name in ("passenger_pl", "passenger_en", "drivers", "restored_pl", "restored_en"):
        out[name] = env.get_template(f"{name}.j2").render(**ctx).strip() + "\n"
    return out
