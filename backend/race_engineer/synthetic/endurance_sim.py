"""Accelerated 24 h endurance SIMULATION with FAKE providers. Everything here is SYNTHETIC.

What it proves: the local pipeline keeps running, the AI layer degrades/recovers/restarts without loss, stale requests are not sent,
call volume stays bounded and memory does not grow. What it does NOT prove: real provider behaviour, real LMU data, real 24 h wall-clock
stability (the clock is simulated; real providers can and will be unavailable at times - no availability is claimed).
"""
from __future__ import annotations

import json
import math
import random
import time
from pathlib import Path

import httpx

from ..acquisition.engine import rss_mb
from ..ai.providers import AIRequestQueue, build_default_manager
from ..endurance import EndurancePipeline, RaceMemory

H = 3600.0
KEYS = {"nvidia": "nvapi-SIMULATEDKEY00000", "groq": "gsk_SIMULATEDKEY00000"}
NV, GQ = "integrate.api.nvidia.com", "api.groq.com"


class SimClock:
    def __init__(self, t0=1_800_000_000.0):
        self.t0, self.t = t0, t0
    def __call__(self):
        return self.t
    def race(self):
        return self.t - self.t0


class FakeProviders:
    """Scripted failures by simulated hour. Counts every HTTP call so wasted attempts can be measured."""
    def __init__(self, clock: SimClock):
        self.clock = clock
        self.calls = {"total": 0, "ok": 0, "during_total_outage": 0}
        self.status: dict[str, int] = {}
        self.tokens = 0

    def phase(self, host):
        h = self.clock.race() / H
        if 3.0 <= h < 3.2 or 10.0 <= h < 10.5:
            return "drop" if h < 5 else "timeout"          # total outage windows (internet loss / provider timeouts)
        if host == NV:
            if 2.0 <= h < 2.5:
                return 503
            if 6.0 <= h < 6.1:
                return 429
            if 8.0 <= h < 12.0:
                return 401                                  # NVIDIA key rejected for 4 h
        return "ok"

    def __call__(self, request: httpx.Request):
        host = request.url.host
        beh = self.phase(host)
        self.calls["total"] += 1
        h = self.clock.race() / H
        total_out = 3.0 <= h < 3.2 or 10.0 <= h < 10.5
        self.calls["during_total_outage"] += total_out
        self.status[str(beh)] = self.status.get(str(beh), 0) + 1
        if beh == "drop":
            raise httpx.ConnectError("simulated connection drop")
        if beh == "timeout":
            raise httpx.ReadTimeout("simulated timeout")
        if beh == 429:
            return httpx.Response(429, text="rate limited", headers={"retry-after": "120"})
        if beh != "ok":
            return httpx.Response(int(beh), text="simulated")
        body = json.loads(request.content)
        payload = json.loads(body["messages"][1]["content"])
        s = payload.get("state", {})
        words = f"Giro {s.get('lap')}"
        if s.get("fuel_l") is not None:
            words += f", carburante {s['fuel_l']} L"
        if s.get("best_lap_s"):
            words += f", migliore {s['best_lap_s']} s"
        if random.random() < 0.03:
            words += ", gap 17.3 s"                          # a hallucinated number: must be rejected by the grounding guard
        self.calls["ok"] += 1
        tin, tout = len(body["messages"][1]["content"]) // 3, 60
        self.tokens += tin + tout
        return httpx.Response(200, json={"choices": [{"message": {"content": words + "."}}], "usage": {"prompt_tokens": tin, "completion_tokens": tout}},
                              headers={"x-ratelimit-remaining-requests": "500", "x-ratelimit-remaining-tokens": "5000"})


