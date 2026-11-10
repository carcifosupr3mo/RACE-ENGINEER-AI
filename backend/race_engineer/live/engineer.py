"""LiveEngineer: the ONE real-time state of the track engineer, shared by the dashboard and the Driving Display.

Pipeline (all existing components, nothing duplicated):
  AcquisitionEngine (shared memory, single reader) --on_sample--> LiveEngineer
    lap buffer -> segment_laps (existing validity rules) -> align_lap (existing 1 m alignment)
    -> driving.analyse vs PersonalReference (corner phases, whole-corner judgement, confidence)
    -> PersonalReference.add (progressive reference, persisted)  -> suggestion arbiter / alerts
    -> optional AI interpretation through the EXISTING AI request queue (aggregates only, grounded, never per sample)
  snapshot() is the single source consumed by /api/engineer/*, by the /ws/live "engineer" field and by the AI facts.

Real-time work per sample is just a list append; lap analysis runs on a worker thread; the 10 Hz tick is O(1).
"""
from __future__ import annotations

import collections
import json
import queue
import threading
import time
from pathlib import Path
from typing import Callable

import numpy as np

from ..analysis.align import AlignedLap, align_lap
from ..analysis.corners import Corner
from ..analysis.driving import analyse, zones
from ..analysis.laps import SessionData, segment_laps
from ..analysis.reference import PersonalReference
from ..analysis.session_mode import classify
from .suggestions import Arbiter, build_alerts, build_candidates
from .coach import Coach, cap_confidence, comparable, corners_meta, lap_conditions

LIVE_COLS = ("session_time_s", "lap_number", "lap_dist_m", "speed_kmh", "throttle", "brake", "steering", "rpm", "gear", "in_pits",
             "lap_invalidated", "last_lap_time_s", "fuel_l", "pos_x_m", "pos_z_m", "sector",
             "rain", "track_temp_c", "tyre_fl_wear", "tyre_fr_wear", "tyre_rl_wear", "tyre_rr_wear")      # last six = lap conditions (comparability)
TAIL_SAMPLES = 25            # samples of the next lap kept to read the game's last-lap time and close the lap exactly like the offline analysis
SCHEMA = 1
AI_SYSTEM = ("Sei l'ingegnere di pista. Commenta in italiano, al massimo 3 righe, l'analisi dell'ultimo giro. "
             "Usa ESCLUSIVAMENTE i numeri presenti nei dati forniti, non inventare valori, non proporre modifiche di setup.")


def _f(x):
    return float("nan") if x is None else float(x)


