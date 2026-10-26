"""Serwer FastAPI: API sieci torów, linii, pozycji na żywo + statyczny frontend.

    python -m backend.app
"""
from __future__ import annotations

import threading
import time
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel

from backend.graph import ROOT, load_config, load_network
from backend.incidents import IncidentAnalyzer
from backend.lines import Fleet, Lines
from backend.live import LivePoller
from backend.store import Store

_state: dict = {}


def build_state() -> None:
    cfg = load_config()
    net = load_network()
    lines = Lines(net)
    fleet = Fleet()
    store = Store()
    poller = LivePoller(cfg["ztm"]["gps_positions"], cfg["ztm"]["poll_interval_s"], cfg["ztm"]["history_retention_h"], store, fleet, lines)
    _state.update(cfg=cfg, net=net, geojson=net.to_geojson(), lines=lines, fleet=fleet, store=store, poller=poller,
                  analyzer=IncidentAnalyzer(net, lines, cfg))


@asynccontextmanager
async def lifespan(app: FastAPI):
    build_state()
    _state["poller"].start()
    yield
    _state["poller"].stop()
    _state["store"].close()


app = FastAPI(title="Tramdispatch Gdańsk", version="0.2.0", lifespan=lifespan)


@app.get("/api/network")
def api_network():
    return JSONResponse(_state["geojson"])


@app.post("/api/network/reload")
def api_network_reload():
    """Przeładowuje graf i linie po edycji data/overrides.json."""
    net = load_network()
    _state.update(net=net, geojson=net.to_geojson(), lines=Lines(net))
    _state["poller"].lines = _state["lines"]
    _state["analyzer"] = IncidentAnalyzer(net, _state["lines"], _state["cfg"])
    return {"ok": True, "report": net.report.to_dict()}


@app.get("/api/lines")
def api_lines():
    return _state["lines"].to_dict()


@app.get("/api/live")
def api_live():
    return _state["poller"].snapshot


@app.get("/api/history")
def api_history(vehicle: str | None = None, minutes: int = Query(60, ge=1, le=1440), at: int | None = None):
    store: Store = _state["store"]
    if vehicle:
        return {"vehicle_code": vehicle, "trail": store.trail(vehicle, int(time.time()) - minutes * 60)}
    if at is not None:
        trams = store.snapshot_at(at)
        fleet: Fleet = _state["fleet"]
        for t in trams:
            t.update(fleet.lookup(t["vehicle_code"]))
            t["age_s"] = max(0, at - t["ts"])
        return {"last_update": at, "trams": trams}
    lo, hi = store.bounds()
    return {"from": lo, "to": hi}


# ------------------------------------------------------------------- awarie
class IncidentIn(BaseModel):
    blocked_edges: list[str]
    both_directions: bool = True
    location_text: str = ""
    cause: str = "inne"
    expected_until: str | None = None
    note: str = ""


class IncidentPatch(BaseModel):
    status: str | None = None
    blocked_edges: list[str] | None = None
    both_directions: bool | None = None
    location_text: str | None = None
    cause: str | None = None
    expected_until: str | None = None
    note: str | None = None
    decision: dict | None = None


def _analyze(blocked: list[str], both: bool) -> dict:
    return _state["analyzer"].analyze(blocked, both, _state["poller"].snapshot["trams"])


@app.post("/api/incidents/preview")
def api_incident_preview(body: IncidentIn):
    """Analiza bez zapisu: do podglądu przed zgłoszeniem."""
    return _analyze(body.blocked_edges, body.both_directions)


@app.post("/api/incidents")
def api_incident_create(body: IncidentIn):
    now = int(time.time())
    inc = {
        "id": time.strftime("%Y%m%d-%H%M%S", time.localtime(now)),
        "created_at": now,
        "status": "active",
        "resolved_at": None,
        "blocked_edges": body.blocked_edges,
        "both_directions": body.both_directions,
        "location_text": body.location_text,
        "cause": body.cause,
        "expected_until": body.expected_until,
        "note": body.note,
        "decision": {},
        "analysis": _analyze(body.blocked_edges, body.both_directions),
    }
    _state["store"].save_incident(inc)
    return inc


@app.get("/api/incidents")
def api_incident_list(status: str | None = None):
    return {"incidents": _state["store"].list_incidents(status)}


@app.get("/api/incidents/{inc_id}")
def api_incident_get(inc_id: str, refresh: bool = True):
    inc = _state["store"].get_incident(inc_id)
    if not inc:
        raise HTTPException(404, "nie ma takiej awarii")
    if refresh and inc["status"] == "active":
        inc["analysis"] = _analyze(inc["blocked_edges"], inc["both_directions"])
    return inc


@app.patch("/api/incidents/{inc_id}")
def api_incident_patch(inc_id: str, body: IncidentPatch):
    inc = _state["store"].get_incident(inc_id)
    if not inc:
        raise HTTPException(404, "nie ma takiej awarii")
    changes = body.model_dump(exclude_none=True)
    reanalyze = any(k in changes for k in ("blocked_edges", "both_directions"))
    inc.update(changes)
    if changes.get("status") == "resolved" and not inc.get("resolved_at"):
        inc["resolved_at"] = int(time.time())
    if reanalyze:
        inc["analysis"] = _analyze(inc["blocked_edges"], inc["both_directions"])
    _state["store"].save_incident(inc)
    return inc


@app.get("/api/health")
def api_health():
    net = _state["net"]
    return {"graph": {"nodes": net.report.nodes, "edges": net.report.edges, "turnbacks": len(net.turnbacks)},
            "live": _state["poller"].health(), "server_time": int(time.time())}


app.mount("/", StaticFiles(directory=Path(ROOT / "frontend"), html=True), name="frontend")


def main() -> None:
    cfg = load_config()["server"]
    url = f"http://{cfg['host']}:{cfg['port']}"
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=cfg["host"], port=cfg["port"], log_level="info")


if __name__ == "__main__":
    main()
