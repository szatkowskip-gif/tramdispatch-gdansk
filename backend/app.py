"""Serwer FastAPI: API sieci torów + statyczny frontend.

    python -m backend.app
"""
from __future__ import annotations

import threading
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.graph import ROOT, load_config, load_network

app = FastAPI(title="Tramdispatch Gdańsk", version="0.1.0")
_state: dict = {}


def network():
    if "net" not in _state:
        _state["net"] = load_network()
        _state["geojson"] = _state["net"].to_geojson()
    return _state["net"]


@app.get("/api/network")
def api_network():
    network()
    return JSONResponse(_state["geojson"])


@app.post("/api/network/reload")
def api_network_reload():
    """Przeładowuje graf po edycji data/overrides.json."""
    _state.clear()
    return {"ok": True, "report": network().report.to_dict()}


@app.get("/api/health")
def api_health():
    net = network()
    return {"graph": {"nodes": net.report.nodes, "edges": net.report.edges, "turnbacks": len(net.turnbacks)}}


app.mount("/", StaticFiles(directory=Path(ROOT / "frontend"), html=True), name="frontend")


def main() -> None:
    cfg = load_config()["server"]
    url = f"http://{cfg['host']}:{cfg['port']}"
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=cfg["host"], port=cfg["port"], log_level="info")


if __name__ == "__main__":
    main()
