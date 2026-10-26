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

from backend.graph import ROOT, load_config, load_network
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
    _state.update(cfg=cfg, net=net, geojson=net.to_geojson(), lines=lines, fleet=fleet, store=store, poller=poller)


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
