"""Endurance pipeline: local analysis always on; online AI is an optional, rate-limited, stale-safe add-on.

Flow:  samples -> EventDetector (local) -> RaceMemory (always) ->
       [periodic 5 min / stint end / pit / critical events / final] -> local text saved IMMEDIATELY ->
       AIRequestQueue (dedup, priority, TTL, quota) -> provider -> number-grounding check -> RaceMemory (source=ai:...).
If every provider is down nothing changes for the race: memory keeps filling with local summaries.
The AI receives compact aggregates, never raw samples.
"""
from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field

from ..ai.providers.request_queue import AIRequestQueue
from ..ai.providers.types import AIRequest, AIResponse, Priority
from .detector import Event, EventDetector, Thresholds
from .memory import RaceMemory

SYSTEM = ("Sei l'ingegnere di pista di una gara di durata. Scrivi in italiano, massimo 5 righe, tono operativo. "
          "Usa ESCLUSIVAMENTE i numeri presenti nei dati forniti: non inventare valori, non stimare. "
          "Se un dato manca dillo. Non proporre modifiche di setup.")


def _mmss(s: float) -> str:
    return f"{int(s // 60)}:{s % 60:06.3f}"


def _numbers_in(o, acc: set):
    if isinstance(o, bool):
        return
    if isinstance(o, (int, float)):
        acc.add(float(o))
        if abs(o) >= 20:                      # lap/stint times may be written as m:ss.mmm
            acc.update({float(int(o // 60)), round(o % 60, 3), round(o % 60, 1), round(o % 60), float(int(o // 3600)),
                        float(int(o % 3600 // 60))})
    elif isinstance(o, dict):
        for v in o.values():
            _numbers_in(v, acc)
    elif isinstance(o, (list, tuple)):
        for v in o:
            _numbers_in(v, acc)
    elif isinstance(o, str):
        for m in re.findall(r"\d+(?:\.\d+)?", o):
            acc.add(float(m))


def ungrounded_numbers(text: str, payload) -> list[str]:
    """Numbers in an AI text that do not appear (within rounding) in the data that was sent. Empty list = grounded."""
    allowed: set[float] = set()
    _numbers_in(payload, allowed)
    bad = []
    for m in re.findall(r"\d+(?:[.,]\d+)?", text):
        n = float(m.replace(",", "."))
        if not any(abs(n - a) <= max(0.051, 0.006 * abs(a)) for a in allowed):
            bad.append(m)
    return bad


def local_text(kind: str, p: dict) -> str:
    """Deterministic, rules-based text from the same payload (what the race memory keeps when no AI answers)."""
    s = p.get("state", {})
    bits = [f"Giro {s.get('lap')}, stint {s.get('stint')}"]
    if s.get("last_laps_s"):
        bits.append("ultimi giri " + ", ".join(_mmss(x) for x in s["last_laps_s"]))
    if s.get("best_lap_s"):
        bits.append("migliore " + _mmss(s["best_lap_s"]))
    if s.get("fuel_l") is not None:
        bits.append(f"carburante {s['fuel_l']} L" + (f", circa {s['laps_of_fuel']} giri" if s.get("laps_of_fuel") else ""))
    if s.get("tyre_max_c_this_lap"):
        bits.append(f"temperatura gomme max {s['tyre_max_c_this_lap']:.0f} C")
    ev = p.get("events", [])
    if ev:
        bits.append("eventi: " + ", ".join(f"{e['kind']}" + (f"@giro {e['lap']}" if e.get("lap") is not None else "") for e in ev[-6:]))
    head = {"periodic_summary": "Riepilogo", "stint_end": "Fine stint", "pit_stop": "Pit stop", "event": "Evento", "final_report": "Report finale"}.get(kind, kind)
    return f"{head} [locale]: " + "; ".join(bits) + "."


@dataclass
class PipelineStats:
    samples_in: int = 0
    samples_analysed: int = 0
    events: int = 0
    ai_enqueued: int = 0
    ai_accepted: int = 0
    ai_rejected_ungrounded: int = 0
    local_summaries: int = 0


class EndurancePipeline:
    def __init__(self, memory: RaceMemory, queue: AIRequestQueue | None, session_id: str, *, summary_interval_s: float = 300.0,
                 detector_hz: float = 2.0, thresholds: Thresholds | None = None, ai_enabled: bool = True):
        self.mem, self.queue, self.sid = memory, queue, session_id
        self.summary_interval_s, self.min_dt = summary_interval_s, 1.0 / detector_hz
        self.det = EventDetector(thresholds)
        self.ai_enabled = ai_enabled and queue is not None
        self.stats = PipelineStats()
        self._lock = threading.Lock()
        st = memory.get_meta(f"pipeline:{session_id}", {})
        self.last_summary_s = st.get("last_summary_s", 0.0)
        self.last_event_id = st.get("last_event_id", 0)
        self.last_fed = -1e9
        self.race_s = st.get("race_s", 0.0)
        self.det.import_state(st.get("detector"))
        if queue is not None:
            queue.on_result = self._on_ai_result
        self._payloads: dict[str, dict] = {}

    # ------------------------------------------------------------------ ingestion (called per sample; cheap)
    def on_sample(self, v: dict) -> None:
        self.stats.samples_in += 1
        t = float(v.get("session_time_s", 0.0))
        self.race_s = max(self.race_s, t)
        if t < self.last_fed and t > self.last_fed - 5:      # clock jitter, ignore
            return
        if t - self.last_fed < self.min_dt:
            return
        self.last_fed = t
        self.stats.samples_analysed += 1
        for e in self.det.feed(v):
            self._handle_event(e)
        if t - self.last_summary_s >= self.summary_interval_s:
            self.last_summary_s = t
            self._summary("periodic_summary", Priority.NORMAL, "periodic", ttl=self.summary_interval_s * 2)
            self._checkpoint()

    def _checkpoint(self):
        self.mem.put_meta(f"pipeline:{self.sid}", {"last_summary_s": self.last_summary_s, "last_event_id": self.last_event_id, "race_s": self.race_s,
                                                      "detector": self.det.export_state()})

    def _handle_event(self, e: Event) -> None:
        self.stats.events += 1
        lap_t = e.data if e.kind == "lap_completed" else None
        eid = self.mem.add_event(self.sid, e.race_s, e.kind, int(e.severity), e.lap, e.data, e.dedup_key)
        if lap_t:
            self.mem.add_lap(self.sid, e.lap, lap_t["time_s"], lap_t["valid"], lap_t["fuel_used_l"], lap_t["stint"], lap_t["tyre_max_c"], lap_t["wear_min"])
        if e.kind == "stint_end":
            d = e.data
            self.mem.add_stint(self.sid, d["stint"], d["start_s"], d["end_s"], d["laps"], d["avg_lap_s"], d["fuel_used_l"])
        if e.severity <= Priority.NORMAL:
            self._checkpoint()
        if e.severity <= Priority.HIGH:
            kind = {"stint_end": "stint_end", "pit_in": "pit_stop"}.get(e.kind, "event")
            if e.kind == "pit_out":
                kind = "pit_stop"
            self._summary(kind, e.severity, f"{e.kind}:{e.lap // 2}", ttl=900 if e.severity <= Priority.CRITICAL else 600, trigger=e)

    # ------------------------------------------------------------------ summaries
    def _payload(self, trigger: Event | None) -> dict:
        evs = self.mem.events_since(self.sid, self.last_event_id, min_severity=Priority.NORMAL)
        if evs:
            self.last_event_id = max(self.last_event_id, evs[-1]["id"])
        evs = [{"kind": e["kind"], "lap": e["lap"], **{k: v for k, v in e["data"].items() if isinstance(v, (int, float, str)) and not isinstance(v, bool)}}
               for e in evs[-8:]]
        p = {"race_time_s": round(self.race_s), "state": self.det.snapshot(), "events": evs,
             "stints_done": len(self.mem.stints(self.sid))}
        if trigger:
            p["trigger"] = {"kind": trigger.kind, **trigger.data}
        return p

    def _summary(self, kind: str, prio: Priority, dedup: str, ttl: float, trigger: Event | None = None) -> None:
        p = self._payload(trigger)
        txt = local_text(kind, p)
        self.mem.add_summary(self.sid, self.race_s, kind, "local", txt, p)
        self.stats.local_summaries += 1
        if not (self.ai_enabled and self.queue):
            return
        req = AIRequest(kind=kind, system=SYSTEM, user=json.dumps(p, ensure_ascii=False), priority=prio, ttl_s=ttl,
                        dedup_key=f"{self.sid}:{dedup}", max_tokens=350, session_id=self.sid)
        rid = self.queue.submit(req)
        if rid:
            self._payloads[rid] = p
            if len(self._payloads) > 400:          # bounded
                self._payloads.pop(next(iter(self._payloads)))
            self.stats.ai_enqueued += 1

    def _on_ai_result(self, req: AIRequest, resp: AIResponse) -> None:
        if req.session_id != self.sid:
            return
        try:
            payload = self._payloads.pop(req.id, None) or json.loads(req.user)
        except ValueError:
            payload = {}
        bad = ungrounded_numbers(resp.text, payload)
        if bad:
            self.stats.ai_rejected_ungrounded += 1
            self.mem.add_summary(self.sid, self.race_s, req.kind, f"ai:{resp.provider}", resp.text, {"ungrounded_numbers": bad}, status="rejected_ungrounded")
        else:
            self.stats.ai_accepted += 1
            self.mem.add_summary(self.sid, self.race_s, req.kind, f"ai:{resp.provider}:{resp.model}", resp.text, {}, status="ok")

    # ------------------------------------------------------------------ end of session
    def end_session(self) -> None:
        self._summary("final_report", Priority.HIGH, "final", ttl=6 * 3600)
        self._checkpoint()
