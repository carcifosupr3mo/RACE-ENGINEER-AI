"""The coach: lifecycle of the instructions, memory of the driver and the end-of-lap review.

It is a component of the ONE ``LiveEngineer`` (no second engine): it does not read telemetry, it does not analyse laps. It consumes the
results of ``analysis.driving.analyse`` (the single analysis implementation) and the shared candidate list, and keeps the state that
turns single findings into coaching:

* an instruction gets a lifecycle: nuovo -> mostrato -> applicato | da_rivalutare | non_verificabile, judged on the laps that follow;
* repeated, not-followed advice is re-assessed (its priority drops) instead of being repeated forever;
* opposite advice on the same corner is not given within a couple of laps (no ping-pong);
* a mistake seen in most laps is a *habit*, a rare one is *occasional*, one that disappeared is *corrected*;
* laps recorded in clearly different conditions are *not comparable*: they neither create nor judge advice.
"""
from __future__ import annotations

import math
import statistics
from typing import Any

from ..storage.coach_memory import LEVELS, CoachMemory
from . import instructions as ins

OPPOSITE = {
    "early_braking": {"inefficient_late_braking"}, "inefficient_late_braking": {"early_braking"},
    "braking_too_long": {"insufficient_trail_braking"}, "insufficient_trail_braking": {"braking_too_long", "excess_trail_braking"},
    "excess_trail_braking": {"insufficient_trail_braking"}, "delayed_acceleration": {"aggressive_throttle"}, "aggressive_throttle": {"delayed_acceleration"},
}
OPPOSITE_WINDOW_LAPS = 2
REASSESS_PENALTY = 0.4
MAX_NOT_FOLLOWED = 2          # evaluations without effect before the hypothesis is re-assessed
MAX_SKIPPED = 3               # non-comparable laps before the tip becomes "non_verificabile"
TOP_TIPS_PER_LAP = 3
COND_LIMITS = {"rain": 0.15, "track_temp_c": 10.0}      # beyond these a lap is NOT comparable
COND_WARN = {"track_temp_c": 5.0, "fuel_l": 20.0, "wear": 0.15}


def magnitude(f: dict) -> float | None:
    """How far this lap is from the reference on the finding's own measure (always >= 0). None when the type has no single measure."""
    ev, t = f.get("evidence") or {}, f["type"]
    g = ev.get
    v = None
    if t in ("early_braking", "inefficient_late_braking"):
        v = g("diff_m")
    elif t == "braking_too_long" and g("lap_len_m") is not None and g("ref_len_m") is not None:
        v = g("lap_len_m") - g("ref_len_m")
    elif t == "abrupt_release" and g("lap_release_span_m") is not None and g("ref_release_span_m") is not None:
        v = g("ref_release_span_m") - g("lap_release_span_m")
    elif t == "delayed_acceleration":
        v = g("diff_m") if g("diff_m") is not None else (None if g("lap_throttle_on_m") is None or g("ref_throttle_on_m") is None
                                                        else g("lap_throttle_on_m") - g("ref_throttle_on_m"))
    elif t == "insufficient_min_speed":
        v = g("diff_kmh")
    elif t == "insufficient_trail_braking" and g("lap_trail_m") is not None and g("ref_trail_m") is not None:
        v = g("ref_trail_m") - g("lap_trail_m")
    elif t == "excess_trail_braking" and g("lap_trail_m") is not None and g("ref_trail_m") is not None:
        v = g("lap_trail_m") - g("ref_trail_m")
    elif t == "aggressive_throttle" and g("lap_ramp_m") is not None and g("ref_ramp_m") is not None:
        v = g("ref_ramp_m") - g("lap_ramp_m")
    elif t == "inefficient_line" and g("ratio") is not None:
        v = g("ratio") - 1.0
    return None if v is None or not math.isfinite(v) else abs(float(v))


def lap_conditions(cols: dict) -> dict:
    """Conditions of ONE lap from the live columns (mean over the lap; None when the channel was not acquired)."""
    import numpy as np

    def m(name):
        a = cols.get(name)
        if a is None:
            return None
        a = np.asarray(a, dtype=float)
        a = a[np.isfinite(a)]
        return float(a.mean()) if len(a) else None
    wear = [m(f"tyre_{w}_wear") for w in ("fl", "fr", "rl", "rr")]
    wear = [w for w in wear if w is not None]
    fuel = cols.get("fuel_l")
    fuel0 = None
    if fuel is not None:
        f = np.asarray(fuel, dtype=float)
        f = f[np.isfinite(f)]
        fuel0 = float(f[0]) if len(f) else None
    return {"rain": m("rain"), "track_temp_c": m("track_temp_c"), "fuel_l": fuel0, "wear": (sum(wear) / len(wear)) if wear else None}


