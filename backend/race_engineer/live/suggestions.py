"""Deterministic suggestion arbiter + alerts. No LLM is involved here: this runs in real time, the AI only interprets (see engineer.py).

* ONE main suggestion at a time, short, tied to a corner, with a confidence and the measured evidence.
* Ranking = (mode weight) x (confidence) x (time impact) x (repetition over the last laps).
* While the driver is in a demanding manoeuvre (braking, steering, inside a corner) the displayed suggestion is frozen:
  only critical alerts may interrupt.
* Not enough data -> a "learning" state, never a guess.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from ..analysis.driving import LABELS_IT
from ..analysis.session_mode import GROUP_OF, weight

MIN_SCORE = 0.10
MIN_REPEAT = 2             # a finding must be present in >= 2 of the last 3 analysed laps: one lap is indistinguishable from normal lap-to-lap variation
REPEAT_WINDOW = 3
HOLD_S = 6.0
APPROACH_M = 700.0
LEVEL_RANK = {"critical": 3, "warn": 2, "info": 1}


def text_for(f: dict) -> str:
    """Brief, precise, tied to the corner. Numbers come from the finding's own evidence."""
    c, ev, t = f["corner"], f.get("evidence", {}), f["type"]
    g = lambda k: ev.get(k)
    if t == "early_braking":
        return f"{c}: frena ~{abs(g('diff_m')):.0f} m più tardi"
    if t == "inefficient_late_braking":
        return f"{c}: frenata troppo tardi, anticipa ~{abs(g('diff_m')):.0f} m"
    if t == "braking_too_long":
        return f"{c}: rilascia il freno prima (~{(g('lap_len_m') - g('ref_len_m')):.0f} m)"
    if t == "abrupt_release":
        return f"{c}: rilascio del freno più progressivo"
    if t == "delayed_acceleration":
        d = g("diff_m") or (g("lap_throttle_on_m") - g("ref_throttle_on_m"))
        return f"{c}: gas pieno ~{abs(d):.0f} m prima"
    if t == "insufficient_min_speed":
        return f"{c}: +{abs(g('diff_kmh')):.0f} km/h all'apice"
    if t == "inefficient_line":
        return f"{c}: traiettoria più pulita, meno sterzo"
    if t in ("entry_loss", "mid_loss", "exit_loss"):
        ph = {"entry_loss": "ingresso", "mid_loss": "centro", "exit_loss": "uscita"}[t]
        return f"{c}: perdi {abs(g('phase_delta_s')):.2f} s in {ph}"
    if t == "inconsistent":
        return f"{c}: frenata incostante (±{g('brake_std_m'):.0f} m)"
    return f"{c}: {LABELS_IT.get(t, t)}"


@dataclass
class Candidate:
    key: str
    type: str
    corner: str
    phase: str
    lap: int
    text: str
    score: float
    confidence: dict
    impact_s: float | None
    repeat: int
    evidence: dict
    ref_lap: int | None = None
    group: str = "pace"

    def to_json(self) -> dict:
        return {"id": self.key, "type": self.type, "label": LABELS_IT.get(self.type, self.type), "corner": self.corner, "phase": self.phase,
                "lap": self.lap, "ref_lap": self.ref_lap, "text": self.text, "confidence": self.confidence, "impact_s": self.impact_s,
                "repeat": self.repeat, "evidence": self.evidence, "priority": round(self.score, 3), "provenance": "computed",
                "source": "driving_analysis"}


def build_candidates(history: list[dict], mode: dict) -> list[Candidate]:
    """history = the last analysed laps (``driving.analyse`` results, oldest first). Repeated findings weigh more."""
    if not history:
        return []
    last = history[-1]
    out: list[Candidate] = []
    for f in last["findings"]:
        same = [h for h in history for g in h["findings"] if g["corner"] == f["corner"] and g["type"] == f["type"]]
        rep = len(same)
        recent = history[-REPEAT_WINDOW:]
        rep_recent = sum(1 for h in recent if any(g["corner"] == f["corner"] and g["type"] == f["type"] for g in h["findings"]))
        if rep_recent < MIN_REPEAT:
            continue
        imps = [g["time_impact_s"] for h in history for g in h["findings"] if g["corner"] == f["corner"] and g["type"] == f["type"]
                and g["time_impact_s"] is not None]
        imp = f["time_impact_s"] if f["time_impact_s"] is not None else (statistics.fmean(imps) if imps else None)
        impf = 0.3 if imp is None else 0.3 + min(1.0, max(0.0, imp) / 0.15)
        grp = GROUP_OF.get(f["type"], "pace")
        score = weight(mode, grp) * f["confidence"]["score"] * impf * min(1.75, 1.0 + 0.25 * (rep - 1))
        out.append(Candidate(f"{f['corner']}.{f['type']}", f["type"], f["corner"], f["phase"], f["lap"], text_for(f), score,
                             {"level": f["confidence"]["level"], "score": f["confidence"]["score"],
                              "reasons": list(f["confidence"]["reasons"]) + [f"presente in {rep_recent} degli ultimi {len(recent)} giri analizzati"]},
                             None if imp is None else round(float(imp), 3), rep, f["evidence"], f["ref_lap"], grp))
    # consistency across laps (needs >= 3 analysed laps): brake point scatter per corner
    if len(history) >= 3:
        by: dict[str, list[float]] = {}
        for h in history:
            for r in h["corners"]:
                b = r["lap"].get("brake_start_m")
                if b is not None:
                    by.setdefault(r["corner"], []).append(b)
        for cid, xs in by.items():
            if len(xs) >= 3 and statistics.pstdev(xs) >= 12.0:
                sd = statistics.pstdev(xs)
                conf_s = min(0.9, 0.3 + 0.1 * len(xs))
                lvl = "alta" if conf_s >= .65 else "media" if conf_s >= .4 else "bassa"
                ev = {"brake_std_m": round(sd, 1), "laps": len(xs)}
                out.append(Candidate(f"{cid}.inconsistent", "inconsistent", cid, "entry", history[-1]["lap"], text_for({"corner": cid, "type": "inconsistent", "evidence": ev}),
                                     weight(mode, "consistency") * conf_s * 0.6, {"level": lvl, "score": conf_s, "reasons": [f"{len(xs)} giri analizzati"]},
                                     None, len(xs), ev, history[-1]["ref_lap"], "consistency"))
    out.sort(key=lambda c: -c.score)
    return [c for c in out if c.score >= MIN_SCORE]


