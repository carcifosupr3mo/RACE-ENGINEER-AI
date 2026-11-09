"""FastAPI application: one backend for the desktop shell and the browser UI."""
from __future__ import annotations

import asyncio
import dataclasses

import numpy as np
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
from ..analysis.align import align_lap
from ..analysis.compare import compare, consistency
from ..analysis.corners import apply_profile, detect_corners
from ..analysis.laps import load_session, segment_laps, summarize
from ..importers.session_import import import_lmu_duckdb
from ..storage.catalog import Catalog
from ..storage.paths import data_dir

def clean(o):
    """NaN/inf -> None (= 'not available') recursively, so JSON never carries invented or invalid numbers."""
    if isinstance(o, float):
        return o if np.isfinite(o) else None
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    return o


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

    data_dir_provider = lambda: engine.data_root or data_dir()

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

    # ------------------------------------------------------------------ analysis (Phase 2/3)
    cache: dict = {}

    def _session(sid: str):
        row = catalog.get_session(sid)
        if not row:
            raise HTTPException(404, "unknown session")
        if row["status"] == "recording":
            raise HTTPException(409, "session still recording")
        key = (sid, row["samples"])
        if key not in cache:
            sd = load_session(row["data_path"], row["track_length_m"] or 0.0)
            cache[key] = (sd, segment_laps(sd))
        return row, *cache[key]

    @app.get("/api/sessions/{sid}/laps")
    def laps(sid: str):
        row, sd, ls = _session(sid)
        return clean({"session": row, "laps": [l.to_json() for l in ls], "summary": summarize(ls), "provenance": sd.provenance})

    def _ref(sd, ls, ref: int | None):
        ok = [l for l in ls if l.valid_for_analysis and l.time_s]
        if not ok:
            raise HTTPException(422, "no valid laps in this session")
        pick = next((l for l in ok if l.number == ref), None) if ref else min(ok, key=lambda l: l.time_s)
        if pick is None:
            raise HTTPException(422, "reference lap is not a valid lap")
        return pick

    @app.get("/api/sessions/{sid}/corners")
    def corners(sid: str, ref: int | None = None):
        row, sd, ls = _session(sid)
        al = align_lap(sd, _ref(sd, ls, ref))
        prof = catalog.get_track_profile(row["track"] or "")
        return clean({"provisional": prof is None, "ref_lap": al.number, "corners": [c.to_json() for c in apply_profile(detect_corners(al), prof)]})

    @app.get("/api/sessions/{sid}/trace")
    def trace(sid: str, laps: str, step: int = 5):
        """Distance-aligned channels for the requested laps (comma separated), every `step` metres."""
        row, sd, ls = _session(sid)
        out = {}
        for n in [int(x) for x in laps.split(",") if x]:
            lap = next((l for l in ls if l.number == n), None)
            if lap is None:
                raise HTTPException(404, f"lap {n} not found")
            a = align_lap(sd, lap)
            sl = slice(None, None, max(1, step))
            f = lambda arr: [None if not np.isfinite(x) else round(float(x), 3) for x in arr[sl]]
            out[n] = {"quality": a.quality, "t": f(a.t), **{k: f(v) for k, v in a.ch.items()}}
        g = np.arange(0, row["track_length_m"], 1.0)[::max(1, step)]
        return {"distance_m": [float(x) for x in g], "laps": out, "provenance": sd.provenance}

    @app.get("/api/sessions/{sid}/compare")
    def compare_api(sid: str, lap: int, ref: int | None = None):
        row, sd, ls = _session(sid)
        rl = _ref(sd, ls, ref)
        target = next((l for l in ls if l.number == lap), None)
        if target is None or not target.valid_for_analysis:
            raise HTTPException(422, "lap is not a valid lap")
        ra, la = align_lap(sd, rl), align_lap(sd, target)
        if not (ra.quality["ok"] and la.quality["ok"]):
            raise HTTPException(422, {"error": "alignment quality too low", "lap": la.quality, "ref": ra.quality})
        cs = apply_profile(detect_corners(ra), catalog.get_track_profile(row["track"] or ""))
        res = compare(la, ra, cs)
        res["corners_provisional"] = all(c.provisional for c in cs)
        res["provenance"] = sd.provenance
        return clean(res)

    @app.get("/api/sessions/{sid}/consistency")
    def consistency_api(sid: str):
        row, sd, ls = _session(sid)
        ok = [l for l in ls if l.valid_for_analysis]
        if len(ok) < 3:
            raise HTTPException(422, "need at least 3 valid laps")
        al = [align_lap(sd, l) for l in ok]
        return clean({"laps": [l.number for l in ok], "corners": consistency(al, detect_corners(al[0]))})

    @app.get("/api/tracks/profile")
    def get_profile(track: str):
        return {"track": track, "corners": catalog.get_track_profile(track)}

    @app.put("/api/tracks/profile")
    def put_profile(track: str, corners: list[dict]):
        need = {"id", "apex_m", "entry_m", "exit_m"}
        if any(not need <= set(c) for c in corners):
            raise HTTPException(422, f"each corner needs {sorted(need)}")
        catalog.put_track_profile(track, corners)
        return {"ok": True, "corners": len(corners)}

    @app.post("/api/import/duckdb")
    def import_duck(path: str):
        p = Path(path)
        if not _allowed(p) or not p.is_file():
            raise HTTPException(404, "file not in the LMU telemetry folder")
        try:
            return import_lmu_duckdb(p, catalog, data_dir_provider())
        except ValueError as e:
            raise HTTPException(422, str(e))

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    dist = Path(__file__).parent / "webdist"
    if dist.is_dir():
        app.mount("/app", StaticFiles(directory=dist, html=True), name="webapp")

    @app.get("/diag")
    def diag():
        return FileResponse(STATIC / "index.html")

    @app.get("/")
    def index():
        if dist.is_dir():
            from fastapi.responses import RedirectResponse
            return RedirectResponse("/app/")
        return FileResponse(STATIC / "index.html")

    return app