class Car:
    """Very small lap model: fuel burn, pit stops every ~fuel stint, tyre wear/temps, rain, one damage event. 10 Hz."""
    def __init__(self, rng, lap_s=100.0, cap=100.0, burn=7.5):
        self.rng, self.lap_s, self.cap, self.burn = rng, lap_s, cap, burn
        self.fuel, self.lap, self.t_lap, self.last_lap, self.best = cap, 1, 0.0, 0.0, 0.0
        self.wear, self.pit_left, self.in_pits, self.laps_done, self.pits = 1.0, 0.0, False, 0, 0
        self.damage = 0

    def step(self, dt: float, race_h: float) -> dict:
        self.t_lap += dt
        if self.in_pits:
            self.pit_left -= dt
            if self.pit_left <= 0:
                self.in_pits, self.fuel = False, self.cap
                if self.pits % 3 == 0:
                    self.wear = 1.0
        else:
            self.fuel = max(0.0, self.fuel - self.burn * dt / self.lap_s)
            self.wear = max(0.05, self.wear - 0.07 * dt / self.lap_s)
        if self.t_lap >= self.lap_s:
            self.last_lap = self.t_lap + self.rng.uniform(-0.8, 0.8) + (5 if self.rng.random() < 0.03 else 0)
            self.t_lap = 0.0
            self.lap += 1
            self.laps_done += 1
            if self.fuel < self.burn * 1.3 and not self.in_pits:
                self.in_pits, self.pit_left, self.pits = True, 60.0, self.pits + 1
        if 5.0 <= race_h < 5.01:
            self.damage = 1
        if 20.0 <= race_h < 20.01:
            self.damage = 2
        rain = 0.4 if 9.0 <= race_h < 11.0 else 0.0
        tyre = 92 + 8 * math.sin(self.t_lap / 9.0) + (30 if 15.0 <= race_h < 15.05 else 0)
        v = {"session_time_s": race_h * H, "lap_number": self.lap, "last_lap_time_s": self.last_lap, "fuel_l": self.fuel, "in_pits": self.in_pits,
             "rain": rain, "damage_dent_max": self.damage, "water_temp_c": 90.0, "oil_temp_c": 105.0, "speed_kmh": 0.0 if self.in_pits else 200.0}
        for w in ("fl", "fr", "rl", "rr"):
            v[f"tyre_{w}_temp_center_c"] = tyre
            v[f"tyre_{w}_wear"] = self.wear
        return v


def _build(root: Path, clock, fake, session_id):
    mgr = build_default_manager(root / "ai_state.sqlite", {"groq": {"limits": {m: {"tpd": 60_000, "rpd": 400, "tpm": 8000, "rpm": 30}
                                                                          for m in ("openai/gpt-oss-120b", "qwen/qwen3.8-27b")}}},
                                transport=httpx.MockTransport(fake), key_overrides=KEYS, clock=clock)
    q = AIRequestQueue(root / "ai_queue.sqlite", mgr, clock=clock, max_calls_per_hour=60)
    mem = RaceMemory(root / "race_memory.sqlite", clock=clock)
    return mgr, q, mem, EndurancePipeline(mem, q, session_id, summary_interval_s=300.0)