def build_alerts(v: dict | None, snap: dict | None, th=None) -> list[dict]:
    """Important alerts from the SAME detector thresholds the endurance pipeline uses (fuel, tyres, engine, rain, damage)."""
    from ..endurance.detector import Thresholds, TYRES
    th = th or Thresholds()
    out: list[dict] = []
    if snap and snap.get("laps_of_fuel") is not None:
        lf = snap["laps_of_fuel"]
        if lf < th.fuel_critical_laps:
            out.append({"id": "fuel_critical", "level": "critical", "text": f"Benzina critica: ~{lf:.1f} giri", "values": {"laps_of_fuel": lf}})
        elif lf < th.fuel_low_laps:
            out.append({"id": "fuel_low", "level": "warn", "text": f"Benzina: ~{lf:.1f} giri", "values": {"laps_of_fuel": lf}})
    if v:
        tt = max((v.get(f"tyre_{w}_temp_center_c") or 0.0) for w in TYRES)
        if tt > th.tyre_temp_high_c:
            out.append({"id": "tyre_temp_high", "level": "warn", "text": f"Gomme calde: {tt:.0f} °C", "values": {"tyre_temp_c": round(tt, 1)}})
        wc, oc = v.get("water_temp_c") or 0.0, v.get("oil_temp_c") or 0.0
        if wc > th.water_temp_high_c or oc > th.oil_temp_high_c or v.get("overheating"):
            out.append({"id": "engine_temp_high", "level": "critical" if v.get("overheating") else "warn",
                        "text": f"Motore caldo: acqua {wc:.0f} °C, olio {oc:.0f} °C", "values": {"water_c": wc, "oil_c": oc}})
        if (v.get("rain") or 0.0) >= th.rain_on:
            out.append({"id": "rain", "level": "info", "text": "Pioggia sul circuito", "values": {"rain": round(float(v["rain"]), 2)}})
        if (v.get("damage_dent_max") or 0) >= 2 or v.get("parts_detached"):
            out.append({"id": "damage", "level": "warn", "text": "Danni alla vettura", "values": {"dent_max": v.get("damage_dent_max"), "detached": bool(v.get("parts_detached"))}})
    out.sort(key=lambda a: -LEVEL_RANK[a["level"]])
    return out


@dataclass
class Arbiter:
    """Keeps ONE suggestion on screen with hysteresis and freezes it while the driver is busy."""
    hold_s: float = HOLD_S
    current: Candidate | None = None
    since: float = 0.0
    frozen: bool = False
    changes: int = 0
    _last_key: str | None = None

    def update(self, cands: list[Candidate], now: float, next_corner: str | None, dist_to_next_m: float | None, demanding: bool) -> Candidate | None:
        cur_valid = self.current is not None and any(c.key == self.current.key for c in cands)
        if demanding and self.current is not None:
            self.frozen = True
            return self.current                      # never change what the driver is reading while busy
        self.frozen = False
        if not cands:
            self.current = None
            return None
        best = cands[0]
        ahead = None
        if next_corner is not None and dist_to_next_m is not None and dist_to_next_m <= APPROACH_M:
            ahead = next((c for c in cands if c.corner == next_corner), None)
        pick = ahead or best
        if self.current is not None and cur_valid and now - self.since < self.hold_s:
            return self.fresh(self.current, cands)
        if self.current is None or pick.key != self.current.key:
            self.current, self.since = pick, now
            self.changes += 1
        else:
            self.current = self.fresh(pick, cands)
        return self.current

    @staticmethod
    def fresh(cur: Candidate, cands: list[Candidate]) -> Candidate:
        return next((c for c in cands if c.key == cur.key), cur)
