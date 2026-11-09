"""FastAPI application: one backend for the desktop shell and the browser UI."""
from __future__ import annotations

import asyncio
import dataclasses
import secrets
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..acquisition.engine import AcquisitionEngine
from ..importers.lmu_duckdb import LmuDuckdb
from ..lmu import layout as L
from ..lmu.diagnostics import STATE_LABELS_IT, ConnState, build_report
from ..lmu.discovery import LmuInstall, find_install, is_lmu_process_running
from ..storage.catalog import Catalog

STATIC = Path(__file__).parent / "static"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}


def create_app(engine: AcquisitionEngine, catalog: Catalog, *, lan_enabled: bool = False,
               token: str | None = None, install: LmuInstall | None = None,
               allowed_import_dirs: list[Path] | None = None) -> FastAPI:
    """Security model:
    * default: server bound to loopback by the CLI; requests must carry a loopback Host header
      (DNS-rebinding protection) and, for WebSockets, a same-origin Origin.
    * LAN mode (explicit opt-in): every /api and /ws call requires the bearer token.
    """
    app = FastAPI(title="Race Engineer AI", version=__version__)
    token = token or secrets.token_urlsafe(24)
    app.state.token = token
    app.state.install = install

    def get_install() -> LmuInstall:
        if app.state.install is None:
            app.state.install = find_install()
        return app.state.install

    def authorized(host: str | None, auth: str | None, query_token: str | None) -> bool:
        hostname = (host or "").rsplit(":", 1)[0] if not (host or "").startswith("[") else (host or "").split("]")[0] + "]"
        if lan_enabled:
            supplied = (auth or "").removeprefix("Bearer ").strip() or (query_token or "")
            return secrets.compare_digest(supplied, token)
        return hostname in LOCAL_HOSTS

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if request.url.path.startswith("/api") and not authorized(
                request.headers.get("host"), request.headers.get("authorization"), request.query_params.get("token")):
            return JSONResponse({"detail": "forbidden"}, status_code=403)
        return await call_next(request)

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": __version__, "lan_enabled": lan_enabled, "platform": sys.platform}

    @app.get("/api/status")
    def status():
        d = engine.diagnostics()
        d["state_label"] = STATE_LABELS_IT[ConnState(d["state"])]
        d["context"] = dataclasses.asdict(engine.ctx) if engine.ctx else None
        return d

    @app.get("/api/live")
    def live():
        s = engine.latest
        return s.to_json() if s else {"values": None}

    @app.websocket("/ws/live")
    async def ws_live(ws: WebSocket):
        if not authorized(ws.headers.get("host"), ws.headers.get("authorization"), ws.query_params.get("token")):
            await ws.close(code=4403)
            return
        origin = ws.headers.get("origin")
        if origin and not lan_enabled and (origin.split("//")[-1].rsplit(":", 1)[0] not in LOCAL_HOSTS):
            await ws.close(code=4403)
            return
        await ws.accept()
        try:
            while True:
                s = engine.latest
                d = engine.diagnostics()
                d["state_label"] = STATE_LABELS_IT[ConnState(d["state"])]
                await ws.send_json({"sample": s.to_json() if s else None, "status": d,
                                    "context": dataclasses.asdict(engine.ctx) if engine.ctx else None})
                await asyncio.sleep(0.1)
        except Exception:
            return

    @app.get("/api/diagnostics/report")
    def report():
        return build_report(get_install(), is_lmu_process_running(), engine.mapping_size, engine.mapping_error,
                            engine.ctx.game_version if engine.ctx else None, sys.platform,
                            synthetic=engine.synthetic).to_json()

    @app.get("/api/lmu/install")
    def lmu_install():
        return dataclasses.asdict(get_install())

    @app.get("/api/layout")
    def layout_info():
        return {"source": L.LAYOUT_SOURCE, "mapping_name": L.LMU_SHARED_MEMORY_NAME, "expected_size": L.MAPPING_SIZE,
                "verified_against_real_lmu": False}

    @app.get("/api/sessions")
    def sessions():
        return catalog.list_sessions()

    def _allowed(p: Path) -> bool:
        roots = list(allowed_import_dirs or [])
        if get_install().telemetry_dir:
            roots.append(Path(get_install().telemetry_dir))
        rp = p.resolve()
        return any(rp.is_relative_to(r.resolve()) for r in roots) and rp.suffix == ".duckdb"

    @app.get("/api/duckdb/files")
    def duck_files():
        return get_install().duckdb_files

    @app.get("/api/duckdb/inspect")
    def duck_inspect(path: str):
        p = Path(path)
        if not _allowed(p) or not p.is_file():
            raise HTTPException(404, "file not in the LMU telemetry folder")
        with LmuDuckdb(p, copy_first=True) as d:
            return dataclasses.asdict(d.inspect())

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    return app