def run(hours: float = 24.0, out_dir: Path | None = None, seed: int = 7, restarts_at_h: tuple[float, ...] = (13.0, 18.0), say=print) -> dict:
    random.seed(seed)
    root = Path(out_dir or ".") / "endurance_sim"
    root.mkdir(parents=True, exist_ok=True)
    for f in root.glob("*.sqlite*"):
        f.unlink()
    clock, rng = SimClock(), random.Random(seed)
    fake = FakeProviders(clock)
    sid = "SIM-24H"
    mgr, q, mem, pipe = _build(root, clock, fake, sid)
    car = Car(rng)
    dt, tick, total = 0.1, 0, int(hours * H / 0.1)
    rss0, rss_samples, down_s, last_ok_flag = rss_mb(), [], 0.0, True
    restarts, restart_log = list(restarts_at_h), []
    gen_samples, t_wall0 = 0, time.time()
    carry = {}
    acc: list[dict] = []
    for tick in range(total):
        clock.t += dt
        h = clock.race() / H
        v = car.step(dt, h)
        gen_samples += 1
        pipe.on_sample(v)
        if tick % 10 == 0:                         # queue worker wakes once per simulated second
            if q.pending() and mgr.next_ready_in(300) <= 0:          # the production worker sleeps while no route is usable
                for _ in range(4):
                    if q.pump() != "done":
                        break
            if all(why for _, why in mgr.available_routes()):
                down_s += 1.0
        if restarts and h >= restarts[0]:
            restarts.pop(0)
            before = {**mem.counts(), "pending": q.pending(), "laps_gen": car.laps_done}
            acc.append({"mgr": dict(vars(mgr.stats)), "q": dict(q.counters)})
            mem.close(); q.db.close(); mgr.quota.close()                # simulated crash/restart: everything reopened from disk
            carry["samples_before_restart"] = pipe.stats.samples_in
            stats_prev = pipe.stats
            mgr, q, mem, pipe = _build(root, clock, fake, sid)
            pipe.stats = stats_prev
            after = {**mem.counts(), "pending": q.pending()}
            restart_log.append({"at_h": round(h, 2), "before": before, "after": after,
                                "memory_identical": all(before[k] == after[k] for k in ("events", "summaries", "laps", "stints")),
                                "queue_pending_recovered": q.pending() == before["pending"] or "stale items dropped on recovery"})
        if tick % int(H / dt) == 0 and tick:
            rss_samples.append(round(rss_mb() or 0, 1))
    pipe.end_session()
    for _ in range(200):
        clock.t += 5
        if q.pump() == "idle":
            break
    acc.append({"mgr": dict(vars(mgr.stats)), "q": dict(q.counters)})
    wall = time.time() - t_wall0

    def merge(key, sub):
        out: dict = {}
        for a in acc:
            for k, v in a[key].items():
                if isinstance(v, dict):
                    d = out.setdefault(k, {})
                    for k2, v2 in v.items():
                        if isinstance(v2, dict):
                            for k3, v3 in v2.items():
                                d.setdefault(k2, {})[k3] = d.get(k2, {}).get(k3, 0) + v3
                        else:
                            d[k2] = d.get(k2, 0) + v2
                elif isinstance(v, (int, float)):
                    out[k] = out.get(k, 0) + v
        return out
    mstats, qcount = merge("mgr", None), merge("q", None)
    st = q.status_counts()
    by_src: dict[str, int] = {}
    for s in mem.summaries(sid, limit=100000):
        key = s["source"].split(":")[0] + ("/" + s["status"] if s["status"] != "ok" else "")
        by_src[key] = by_src.get(key, 0) + 1
    laps_mem = mem.lap_count(sid)
    hs = mgr.health.snapshot()
    rep = {
        "SYNTHETIC": True, "simulated_hours": hours, "wall_seconds": round(wall, 1), "seed": seed,
        "samples_generated": gen_samples, "samples_ingested": pipe.stats.samples_in, "samples_analysed_locally": pipe.stats.samples_analysed,
        "laps_generated": car.laps_done, "laps_in_memory": laps_mem, "stints_in_memory": len(mem.stints(sid)), "pit_stops_generated": car.pits,
        "events_stored": mem.counts()["events"],
        "ai": {"requests_submitted": qcount["submitted"], "enqueued_by_pipeline": pipe.stats.ai_enqueued, "answered": pipe.stats.ai_accepted + pipe.stats.ai_rejected_ungrounded,
               "accepted": pipe.stats.ai_accepted, "rejected_ungrounded_numbers": pipe.stats.ai_rejected_ungrounded,
               "http_calls_total": fake.calls["total"], "http_calls_ok": fake.calls["ok"], "http_calls_during_total_outage": fake.calls["during_total_outage"],
               "tokens_total_reported": fake.tokens, "queue": {**qcount, "status": st},
               "manager": {k: mstats.get(k) for k in ("requests", "served", "fallbacks", "local_fallbacks", "errors", "by_route")},
               "http_status_histogram": fake.status, "all_routes_unavailable_s": round(down_s), "route_health": hs},
        "summaries_by_source": by_src, "local_summaries": pipe.stats.local_summaries,
        "restarts": restart_log,
        "memory_mb": {"rss_start": rss0, "rss_hourly": rss_samples, "rss_end": round(rss_mb() or 0, 1)},
        "pending_at_end": q.pending(),
    }
    rep["checks"] = {
        "no_sample_lost_before_detector": rep["samples_generated"] == rep["samples_ingested"],
        "all_completed_laps_persisted": abs(rep["laps_generated"] - laps_mem) <= 1 + len(restart_log),
        "memory_survived_every_restart": all(r["memory_identical"] for r in restart_log),
        "calls_bounded": fake.calls["total"] < hours * 120,
        "no_calls_flood_during_total_outage": fake.calls["during_total_outage"] <= 3 * 42,   # <= 1 probe/min/route over the 42 simulated outage minutes; without a breaker: thousands
        "rss_growth_under_100mb": (rss_samples[-1] - (rss_samples[0] if rss_samples else 0) < 100) if rss_samples else None,
        "local_summary_for_every_ai_request": rep["local_summaries"] >= rep["ai"]["enqueued_by_pipeline"],
    }
    (root / "endurance_report.json").write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    say(json.dumps({k: rep[k] for k in ("simulated_hours", "wall_seconds", "samples_generated", "laps_generated", "laps_in_memory", "checks")}, indent=2))
    return rep