class LiveEngineer:
    def __init__(self, engine, catalog, root, *, endurance_snapshot: Callable[[], dict | None] | None = None,
                 ai_queue: Callable[[], object] | None = None, synchronous: bool = False, tick_hz: float = 10.0,
                 clock: Callable[[], float] = time.time):
        self.engine, self.catalog, self.root = engine, catalog, root
        self.endurance_snapshot, self.ai_queue = endurance_snapshot, ai_queue
        self.synchronous, self.min_dt, self.clock = synchronous, 1.0 / tick_hz, clock
        self._lock = threading.RLock()
        self._jobs: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self.errors: collections.deque = collections.deque(maxlen=20)
        self.events: collections.deque = collections.deque(maxlen=200)
        self.seq = 0
        self.counters = {"samples": 0, "laps_closed": 0, "laps_analysed": 0, "ai_requests": 0, "ai_accepted": 0, "ai_rejected": 0}
        self.coach = Coach(catalog, clock)
        self._reset_session(None)
        engine.on_sample.append(self.on_sample)
        engine.on_session_end.append(self._on_session_end)

    # ------------------------------------------------------------------ session state
    def _reset_session(self, key):
        self.key = key
        self.sid = None
        self.ctx = None
        self.synthetic = False
        self.ref: PersonalReference | None = None
        self.cur = {c: [] for c in LIVE_COLS}
        self.cur_lap: int | None = None
        self.closing: dict | None = None
        self.geom: AlignedLap | None = None
        self.history: collections.deque = collections.deque(maxlen=5)
        self.last_analysis: dict | None = None
        self.by_lap: dict[int, dict] = {}                # lap number -> analysis (bounded), for the per-lap API and tests
        self.arbiter = Arbiter()
        self.candidates: list = []
        self.trail: list = []
        self.lap_t0: float | None = None
        self.lap_start_dist: float | None = None
        self.delta_hist: collections.deque = collections.deque(maxlen=40)
        self.best_lap_s: float | None = None
        self.last_lap_s: float | None = None
        self.ai_note: dict | None = None
        self._ai_payloads: dict = {}
        self._last_tick = -1e9
        self._last_slow = -1e9
        self._alerts: list = []
        self._mode: dict = classify(None)
        self._state: dict = {}
        self._map_cache: tuple | None = None
        self.last_session_t: float | None = None
        self.lap_cond: dict[int, dict] = {}              # lap number -> conditions (comparability)
        self.lap_times: list[float] = []                 # valid lap times of this session
        self._prev_al: AlignedLap | None = None
        self._prev_res: dict | None = None
        self._prev_time: float | None = None
        self.last_review: dict | None = None
        self.review_at: float | None = None
        self.reviews: dict[int, dict] = {}
        self._cands_sig = None
        self._instr_cache: dict = {}
        self._shown_key: str | None = None

    def _event(self, kind: str, data: dict) -> None:
        self.seq += 1
        self.events.append({"seq": self.seq, "type": kind, "t": self.clock(), "data": data})

    def _on_session_end(self, sid) -> None:
        with self._lock:
            if self.ref:
                self.ref.save()

    # ------------------------------------------------------------------ per-sample (acquisition thread: keep it cheap, never raise)
    def on_sample(self, sample) -> None:
        try:
            self._on_sample(sample)
        except Exception as e:           # the engineer must never disturb acquisition
            self.errors.append(f"{type(e).__name__}: {e}")

    def _on_sample(self, sample) -> None:
        v = sample.values
        ctx = self.engine.ctx
        if ctx is None:
            return
        with self._lock:
            t = v.get("session_time_s")
            key = (self.engine.session_id, ctx.key())
            restarted = self.last_session_t is not None and t is not None and t < self.last_session_t - 1.0
            if key != self.key or restarted:
                self._start_session(key, ctx, sample)
            self.last_session_t = t
            self.counters["samples"] += 1
            lap = v.get("lap_number")
            if lap is None or v.get("lap_dist_m") is None or t is None:
                return
            lap = int(lap)
            if self.cur_lap is None:
                self.cur_lap = lap
            elif lap != self.cur_lap:
                self._lap_boundary(lap)
            for c in LIVE_COLS:
                self.cur[c].append(_f(v.get(c)))
            if self.closing is not None:
                for c in LIVE_COLS:
                    self.closing["tail"][c].append(_f(v.get(c)))
                if len(self.closing["tail"]["session_time_s"]) >= TAIL_SAMPLES:
                    self._submit_close()
            if self.lap_t0 is None:
                self.lap_t0, self.lap_start_dist = float(t), float(v["lap_dist_m"])
            now = self.clock()
            if now - self._last_tick >= self.min_dt:
                self._last_tick = now
                self._tick(v, now)

    def _start_session(self, key, ctx, sample) -> None:
        if self.ref is not None:
            self.ref.save()
        self._reset_session(key)
        self.key, self.sid, self.ctx = key, key[0], ctx
        self.synthetic = bool(self.engine.synthetic) or sample.source.value == "synthetic"
        prof = None
        try:
            prof = self.catalog.get_track_profile(ctx.track_name or "")
        except Exception:
            pass
        self.ref = PersonalReference(ctx.track_name, ctx.vehicle_name, self.synthetic, store_dir=None if self.root is None else Path(self.root) / "references", profile=prof)
        self.coach.bind(self.sid, ctx.track_name, ctx.vehicle_name, self.synthetic)
        self._event("session_started", {"session_id": self.sid, "track": ctx.track_name, "reference_laps": len(self.ref.laps)})
        if self.ref.laps:
            self._event("reference_loaded", {"version": self.ref.version, "laps": len(self.ref.laps)})

    def _lap_boundary(self, new_lap: int) -> None:
        if len(self.cur["session_time_s"]) >= 50 and self.closing is None:
            self.closing = {"lap": self.cur_lap, "body": self.cur, "tail": {c: [] for c in LIVE_COLS}}
        elif self.closing is not None and len(self.cur["session_time_s"]) >= 50:
            self._submit_close()
            self.closing = {"lap": self.cur_lap, "body": self.cur, "tail": {c: [] for c in LIVE_COLS}}
        self.cur = {c: [] for c in LIVE_COLS}
        self.cur_lap = new_lap
        self.lap_t0 = None
        self.trail = []
        self.delta_hist.clear()

    def _submit_close(self) -> None:
        job, self.closing = self.closing, None
        if job is None:
            return
        if self.synchronous:
            self._finalize(job)
        else:
            self._jobs.put(job)
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._work, name="live-engineer", daemon=True)
                self._worker.start()

    def _work(self) -> None:
        while True:
            try:
                job = self._jobs.get(timeout=30)
            except queue.Empty:
                return
            try:
                self._finalize(job)
            except Exception as e:
                self.errors.append(f"lap analysis: {type(e).__name__}: {e}")
            finally:
                self._jobs.task_done()

    def flush(self, timeout: float = 10.0) -> None:
        """Wait for queued lap analyses (used by tests and by the final report)."""
        t0 = time.time()
        while self._jobs.unfinished_tasks and time.time() - t0 < timeout:
            time.sleep(0.01)

    # ------------------------------------------------------------------ lap analysis (worker thread)
    def _finalize(self, job: dict) -> None:
        ctx, ref, sid = self.ctx, self.ref, self.sid
        if ctx is None or ref is None:
            return
        cols = {c: np.array(job["body"][c] + job["tail"][c], dtype=float) for c in LIVE_COLS}
        L = float(ctx.track_length_m or 0.0)
        self.counters["laps_closed"] += 1
        if L <= 0:
            with self._lock:
                self._event("lap_completed", {"lap": job["lap"], "valid": False, "reasons": ["track_length_unknown"]})
            return
        sd = SessionData(cols, L, "synthetic" if self.synthetic else "lmu_shm")
        lap = segment_laps(sd)[0]
        info = {"lap": lap.number, "time_s": lap.time_s, "valid": bool(lap.valid_for_analysis), "reasons": lap.reasons, "status": lap.status}
        al = None
        try:
            al = align_lap(sd, lap)
        except Exception:
            pass
        with self._lock:
            if lap.time_s:
                self.last_lap_s = float(lap.time_s)
            if al is not None and al.quality["ok"] and self.geom is None:
                self.geom = al
            if not (lap.valid_for_analysis and lap.time_s and al is not None and al.quality["ok"]):
                info["valid"] = False
                self._event("lap_completed", info)
                return
            rel = ref.reliability()
            anchor = ref.anchor
            anchor_time_before = anchor.time_s if anchor is not None else None
            res = None
            cond = lap_conditions(cols)
            self.lap_cond[lap.number] = cond
            if len(self.lap_cond) > 80:
                self.lap_cond.pop(next(iter(self.lap_cond)))
            anchor_cond = self.lap_cond.get(anchor.number) if (anchor is not None and anchor.session_id == sid) else None
            comp = comparable(cond, anchor_cond)
            if anchor is not None and ref.corners():
                res = analyse(al, anchor.aligned, ref.corners(), reliability=max(0.15, rel["score"]))
                res["ref_session_id"] = anchor.session_id
                res["ref_time_s"] = anchor.time_s
                res["lap_time_s"] = float(lap.time_s)
                res["comparable"], res["conditions"] = comp["ok"], cond
                cap_confidence(res, comp)
                self.last_analysis = res
                if comp["ok"]:
                    self.history.append(res)         # laps in clearly different conditions neither create nor judge advice
                self.by_lap[res['lap']] = res
                if len(self.by_lap) > 60:
                    self.by_lap.pop(next(iter(self.by_lap)))
                self.counters["laps_analysed"] += 1
            self.coach.lap_now = lap.number
            evals = self.coach.lap_closed(res, lap=lap.number, comp=comp)
            prev_res = self._prev_res
            if res is not None and self._prev_al is not None and (prev_res is None or prev_res.get("ref_lap") != res["ref_lap"]
                                                                   or prev_res.get("ref_session_id") != res.get("ref_session_id")):
                try:
                    prev_res = analyse(self._prev_al, anchor.aligned, ref.corners(), reliability=max(0.15, rel["score"]))   # same function, same reference
                except Exception:
                    prev_res = None
            add = ref.add(al, float(lap.time_s), sid)
            if add.get("new_anchor"):
                self.history.clear()                 # earlier findings were measured against a reference that no longer exists
                self.candidates = []
                self._cands_sig = None
            if self.best_lap_s is None or lap.time_s < self.best_lap_s:
                self.best_lap_s = float(lap.time_s)
            info.update({"is_reference_best": bool(add.get("new_anchor")), "delta_to_ref_s": None if res is None else res["total_delta_s"],
                         "findings": 0 if res is None else len(res["findings"])})
            self._event("lap_completed", info)
            if add.get("accepted") and (add.get("new_anchor") or ref.version == 1 or len(ref.laps) <= 3):
                self._event("reference_changed", {"version": ref.version, "anchor_lap": ref.anchor.number, "anchor_time_s": ref.anchor.time_s,
                                                  "laps": len(ref.laps), "reliability": ref.reliability()["level"]})
            if res is not None:
                self._event("analysis_ready", {"lap": lap.number, "ref_lap": res["ref_lap"], "findings": len(res["findings"]), "total_delta_s": res["total_delta_s"]})
                self._rebuild_candidates()
                self._submit_ai(res)
            self._make_review(res, lap, comp, evals, prev_res, anchor_time_before)
            self._prev_al, self._prev_res, self._prev_time = al, res, float(lap.time_s)
            self.lap_times.append(float(lap.time_s))

    def _review_view(self, now: float) -> dict | None:
        """Compact view of the last end-of-lap review for the shared state (the full review: /api/coach/review)."""
        rv = self.last_review
        if rv is None or self.review_at is None:
            return None
        age = now - self.review_at
        return {"lap": rv["lap"], "summary": rv["summary"], "time_s": rv["time_s"], "delta_best_s": rv["delta_best_s"], "delta_prev_s": rv["delta_prev_s"],
                "improved": [r["label"] for r in rv["improved"][:3]], "worsened": [r["label"] for r in rv["worsened"][:3]],
                "comparable": rv["comparable"]["ok"], "next_focus": rv["next_focus"], "age_s": round(age, 1),
                "visible": age < float(self.coach.prefs()["show_review_s"]), "synthetic": rv.get("synthetic", False)}

    def _rebuild_candidates(self) -> None:
        """Candidates only change when the mode or the analysed laps change; the coach re-ranks them with the driver's memory."""
        sig = (self._mode["mode"], len(self.history), self.history[-1]["lap"] if self.history else None)
        if sig == self._cands_sig:
            return
        self._cands_sig = sig
        self._instr_cache = {}
        self.candidates = self.coach.decorate(build_candidates(list(self.history), self._mode))
        if self.ref is not None and self.ref.anchor is not None and self.candidates:
            self.coach.sync_tips(self.candidates, self._mode, self.ref.reliability(), corners_meta(self.ref))

    def _make_review(self, res, lap, comp, evals, prev_res, best_before) -> None:
        corners = corners_meta(self.ref)
        focus = None
        if self.candidates:
            c0 = self.candidates[0]
            i0 = self._instr_cache.get(c0.key) or self.coach.instruction(c0.to_json(), corner=corners.get(c0.corner), mode=self._mode,
                                                                           rel=self.ref.reliability() if self.ref else {}, reassess=getattr(c0, "reassess", False))
            focus = {"corner": c0.corner, "corner_label": i0["corner_label"], "headline": i0["headline"], "key": c0.key}
        best = best_before if best_before is not None else None
        rv = self.coach.review(res=res, lap=lap.number, time_s=float(lap.time_s), best_s=best, prev_res=prev_res, prev_time=self._prev_time,
                               session_times=list(self.lap_times) + [float(lap.time_s)], comp=comp, evals=evals, corners=corners, next_focus=focus, mode=self._mode)
        rv["synthetic"] = self.synthetic
        self.last_review, self.review_at = rv, self.clock()
        self.reviews[lap.number] = rv
        if len(self.reviews) > 60:
            self.reviews.pop(next(iter(self.reviews)))
        try:
            self.coach.save_review(rv, 0 if res is None else len(res["findings"]))
        except Exception as e:
            self.errors.append(f"coach memory: {type(e).__name__}: {e}")
        self._event("lap_review", {"lap": lap.number, "summary": rv["summary"], "comparable": comp["ok"]})

    # ------------------------------------------------------------------ AI interpretation (optional, aggregates only, never per sample)
    def _submit_ai(self, res: dict) -> None:
        if self.synthetic or self.ai_queue is None:
            return
        try:
            q = self.ai_queue()
            if q is None:
                return
            from ..ai.providers.types import AIRequest, Priority
            payload = {"lap": res["lap"], "ref_lap": res["ref_lap"], "total_delta_s": None if res["total_delta_s"] is None else round(res["total_delta_s"], 3),
                       "sessione": self._mode["label"], "affidabilita_riferimento": res["reference_reliability"],
                       "riscontri": [{"curva": f["corner"], "tipo": f["label"], "impatto_s": f["time_impact_s"], "confidenza": f["confidence"]["level"],
                                      "misure": f["evidence"]} for f in res["findings"][:5]]}
            req = AIRequest(kind="driving_analysis", system=AI_SYSTEM, user=json.dumps(payload, ensure_ascii=False), priority=Priority.LOW,
                            ttl_s=900.0, dedup_key=f"{self.sid}:drv:{res['lap']}", max_tokens=250, session_id=self.sid)
            self._chain_ai(q)
            rid = q.submit(req)
            if rid:
                self._ai_payloads[rid] = payload
                if len(self._ai_payloads) > 50:
                    self._ai_payloads.pop(next(iter(self._ai_payloads)))
                self.counters["ai_requests"] += 1
        except Exception as e:
            self.errors.append(f"ai: {type(e).__name__}: {e}")

    def _chain_ai(self, q) -> None:
        cb = getattr(q, "on_result", None)
        if getattr(cb, "_live_engineer", False):
            return
        prev = cb

        def dispatch(req, resp):
            if prev:
                prev(req, resp)
            self._on_ai(req, resp)
        dispatch._live_engineer = True          # type: ignore[attr-defined]
        q.on_result = dispatch

    def _on_ai(self, req, resp) -> None:
        if req.kind != "driving_analysis" or req.session_id != self.sid:
            return
        from ..endurance.pipeline import ungrounded_numbers
        payload = self._ai_payloads.pop(req.id, None)
        if payload is None:
            return
        bad = ungrounded_numbers(resp.text, payload)
        with self._lock:
            if bad:
                self.counters["ai_rejected"] += 1
                return
            self.counters["ai_accepted"] += 1
            self.ai_note = {"text": resp.text, "provider": resp.provider, "model": resp.model, "lap": payload["lap"], "grounded": True}
            self._event("ai_note", {"lap": payload["lap"], "provider": resp.provider})

    # ------------------------------------------------------------------ 10 Hz tick
    def _corner_context(self, s: float, v: dict, L: float):
        cs = self.ref.corners() if self.ref else []
        if not cs or L <= 0:
            return None, None, None, "straight", False
        cur, nxt, dist = None, None, None
        for c in cs:
            if c.entry_m - 20.0 <= s <= c.exit_m:
                cur = c
        ahead = sorted(cs, key=lambda c: (c.entry_m - s) % L)
        nxt = next((c for c in ahead if c is not cur), ahead[0])
        dist = (nxt.entry_m - s) % L
        brake, steer = v.get("brake") or 0.0, abs(v.get("steering") or 0.0)
        phase = "straight"
        if cur is not None:
            phase = "braking" if brake > 0.1 else "apex" if abs(s - cur.apex_m) <= 30 else "exit" if s > cur.apex_m else "entry"
        demanding = cur is not None or brake > 0.05 or steer > 0.30
        return cur, nxt, dist, phase, demanding

    def _tick(self, v: dict, now: float) -> None:
        ctx, ref = self.ctx, self.ref
        L = float(ctx.track_length_m or 0.0)
        s = float(v["lap_dist_m"])
        t = float(v["session_time_s"])
        if now - self._last_slow >= 0.5:
            self._last_slow = now
            snap = self.endurance_snapshot() if self.endurance_snapshot else None
            self._snap = snap
            self._alerts = build_alerts(v, snap)
            self._mode = classify(ctx.session_type, t, (snap or {}).get("stint", 1))
            self._rebuild_candidates()
        # trail: real positions every >= 3 m
        x, z = v.get("pos_x_m"), v.get("pos_z_m")
        if x is not None and z is not None and (not self.trail or abs(s - self.trail[-1][2]) >= 3.0) and len(self.trail) < 6000:
            self.trail.append([round(float(x), 1), round(float(z), 1), round(s, 1)])
        # live delta vs the anchor, with the same time origin as align_lap (first sample of the lap)
        delta = None
        anchor = ref.anchor if ref else None
        if anchor is not None and self.lap_t0 is not None and self.lap_start_dist is not None and self.lap_start_dist < max(30.0, 0.02 * L):
            a = anchor.aligned
            fin = np.isfinite(a.t)
            if fin.any() and a.grid[fin][0] <= s <= a.grid[fin][-1]:
                delta = (t - self.lap_t0) - float(np.interp(s, a.grid[fin], a.t[fin]))
        if delta is not None:
            self.delta_hist.append((t, delta))
        trend = None
        if len(self.delta_hist) >= 5:
            (t0, d0), (t1, d1) = self.delta_hist[0], self.delta_hist[-1]
            trend = (d1 - d0) / (t1 - t0) if t1 - t0 > 0.5 else None
        cur, nxt, dist, phase, demanding = self._corner_context(s, v, L)
        enough = ref is not None and len(ref.laps) >= 2
        main = None
        if enough:
            main = self.arbiter.update(self.candidates, now, nxt.id if nxt else None, dist, demanding)
        else:
            self.arbiter.current, self.arbiter.frozen = None, False
        crit = [a for a in self._alerts if a["level"] == "critical"]
        prev = self._state.get("suggestion", {}).get("main") if self._state else None
        main_j = main.to_json() if main else None
        if main_j:
            early = L > 0 and s < 0.25 * L
            if self._shown_key != main_j["id"]:
                self._shown_key = main_j["id"]
                self._instr_cache.pop(main_j["id"], None)
                self.coach.displayed(main_j["id"], (self.cur_lap or 0) if early else (self.cur_lap or 0) + 1)
            inst = self._instr_cache.get(main_j["id"])
            if inst is None:
                inst = self._instr_cache[main_j["id"]] = self.coach.instruction(
                    main_j, corner=corners_meta(ref).get(main_j["corner"]), mode=self._mode,
                    rel=ref.reliability() if ref else {}, reassess=getattr(main, "reassess", False))
            main_j["instruction"] = inst
        elif self._shown_key is not None:
            self._shown_key = None
        if (main_j and main_j["id"]) != (prev and prev["id"]):
            self._event("suggestion_changed", {"id": main_j and main_j["id"], "text": main_j and main_j["text"]})
        rel = ref.reliability() if ref else {"level": "nessuno", "learning": True, "n_laps": 0, "score": 0.0, "reasons": []}
        n_valid = len(ref.laps) if ref else 0
        sug_state = "learning" if not enough else ("frozen" if self.arbiter.frozen else "ready" if main_j else "quiet")
        learning = None
        if not enough:
            learning = {"have": n_valid, "need": 2, "message": f"Sto imparando il circuito: giri validi {n_valid}/2 per attivare i suggerimenti"}
        snap = getattr(self, "_snap", None)
        self._state = {
            "schema": SCHEMA,
            "session": {"id": self.sid, "track": ctx.track_name, "vehicle": ctx.vehicle_name, "type": ctx.session_type, "mode": self._mode,
                        "elapsed_s": round(t, 1), "track_length_m": L},
            "lap": {"number": self.cur_lap, "elapsed_s": None if self.lap_t0 is None else round(t - self.lap_t0, 2), "last_s": self.last_lap_s,
                    "best_s": self.best_lap_s, "sector": v.get("sector")},
            "inputs": {"speed_kmh": v.get("speed_kmh"), "gear": v.get("gear"), "rpm": v.get("rpm"), "max_rpm": v.get("max_rpm"),
                       "throttle": v.get("throttle"), "brake": v.get("brake"), "steering": v.get("steering")},
            "position": {"lap_dist_m": round(s, 1), "x": x, "z": z},
            "delta": {"available": delta is not None, "to_ref_s": None if delta is None else round(delta, 3),
                      "trend_s_per_s": None if trend is None else round(trend, 3),
                      "ref_lap": anchor.number if anchor else None, "ref_time_s": anchor.time_s if anchor else None},
            "corner": {"current": cur.id if cur else None, "next": nxt.id if nxt else None,
                       "dist_to_next_m": None if dist is None else round(dist, 0), "phase": phase, "demanding": bool(demanding)},
            "reference": {"version": ref.version if ref else 0, "laps": n_valid, "reliability": rel, "synthetic": self.synthetic,
                          "anchor": None if anchor is None else {"lap": anchor.number, "time_s": round(anchor.time_s, 3), "session_id": anchor.session_id}},
            "suggestion": {"state": sug_state, "main": main_j, "frozen": bool(self.arbiter.frozen), "learning": learning,
                           "candidates": [c.to_json() for c in self.candidates[:3]]},
            "alerts": self._alerts, "critical": bool(crit),
            "last_lap": None if self.last_analysis is None else {
                "lap": self.last_analysis["lap"], "ref_lap": self.last_analysis["ref_lap"], "time_s": self.last_analysis.get("lap_time_s"),
                "delta_s": self.last_analysis["total_delta_s"], "findings": [{k: f[k] for k in ("corner", "type", "label", "time_impact_s", "confidence")}
                                                                          for f in self.last_analysis["findings"][:5]],
                "gains": [{k: g[k] for k in ("corner", "label", "time_gain_s")} for g in self.last_analysis["gains"][:3]]},
            "resources": None if not snap else {k: snap.get(k) for k in ("fuel_l", "fuel_per_lap_l", "laps_of_fuel", "stint", "stint_laps", "tyre_max_c_this_lap",
                                                                          "wear_min_this_lap", "avg_last_laps_s")},
            "review": self._review_view(now), "coach": {"prefs": self.coach.prefs(), "lap_comparable": None if not self.last_analysis else self.last_analysis.get("comparable")},
            "ai_note": self.ai_note, "map_version": self.map_version(),
            "provenance": "synthetic" if self.synthetic else "lmu_shm", "synthetic": self.synthetic,
            "seq": self.seq,
        }

    # ------------------------------------------------------------------ map (REAL positions only)
    def map_version(self) -> str:
        return f"{self.ref.version if self.ref else 0}:{'g' if self.geom is not None else '-'}"

    def map_payload(self) -> dict:
        with self._lock:
            ver = self.map_version()
            if self._map_cache and self._map_cache[0] == ver:
                return self._map_cache[1]
            ref = self.ref
            src, al = ("reference", ref.anchor.aligned) if ref and ref.anchor else (("geometry", self.geom) if self.geom is not None else (None, None))
            out: dict = {"available": False, "version": ver, "source": src, "reason": "nessun giro completo con posizione: la mappa si costruisce dai dati reali"}
            if al is not None:
                x, z = al.ch.get("pos_x_m"), al.ch.get("pos_z_m")
                if x is not None and z is not None and np.isfinite(x).sum() > 50 and np.isfinite(z).sum() > 50:
                    idx = [i for i in range(0, len(al.grid), 3) if np.isfinite(x[i]) and np.isfinite(z[i])]
                    cs = ref.corners() if ref and ref.anchor else []
                    def xz(m):
                        i = int(np.clip(round(m / (al.grid[1] - al.grid[0])), 0, len(al.grid) - 1))
                        return [round(float(x[i]), 1), round(float(z[i]), 1)] if np.isfinite(x[i]) and np.isfinite(z[i]) else None
                    out = {"available": True, "version": ver, "source": src, "synthetic": self.synthetic,
                           "track_length_m": float(self.ctx.track_length_m), "points": [[round(float(x[i]), 1), round(float(z[i]), 1), float(al.grid[i])] for i in idx],
                           "corners": [{"id": c.id, "name": c.name, "entry_m": c.entry_m, "apex_m": c.apex_m, "exit_m": c.exit_m, "provisional": c.provisional,
                                        "min_speed_kmh": c.min_speed_kmh, "apex_xz": xz(c.apex_m)} for c in cs],
                           "zones": zones(al, cs) if cs and src == "reference" else [],
                           "targets": ref.targets() if ref and ref.anchor else [],
                           "note": "Geometria dai campioni reali di posizione del giro di riferimento; nessun tracciato è stato inventato o disegnato a mano."}
            self._map_cache = (ver, out)
            return out

    # ------------------------------------------------------------------ public API
    def snapshot(self, full: bool = False) -> dict:
        """The shared state. Same dict for every consumer; only the connection block is refreshed at read time."""
        with self._lock:
            st = dict(self._state) if self._state else {}
            st["seq"] = self.seq
        eng = self.engine.diagnostics()
        st["connection"] = {"state": eng["state"], "acquiring": eng["state"] == "acquiring", "effective_hz": eng["effective_hz"],
                            "samples_lost": eng["samples_lost"], "synthetic": bool(eng["synthetic"]) or st.get("synthetic", False),
                            "last_sample_age_s": None if self.engine.stats.last_sample_wall is None else round(self.engine.clock() - self.engine.stats.last_sample_wall, 2)}
        st["server_time"] = self.clock()
        st["ready"] = bool(self._state)
        if not self._state:
            st["suggestion"] = {"state": "learning", "main": None, "frozen": False,
                                "learning": {"have": 0, "need": 2, "message": "In attesa dei dati di guida"}, "candidates": []}
            st["alerts"], st["map_version"] = [], "0:-"
        if full:
            st["map"] = self.map_payload()
            st["trail"] = list(self.trail)
            st["analysis"] = self.last_analysis
            st["reference_detail"] = self.ref.to_json() if self.ref else None
        return st

    def events_since(self, seq: int = 0) -> list[dict]:
        with self._lock:
            return [e for e in self.events if e["seq"] > seq]

    def status(self) -> dict:
        return {"counters": dict(self.counters), "errors": list(self.errors), "pending_jobs": self._jobs.unfinished_tasks, "seq": self.seq}
