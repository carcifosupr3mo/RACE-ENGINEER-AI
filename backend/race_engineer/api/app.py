"""FastAPI application: one backend for the desktop shell and the browser UI."""
from __future__ import annotations

import asyncio
import dataclasses

import numpy as np
import logging
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
from ..analysis import driving as drv_an
from ..analysis.session_mode import classify as classify_session
from ..live.engineer import LiveEngineer
from ..analysis.corners import apply_profile, detect_corners
from ..ai import chat as ai_chat
from ..analysis import driver as drv
from ..analysis.tyrefuel import fuel_report, tyre_report
from ..analysis.laps import load_session, segment_laps, summarize
from ..setup import advisor as setup_advisor
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


def _lan_ips() -> list[str]:
    """Private IPv4 addresses of this PC (no packet is sent). Used only to print the LAN URL of the Driving Display."""
    import socket
    found: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sk:
            sk.connect(("10.255.255.255", 1))
            found.append(sk.getsockname()[0])
    except OSError:
        pass
    try:
        found += [i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        pass
    return [ip for ip in dict.fromkeys(found) if not ip.startswith(("127.", "169.254.", "0."))]


log = logging.getLogger("race_engineer.api")
STATIC = Path(__file__).parent / "static"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}


def create_app(engine: AcquisitionEngine, catalog: Catalog, *, lan_enabled: bool = False,
               token: str | None = None, install: LmuInstall | None = None,
               allowed_import_dirs: list[Path] | None = None, webdist: Path | None = None, live_options: dict | None = None) -> FastAPI:
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

    def cross_site(origin: str | None, fetch_site: str | None) -> bool:
        """Loopback mode has no token, so a web page open in the user's browser could call the API (CSRF). Browsers label such
        requests with a foreign Origin / Sec-Fetch-Site: cross-site; the app's own pages and non-browser clients do not."""
        if lan_enabled:
            return False                  # every call already needs the token, which a foreign page does not have
        if origin and origin.split("//")[-1].rsplit(":", 1)[0] not in LOCAL_HOSTS:
            return True
        return (fetch_site or "").lower() == "cross-site"

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if request.url.path.startswith("/api") and (not authorized(
                request.headers.get("host"), request.headers.get("authorization"), request.query_params.get("token"))
                or cross_site(request.headers.get("origin"), request.headers.get("sec-fetch-site"))):
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
        if cross_site(ws.headers.get("origin"), None):
            await ws.close(code=4403)
            return
        await ws.accept()
        try:
            last_seq = live.seq
            while True:
                s = engine.latest
                d = engine.diagnostics()
                d["state_label"] = STATE_LABELS_IT[ConnState(d["state"])]
                ev = live.events_since(last_seq)
                if ev:
                    last_seq = ev[-1]["seq"]
                # "engineer" = the SAME shared state served by /api/engineer/state (map excluded: fetched when map_version changes)
                await ws.send_json(clean({"sample": s.to_json() if s else None, "status": d,
                                          "context": dataclasses.asdict(engine.ctx) if engine.ctx else None,
                                          "engineer": live.snapshot(), "events": ev}))
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

    def _aligned(sd, lap):
        """align_lap + a quality gate with a message a person can act on (the raw numbers go to the log)."""
        a = align_lap(sd, lap)
        if not a.quality["ok"]:
            log.warning("lap %s not usable for analysis: %s", lap.number, a.quality)
            raise HTTPException(422, f"Il giro {lap.number} non ha dati di posizione sufficienti per l'analisi "
                                     f"(copertura {a.quality['coverage']:.0%} del circuito). Scegli un altro giro.")
        return a

    @app.get("/api/sessions/{sid}/corners")
    def corners(sid: str, ref: int | None = None):
        row, sd, ls = _session(sid)
        al = _aligned(sd, _ref(sd, ls, ref))
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
        ra, la = _aligned(sd, rl), _aligned(sd, target)
        cs = apply_profile(detect_corners(ra), catalog.get_track_profile(row["track"] or ""))
        res = compare(la, ra, cs)
        res["corners_provisional"] = all(c.provisional for c in cs)
        res["provenance"] = sd.provenance
        return clean(res)

    @app.get("/api/sessions/{sid}/driving")
    def driving_api(sid: str, lap: int, ref: int | None = None):
        """Driving analysis of a recorded lap vs the reference lap: the SAME ``driving.analyse`` the live engineer runs."""
        row, sd, ls = _session(sid)
        rl = _ref(sd, ls, ref)
        target = next((l for l in ls if l.number == lap), None)
        if target is None or not target.valid_for_analysis:
            raise HTTPException(422, "lap is not a valid lap")
        ra, la = _aligned(sd, rl), _aligned(sd, target)
        n_valid = len([l for l in ls if l.valid_for_analysis and l.time_s])
        reliability = 0.0 if n_valid < 2 else min(1.0, 0.25 * (n_valid - 1))
        cs = apply_profile(detect_corners(ra), catalog.get_track_profile(row["track"] or ""))
        res = drv_an.analyse(la, ra, cs, reliability=max(0.15, reliability))
        res["corners_provisional"] = all(c.provisional for c in cs)
        res["session_mode"] = classify_session(row["session_type"])
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

    @app.get("/api/sessions/{sid}/fuel")
    def fuel_api(sid: str, target_laps: int | None = None, margin_laps: float = 0.5):
        row, sd, ls = _session(sid)
        return clean(fuel_report(sd, ls, target_laps, margin_laps))

    @app.get("/api/sessions/{sid}/tyres")
    def tyres_api(sid: str):
        row, sd, ls = _session(sid)
        return clean(tyre_report(sd, ls))

    @app.get("/api/driver/history")
    def driver_history(period: str = "week", include_synthetic: bool = False):
        if period not in ("day", "week", "month"):
            raise HTTPException(422, "period must be day|week|month")
        return clean(drv.history(catalog, include_synthetic, period))

    @app.get("/api/driver/goals")
    def goals():
        return clean([drv.evaluate_goal(catalog, g) for g in catalog.list_goals()])

    @app.post("/api/driver/goals")
    def add_goal(track: str, metric: str, target: float, vehicle: str = "", note: str | None = None):
        if metric not in ("best_lap_s", "lap_std_s", "slow_corner_loss_s"):
            raise HTTPException(422, "unknown metric")
        base = None
        rows = [r for r in catalog.list_sessions(True) if r["track"] == track and r["status"] != "recording" and r["samples"]]
        vals = []
        for r in rows:
            st = drv.session_stats(r)
            v = {"best_lap_s": st["summary"]["best_time_s"], "lap_std_s": st["summary"]["std_time_s"]}.get(metric)
            if v is not None:
                vals.append(v)
        base = min(vals) if vals else None
        return {"id": catalog.add_goal(track, vehicle, metric, target, base, note), "baseline": base}

    @app.get("/api/sessions/{sid}/training")
    def training(sid: str):
        _session(sid)
        return clean(drv.training_plan(catalog, sid))

    @app.post("/api/chat")
    def chat(body: dict):
        sid, q = body.get("session_id"), (body.get("question") or "").strip()
        if not sid or not q:
            raise HTTPException(422, "session_id and question are required")
        _session(sid)
        return clean(ai_chat.ask(catalog, sid, q, conversation=body.get("conversation", "default")))

    @app.get("/api/chat/history")
    def chat_history(conversation: str = "default"):
        return catalog.list_messages(conversation)

    @app.get("/api/ai/settings")
    def ai_get():
        cfg = catalog.get_setting("ai") or {"enabled": False, "providers": []}
        return {**cfg, "note": "API keys are never stored: set the environment variable named in api_key_env."}

    def endurance():
        svc = getattr(app.state, "endurance", None)
        if svc is None:
            from ..endurance.service import EnduranceService
            svc = app.state.endurance = EnduranceService(engine, catalog, data_dir_provider())
        return svc

    if engine.data_root is not None:
        endurance()          # start local endurance analysis together with the app (never touches acquisition on failure)

    # ------------------------------------------------------------------ unified live engineer (ONE state for dashboard + Driving Display)
    def _endurance_snapshot():
        svc = getattr(app.state, "endurance", None)
        p = getattr(svc, "current", None)
        return p.det.snapshot() if p is not None else None

    def _ai_queue():
        svc = getattr(app.state, "endurance", None)
        return getattr(svc, "queue", None)

    live = app.state.live = LiveEngineer(engine, catalog, engine.data_root, endurance_snapshot=_endurance_snapshot, ai_queue=_ai_queue,
                                          **(live_options or {}))

    @app.get("/api/engineer/state")
    def engineer_state(full: bool = False):
        return clean(live.snapshot(full=full))

    @app.get("/api/engineer/map")
    def engineer_map():
        return clean(live.map_payload())

    @app.get("/api/engineer/events")
    def engineer_events(since: int = 0):
        return {"events": clean(live.events_since(since)), "seq": live.seq}

    @app.get("/api/engineer/reference")
    def engineer_reference():
        return clean(live.ref.to_json() if live.ref else {"laps": [], "reliability": {"level": "nessuno", "learning": True}})

    @app.get("/api/engineer/status")
    def engineer_status():
        return live.status()

    # ---- coaching memory / end-of-lap review (same engine, same catalog database)
    def _coach_scope():
        return live.coach.track, live.coach.vehicle, live.coach.synthetic

    @app.get("/api/coach/review")
    def coach_review(lap: int | None = None):
        with live._lock:
            rv = live.reviews.get(lap) if lap is not None else live.last_review
        if rv is None:
            raise HTTPException(404, "nessuna revisione di giro disponibile")
        return clean(rv)

    @app.get("/api/coach/summary")
    def coach_summary():
        with live._lock:
            return clean(live.coach.mem.summary(*_coach_scope()))

    @app.get("/api/coach/tips")
    def coach_tips(limit: int = 30):
        with live._lock:
            return clean({"tips": live.coach.mem.recent_tips(*_coach_scope(), limit=max(1, min(limit, 200)))})

    @app.get("/api/coach/progress")
    def coach_progress():
        with live._lock:
            return clean({"laps": live.coach.mem.progress(*_coach_scope())})

    @app.get("/api/coach/prefs")
    def coach_prefs_get():
        return live.coach.prefs()

    @app.put("/api/coach/prefs")
    def coach_prefs_put(body: dict):
        with live._lock:
            return live.coach.mem.set_prefs(body)

    @app.get("/api/engineer/checklist")
    def engineer_checklist(format: str = "json"):
        """Live-test checklist built from the SHARED state (same snapshot/map the dashboard and display use). Sanitised: no driver name, paths or keys."""
        from fastapi.responses import PlainTextResponse
        from ..live import checklist as _ck
        from ..lmu.verify import sanitize_obj
        with live._lock:
            coach_sum = live.coach.mem.summary(live.coach.track, live.coach.vehicle, live.coach.synthetic) if live.coach.sid else None
        rep = _ck.build(snapshot=live.snapshot(), map_payload=live.map_payload(), engine_diag=engine.diagnostics(),
                        lmu_process=None if engine.synthetic else is_lmu_process_running(), live_status=live.status(), app_version=__version__,
                        coach=coach_sum)
        rep = sanitize_obj(clean(rep))
        return PlainTextResponse(_ck.to_markdown(rep), media_type="text/markdown; charset=utf-8") if format == "md" else rep

    @app.get("/api/display/info")
    def display_info(request: Request):
        """How to open the Driving Display (second monitor on this PC, or LAN browser). The page is served by this same backend."""
        port = request.url.port or (443 if request.url.scheme == "https" else 80)
        q = f"?token={token}" if lan_enabled else ""
        urls = [f"http://{ip}:{port}/driving-display{q}" for ip in _lan_ips()] if lan_enabled else []
        return {"path": "/driving-display", "local_url": f"http://127.0.0.1:{port}/driving-display", "lan_enabled": lan_enabled, "lan_urls": urls,
                "how_to_enable_lan": None if lan_enabled else "avvia con --lan (il token di accesso viene mostrato all'avvio)",
                "websocket": "/ws/live (campo 'engineer')", "api": "/api/engineer/state"}

    @app.get("/api/endurance/status")
    def endurance_status():
        return clean(endurance().status())

    @app.get("/api/endurance/summaries")
    def endurance_summaries(session_id: str | None = None, kind: str | None = None, limit: int = 50):
        return clean(endurance().mem.summaries(session_id, kind, min(limit, 500)))

    @app.get("/api/endurance/events")
    def endurance_events(session_id: str, since: int = 0):
        return clean(endurance().mem.events_since(session_id, since))

    @app.get("/api/ai/providers")
    def ai_providers():
        from ..ai.providers.chain import get_manager
        from ..ai.providers.credentials import key_status
        m = get_manager((catalog.get_setting("ai") or {}).get("free_multi"), data_dir_provider())
        return clean({"keys": {p: key_status(p) for p in ("nvidia", "groq")}, **m.status()})

    @app.put("/api/ai/providers/key")
    def ai_key_put(body: dict):
        """Stores the key ONLY in the OS credential store (Windows Credential Manager). The key is never echoed, logged or kept."""
        from ..ai.providers.credentials import store_key, key_status
        prov = body.get("provider")
        if prov not in ("nvidia", "groq") or not isinstance(body.get("key"), str) or len(body["key"]) < 8:
            raise HTTPException(422, "provider must be nvidia|groq and key a non-empty string")
        res = store_key(prov, body["key"])
        body["key"] = None
        return {**res, "status": key_status(prov)}

    @app.delete("/api/ai/providers/key/{provider}")
    def ai_key_delete(provider: str):
        from ..ai.providers.credentials import delete_key, key_status
        if provider not in ("nvidia", "groq"):
            raise HTTPException(404)
        return {"deleted": delete_key(provider), "status": key_status(provider)}

    @app.post("/api/ai/providers/test")
    def ai_providers_test():
        from ..ai.providers import selftest
        from ..ai.providers.chain import get_manager
        m = get_manager((catalog.get_setting("ai") or {}).get("free_multi"), data_dir_provider())
        return clean(selftest.run(m))

    @app.put("/api/ai/settings")
    def ai_put(cfg: dict):
        if cfg.get("mode") == "free_multi" and any(k in str(cfg) for k in ("api_key\"", "'api_key'", "'key'", "'token'")):
            raise HTTPException(422, "do not send secrets in settings")
        for p in cfg.get("providers", []):
            if p.get("type") not in ("openai_compat", "anthropic") or "model" not in p:
                raise HTTPException(422, "provider needs type openai_compat|anthropic and model")
            if any(k in p for k in ("api_key", "key", "token")):
                raise HTTPException(422, "do not send secrets: use api_key_env (environment variable name)")
        catalog.put_setting("ai", cfg)
        return {"ok": True}

    @app.post("/api/setups/import")
    def setup_import(body: dict):
        """Import a setup JSON (body.raw) or the CarSetup blob of an LMU DuckDB (body.duckdb_path). Never writes to originals."""
        try:
            if body.get("duckdb_path"):
                p = Path(body["duckdb_path"])
                if not _allowed(p) or not p.is_file():
                    raise HTTPException(404, "file not in the LMU telemetry folder")
                return setup_advisor.import_from_duckdb_metadata(catalog, str(p), body.get("session_id"))
            if "raw" in body:
                return setup_advisor.import_setup(catalog, body["raw"], "manual_json", body.get("name"), body.get("session_id"))
        except ValueError as e:
            raise HTTPException(422, str(e))
        raise HTTPException(422, "provide raw or duckdb_path")

    @app.get("/api/setups/{setup_id}/advice")
    def setup_advice(setup_id: str, session_id: str, lap: int, ref: int | None = None):
        if setup_advisor.get_setup(catalog, setup_id) is None:
            raise HTTPException(404, "unknown setup")
        res = compare_api(session_id, lap, ref)
        return clean(setup_advisor.advise(catalog, setup_id, res["findings"]))

    @app.get("/api/tracks/profile")
    def get_profile(track: str):
        return {"track": track, "corners": catalog.get_track_profile(track)}

    @app.put("/api/tracks/profile")
    def put_profile(track: str, corners: list[dict]):
        need = {"id", "apex_m", "entry_m", "exit_m"}
        if not corners:
            raise HTTPException(422, "Nessuna curva da salvare: un profilo vuoto non ha senso e cancellerebbe le curve rilevate.")
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

    dist = webdist if webdist is not None else Path(__file__).parent / "webdist"
    if dist.is_dir():
        app.mount("/app", StaticFiles(directory=dist, html=True), name="webapp")

    @app.get("/driving-display")
    @app.get("/driving-display/")
    def driving_display():
        """The Driving Display is a presentation mode of the SAME web app (route chosen client-side); data comes from /ws/live + /api/engineer/*."""
        if (dist / "index.html").is_file():
            return FileResponse(dist / "index.html", headers={"Cache-Control": "no-store"})
        return JSONResponse({"detail": "frontend not built (npm run build in frontend/)"}, status_code=503)

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