def comparable(lap: dict | None, ref: dict | None) -> dict:
    """Is this lap comparable with the reference? Unknown values never block (they are reported as missing)."""
    if not lap or not ref:
        return {"ok": True, "verified": False, "reasons": [], "warnings": [],
                "missing": ["condizioni del giro di riferimento non registrate (riferimento di un'altra sessione): confrontabilità non verificabile"]}
    reasons, warns, missing = [], [], []
    for k, lim in COND_LIMITS.items():
        a, b = lap.get(k), ref.get(k)
        if a is None or b is None:
            missing.append({"rain": "pioggia", "track_temp_c": "temperatura pista"}[k] + " non disponibile")
        elif abs(a - b) >= lim:
            reasons.append(("pioggia diversa" if k == "rain" else f"temperatura pista diversa di {abs(a - b):.0f} °C"))
    for k, lim in COND_WARN.items():
        a, b = lap.get(k), ref.get(k)
        if a is not None and b is not None and abs(a - b) >= lim and k not in COND_LIMITS:
            warns.append({"fuel_l": f"carburante diverso di {abs(a - b):.0f} L", "wear": "usura gomme diversa"}[k])
        elif a is not None and b is not None and k in COND_LIMITS and lim > abs(a - b) >= lim / 2:
            warns.append(f"temperatura pista diversa di {abs(a - b):.0f} °C")
    # verified = BOTH limiting channels (rain, track temperature) are known on both laps. Otherwise the comparison cannot be established:
    # advice may still be shown (capped confidence) but its effect is NEVER judged ("non_verificabile").
    verified = not missing
    return {"ok": not reasons, "verified": verified and not reasons, "reasons": reasons, "warnings": warns, "missing": missing}


def cap_confidence(res: dict | None, comp: dict) -> None:
    """Unverified comparability -> a finding can be at most 'media' confidence (in place, same structure)."""
    if res is None or comp.get("verified", False):
        return
    for f in res["findings"]:
        c = f["confidence"]
        if c["level"] == "alta":
            c["level"] = "media"
            c["score"] = min(c["score"], 0.64)
            c["reasons"] = list(c["reasons"]) + ["condizioni del giro di riferimento non verificabili: confidenza limitata a «media»"]


def fmt_time(s: float | None) -> str:
    if s is None:
        return "–"
    m, r = divmod(float(s), 60)
    return f"{int(m)}:{r:06.3f}"


class Coach:
    def __init__(self, catalog, clock):
        self.mem = CoachMemory(catalog, clock)
        self.clock = clock
        self.track = self.vehicle = ""
        self.synthetic = False
        self.sid: str | None = None
        self.lap_now: int | None = None
        self._tips: dict[str, int] = {}              # candidate key -> open tip id (this session)

    # ------------------------------------------------------------------ session
    def bind(self, sid, track, vehicle, synthetic) -> None:
        self.sid, self.track, self.vehicle, self.synthetic = sid, track or "", vehicle or "", bool(synthetic)
        self._tips = {t["key"]: t["id"] for t in self.mem.open_tips(self.track, self.vehicle, self.synthetic)}

    def prefs(self) -> dict:
        return self.mem.prefs()

    # ------------------------------------------------------------------ candidates: memory-aware filtering (pure re-ranking, no new analysis)
    def decorate(self, cands: list) -> list:
        prefs = self.mem.prefs()
        min_lvl = LEVELS.get(prefs["min_confidence"], 0)
        out = []
        for c in cands:
            if LEVELS.get(c.confidence["level"], 0) < min_lvl:
                continue
            tip = self.mem.last_tip(self.track, self.vehicle, self.synthetic, c.key)
            c.reassess = bool(tip and tip["status"] == "da_rivalutare")
            if c.reassess:
                c.score *= REASSESS_PENALTY
            if self._suppressed_by_opposite(c):
                continue
            out.append(c)
        out.sort(key=lambda c: -c.score)
        return out

    def _suppressed_by_opposite(self, c) -> bool:
        if c.confidence["level"] == "alta":
            return False
        for opp in OPPOSITE.get(c.type, ()):
            t = self.mem.last_tip(self.track, self.vehicle, self.synthetic, f"{c.corner}.{opp}")
            if t and t["status"] in ("nuovo", "mostrato", "applicato") and t.get("shown_lap") is not None \
                    and self.lap_now is not None and self.lap_now - t["shown_lap"] <= OPPOSITE_WINDOW_LAPS:
                return True
        return False

    # ------------------------------------------------------------------ instructions
    def instruction(self, c: dict, *, corner: dict | None, mode: dict, rel: dict, reassess: bool = False) -> dict:
        now = self.clock()
        i = ins.build(c, corner=corner, mode=mode, reference=rel, now=now)
        tid = self._tips.get(c["id"])
        tip = self.mem.tip(tid) if tid else None
        hb = self.mem.habit(self.track, self.vehicle, self.synthetic, c["corner"], c["type"])
        i["habit"] = hb
        i["tip_id"] = tid
        i["status"] = tip["status"] if tip else "nuovo"
        if reassess or (tip and tip["status"] == "da_rivalutare"):
            i["reassessment"] = ("Questo consiglio è già stato dato senza un effetto misurabile: l'ipotesi potrebbe non essere quella giusta, "
                                 "quindi ha meno priorità. Controlla anche le altre fasi della curva.")
        if hb["classification"] == "abitudine":
            i["habit_note"] = f"Errore ricorrente: visto in {hb['laps_seen']} giri su {hb['laps_analysed']}."
        elif hb["classification"] == "occasionale" and hb["laps_seen"] >= 2:
            i["habit_note"] = f"Visto {hb['laps_seen']} volte: per ora occasionale."
        if self.mem.prefs()["verbosity"] == "breve":
            i["how"], i["why"] = i["how"], ""
        return i

    def sync_tips(self, cands: list, mode: dict, rel: dict, corners: dict) -> None:
        """Register (once) the top candidates as 'nuovo'. A key that already has an open tip keeps it."""
        for c in cands[:TOP_TIPS_PER_LAP]:
            if c.key in self._tips and (self.mem.tip(self._tips[c.key]) or {}).get("status") in ("nuovo", "mostrato"):
                continue
            j = c.to_json()
            inst = self.instruction(j, corner=corners.get(c.corner), mode=mode, rel=rel, reassess=getattr(c, "reassess", False))
            mag = magnitude({"type": c.type, "evidence": c.evidence})
            self._tips[c.key] = self.mem.new_tip(session_id=self.sid, track=self.track, vehicle=self.vehicle, synthetic=self.synthetic, corner=c.corner,
                                                 type_=c.type, lap=c.lap, confidence=c.confidence["level"], impact_s=c.impact_s, mag=mag, instruction=inst)

    def displayed(self, key: str, lap: int | None) -> None:
        tid = self._tips.get(key)
        if tid:
            self.mem.mark_shown(tid, lap)

    # ------------------------------------------------------------------ after each analysed lap
    def lap_closed(self, res: dict | None, *, lap: int, comp: dict) -> list[dict]:
        """Judge the open tips on the lap just analysed and update the habits. Returns the evaluations (for the review)."""
        self.lap_now = lap
        evals: list[dict] = []
        if res is None:
            return evals
        found = {f"{f['corner']}.{f['type']}": f for f in res["findings"]}
        for tip in self.mem.open_tips(self.track, self.vehicle, self.synthetic):
            if tip["status"] == "nuovo" and comp["ok"] and tip["key"] not in found and tip["lap_issued"] is not None and tip["lap_issued"] < lap:
                # never displayed and the problem is gone: nothing to judge, and it must not stay open for ever
                self.mem.evaluate(tip["id"], status="non_verificabile", outcome="non_mostrato", lap=lap, impact_after=0.0, count=False)
                self._tips.pop(tip["key"], None)
                continue
            if tip["status"] != "mostrato" or tip["shown_lap"] is None or tip["shown_lap"] > lap:
                continue                                           # not displayed before this lap: cannot be judged on it
            rec = {"tip_id": tip["id"], "key": tip["key"], "corner": tip["corner"], "type": tip["type"], "headline": tip["instruction"].get("headline"),
                   "corner_label": tip["instruction"].get("corner_label")}
            if not (comp["ok"] and comp.get("verified", False)):
                why = "; ".join(comp["reasons"]) or "condizioni (pioggia/temperatura pista) non note su uno dei due giri: confronto non verificabile"
                skipped = tip["skipped"] + 1
                st = "non_verificabile" if skipped >= MAX_SKIPPED else "mostrato"
                oc = "non_confrontabile" if not comp["ok"] else "non_verificabile"
                self.mem.evaluate(tip["id"], status=st, outcome=oc, lap=lap, impact_after=None, count=False, skipped=True)
                evals.append({**rec, "status": st, "outcome": oc, "why": why})
                continue
            f = found.get(tip["key"])
            if f is None and tip["outcome"] != "miglioramento_osservato":
                # first lap without the problem: an OBSERVED improvement, not yet a stable one (one lap can be luck) -> wait for a confirmation
                self.mem.evaluate(tip["id"], status="mostrato", outcome="miglioramento_osservato", lap=lap, impact_after=0.0)
                evals.append({**rec, "status": "mostrato", "outcome": "miglioramento_osservato", "impact_before_s": tip["impact_before_s"], "impact_after_s": 0.0})
                continue
            if f is None:
                self.mem.evaluate(tip["id"], status="applicato", outcome="seguito_migliorato", lap=lap, impact_after=0.0)
                self.mem.mark_fixed(self.track, self.vehicle, self.synthetic, tip["corner"], tip["type"])
                self._tips.pop(tip["key"], None)
                evals.append({**rec, "status": "applicato", "outcome": "seguito_migliorato", "impact_before_s": tip["impact_before_s"], "impact_after_s": 0.0})
                continue
            mag_a, mag_b, imp_a, imp_b = magnitude(f), tip["mag_before"], f.get("time_impact_s"), tip["impact_before_s"]
            worse = imp_a is not None and imp_b is not None and imp_a >= imp_b * 1.3 + 0.01
            better = imp_a is not None and imp_b is not None and imp_a <= imp_b * 0.7
            moved = None if mag_a is None or not mag_b else (mag_b - mag_a) / mag_b
            if worse or (moved is not None and moved <= -0.3 and (imp_a or 0) > 0):
                out, st = "peggiorato", "da_rivalutare"
            elif moved is not None and moved >= 0.4:
                out, st = ("parziale", "mostrato") if better else ("seguito_non_efficace", "da_rivalutare")
            elif moved is not None and moved >= 0.15:
                out, st = "parziale", "mostrato"
            elif better:
                out, st = "parziale", "mostrato"
            else:
                out = "non_seguito"
                st = "da_rivalutare" if tip["evaluations"] + 1 >= MAX_NOT_FOLLOWED else "mostrato"
            self.mem.evaluate(tip["id"], status=st, outcome=out, lap=lap, impact_after=imp_a, new_impact_before=imp_a if st == "mostrato" else None,
                              new_mag=mag_a if st == "mostrato" else None)
            if st == "da_rivalutare":
                self._tips.pop(tip["key"], None)
            evals.append({**rec, "status": st, "outcome": out, "impact_before_s": imp_b, "impact_after_s": imp_a, "magnitude_before": mag_b, "magnitude_after": mag_a})
        if comp["ok"]:
            for f in res["findings"]:
                self.mem.seen(self.track, self.vehicle, self.synthetic, self.sid, f["corner"], f["type"], f.get("time_impact_s"))
        return evals

    # ------------------------------------------------------------------ end-of-lap review
    def review(self, *, res: dict | None, lap: int, time_s: float | None, best_s: float | None, prev_res: dict | None, prev_time: float | None,
               session_times: list[float], comp: dict, evals: list[dict], corners: dict, next_focus: dict | None, mode: dict) -> dict:
        """Deterministic explanation of the lap (Italian). Numbers support the sentences; nothing here calls a model."""
        rows, improved, worsened = [], [], []
        gained = lost = 0.0
        if res is not None:
            prev_by = {} if prev_res is None else {r["corner"]: r["zone_delta_s"] for r in prev_res["corners"]}
            for r in res["corners"]:
                zd, pz = r["zone_delta_s"], prev_by.get(r["corner"])
                ch = None if zd is None or pz is None else round(zd - pz, 3)
                rows.append({"corner": r["corner"], "label": ins.corner_label(r["corner"], (corners.get(r["corner"]) or {}).get("provisional", True)),
                             "vs_best_s": zd, "vs_prev_s": ch})
                if ch is not None and ch <= -0.02:
                    improved.append(rows[-1]); gained += -ch
                elif ch is not None and ch >= 0.02:
                    worsened.append(rows[-1]); lost += ch
        findings = [] if res is None else res["findings"]
        prev_keys = set() if prev_res is None else {(f["corner"], f["type"]) for f in prev_res["findings"]}
        new = [f for f in findings if (f["corner"], f["type"]) not in prev_keys]
        recurring = []
        for f in findings:
            hb = self.mem.habit(self.track, self.vehicle, self.synthetic, f["corner"], f["type"])
            if hb["classification"] == "abitudine":
                recurring.append({"corner": f["corner"], "type": f["type"], "label": f["label"], **hb})
        applied = [e for e in evals if e["status"] == "applicato"]
        not_applied = [e for e in evals if e["outcome"] in ("non_seguito", "seguito_non_efficace", "peggiorato")]
        d_best = None if time_s is None or best_s is None else round(time_s - best_s, 3)
        d_prev = None if time_s is None or prev_time is None else round(time_s - prev_time, 3)
        avg = statistics.fmean(session_times) if len(session_times) >= 3 else None
        lab = lambda r: r["label"]
        parts = []
        if time_s is not None:
            s = f"GIRO {lap} COMPLETATO — {fmt_time(time_s)}"
            if d_best is not None:
                s += " (miglior giro personale)" if d_best <= 0 else f" ({d_best:+.3f} s dal tuo miglior giro)"
            parts.append(s + ".")
        if not comp["ok"]:
            parts.append("Condizioni diverse dal giro di riferimento (" + "; ".join(comp["reasons"]) + "): il giro non è confrontabile, nessuna valutazione dei consigli.")
        else:
            if improved:
                parts.append("Curve migliorate rispetto al giro precedente: " + ", ".join(f"{lab(r)} ({-r['vs_prev_s']:.2f} s)" for r in improved[:3]) + ".")
            if worsened:
                parts.append("Curve peggiorate: " + ", ".join(f"{lab(r)} (+{r['vs_prev_s']:.2f} s)" for r in worsened[:3]) + ".")
            if findings:
                f0 = findings[0]
                parts.append(f"Il problema principale è in {ins.corner_label(f0['corner'], (corners.get(f0['corner']) or {}).get('provisional', True))}: "
                             f"{f0['label'].lower()}" + (f", circa {f0['time_impact_s']:.2f} s" if f0.get("time_impact_s") else "") + ".")
            elif res is not None:
                parts.append("Nessuna perdita significativa rispetto al riferimento in questo giro.")
            for e in applied[:2]:
                parts.append(f"Consiglio applicato: {e['corner_label']} — {e['headline'].lower()}.")
            for e in not_applied[:2]:
                parts.append(f"Consiglio non risolto: {e['corner_label']} — {e['headline'].lower()} ({e['outcome'].replace('_', ' ')}).")
            if recurring:
                r0 = recurring[0]
                parts.append(f"Errore ricorrente: {r0['label'].lower()} in {ins.corner_label(r0['corner'])} ({r0['laps_seen']} giri su {r0['laps_analysed']}).")
            if next_focus:
                parts.append(f"Nel prossimo giro concentrati su {next_focus['corner_label']}: {next_focus['headline'].lower()}.")
        missing = list(comp.get("missing", [])) + ["traffico e avversari: non rilevabili", "differenze di setup: non rilevabili dalla telemetria acquisita"]
        return {
            "lap": lap, "time_s": time_s, "best_s": best_s, "delta_best_s": d_best, "delta_prev_s": d_prev, "session_avg_s": None if avg is None else round(avg, 3),
            "comparable": comp, "corners": rows, "improved": improved, "worsened": worsened, "time_gained_vs_prev_s": round(gained, 3), "time_lost_vs_prev_s": round(lost, 3),
            "new_findings": [{"corner": f["corner"], "type": f["type"], "label": f["label"], "impact_s": f.get("time_impact_s")} for f in new[:5]],
            "recurring": recurring[:5], "tips_evaluated": evals, "next_focus": next_focus, "mode": mode.get("label"),
            "summary": " ".join(parts), "missing": missing, "provenance": "computed", "language": "it",
        }

    def save_review(self, review: dict, findings: int) -> None:
        self.mem.save_lap(self.sid, review["lap"], self.track, self.vehicle, self.synthetic, review["time_s"], review["delta_best_s"], findings, review)


def corners_meta(ref) -> dict[str, Any]:
    return {} if ref is None or not ref.anchor else {c.id: c.to_json() for c in ref.corners()}
