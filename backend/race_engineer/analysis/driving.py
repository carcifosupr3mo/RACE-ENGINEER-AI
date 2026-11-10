"""Driving analysis: per-corner phases (braking -> release -> apex -> throttle -> exit) and whole-corner evaluation.

This module EXTENDS ``compare.corner_metrics`` (it calls it, it does not re-implement brake/throttle detection) and is the
single implementation used by BOTH the live engineer (``live.engineer``) and the post-session API / AI facts, so the
dashboard and the Driving Display can never disagree about the same lap.

Principles
* A later braking point is NOT automatically better: a finding is judged on the whole corner (entry/mid/exit segment
  times from the distance-aligned time axis, minimum speed, exit speed).  A later braking that gains time is reported as a
  *gain*, never as an error.
* Every finding carries the measured evidence, the time impact of the phase and a confidence (level + score + reasons)
  that depends on the size of the effect and on how reliable the reference is.
* Nothing is invented: a metric that cannot be measured is ``None`` and the rules that need it do not fire.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field

import numpy as np

from .align import AlignedLap, delta_time
from .compare import BRAKE_THR, CornerMetrics, corner_metrics
from .corners import Corner

PHASES = ("entry", "mid", "exit")
# which finding types "explain" a phase loss (so the generic *_loss finding is not added on top of them)
PHASE_OF = {"early_braking": "entry", "inefficient_late_braking": "entry", "braking_too_long": "entry",
            "abrupt_release": "mid", "insufficient_min_speed": "mid", "inefficient_line": "mid",
            "delayed_acceleration": "exit", "insufficient_trail_braking": "entry", "excess_trail_braking": "mid",
            "aggressive_throttle": "exit", "gear_choice": "mid", "entry_loss": "entry", "mid_loss": "mid", "exit_loss": "exit"}
LABELS_IT = {
    "early_braking": "Frenata anticipata", "inefficient_late_braking": "Frenata tardiva inefficiente",
    "braking_too_long": "Frenata troppo lunga", "abrupt_release": "Rilascio del freno brusco",
    "delayed_acceleration": "Accelerazione ritardata", "insufficient_min_speed": "Velocità minima insufficiente",
    "inefficient_line": "Traiettoria inefficiente", "entry_loss": "Perdita in ingresso", "mid_loss": "Perdita a centro curva",
    "exit_loss": "Perdita in uscita", "late_braking_gain": "Frenata tardiva efficace",
    "insufficient_trail_braking": "Trail braking insufficiente", "excess_trail_braking": "Trail braking eccessivo",
    "aggressive_throttle": "Accelerazione troppo brusca", "gear_choice": "Marcia diversa dal riferimento",
}


@dataclass
class DrivingThresholds:
    brake_point_m: float = 15.0
    long_brake_m: float = 15.0
    release_later_m: float = 8.0
    min_speed_kmh: float = 2.0
    exit_speed_kmh: float = 3.0
    throttle_m: float = 15.0
    abrupt_span_m: float = 6.0          # brake pressure falls from 80 % of the peak to the threshold in less than this
    abrupt_ratio: float = 0.5           # ... and in less than this fraction of the reference's span
    steer_ratio: float = 1.10
    trail_min_m: float = 12.0           # the reference holds the brake while turning for at least this long
    trail_ratio: float = 0.40           # lap trail length <= this fraction of the reference's -> insufficient
    trail_excess_m: float = 15.0
    ramp_min_m: float = 12.0            # reference throttle progression (10 % -> 90 %) at least this long
    ramp_ratio: float = 0.50
    seg_loss_s: float = 0.03            # generic phase loss
    zone_loss_s: float = 0.02
    zone_gain_s: float = 0.02
    line_loss_s: float = 0.03


@dataclass
class DrivingMetrics:
    """Everything ``CornerMetrics`` measures plus the phases needed by the driving analysis."""
    base: CornerMetrics
    entry_speed_kmh: float | None = None
    brake_peak_m: float | None = None
    brake_ramp_m: float | None = None        # distance from brake application to 90 % of the peak (progression)
    brake_length_m: float | None = None
    release_span_m: float | None = None      # distance over which pressure drops from 80 % of peak to the threshold
    throttle_on_m: float | None = None       # first throttle >= 10 % after the minimum speed
    steer_abs_mean: float | None = None      # mean |steering| around the apex (line indicator)
    trail_m: float | None = None             # distance where the brake is still applied (> threshold) while the wheel is turned
    throttle_ramp_m: float | None = None     # distance from 10 % to 90 % throttle after the minimum speed (progression)
    gear_apex: int | None = None             # gear engaged at the minimum speed
    shifts: int | None = None                # gear changes between corner entry and exit
    seg_t: dict = field(default_factory=dict)     # phase -> duration (s)
    bounds_m: tuple = ()

    def to_json(self) -> dict:
        d = self.base.to_json()
        for k in ("entry_speed_kmh", "brake_peak_m", "brake_ramp_m", "brake_length_m", "release_span_m", "throttle_on_m", "steer_abs_mean",
                  "trail_m", "throttle_ramp_m"):
            v = getattr(self, k)
            d[k] = None if v is None or not np.isfinite(v) else round(float(v), 3)
        d["gear_apex"], d["shifts"] = self.gear_apex, self.shifts
        d["segments_s"] = {k: (None if v is None or not np.isfinite(v) else round(float(v), 3)) for k, v in self.seg_t.items()}
        return d


def _ix(g: np.ndarray, m: float) -> int:
    step = float(g[1] - g[0]) if len(g) > 1 else 1.0
    return int(np.clip(round(m / step), 0, len(g) - 1))


def driving_metrics(lap: AlignedLap, c: Corner) -> DrivingMetrics:
    base = corner_metrics(lap, c)
    g, v, th, br = lap.grid, lap.ch["speed_kmh"], lap.ch["throttle"], lap.ch["brake"]
    st = lap.ch.get("steering")
    dm = DrivingMetrics(base)
    if base.brake_start_m is not None and base.brake_release_m is not None:
        i_s, i_r = _ix(g, base.brake_start_m), _ix(g, base.brake_release_m)
        w = np.nan_to_num(br[i_s:i_r + 1])
        if len(w) and w.max() > BRAKE_THR:
            pk = float(w.max())
            i_pk = i_s + int(np.argmax(w))
            dm.brake_peak_m = float(g[i_pk])
            dm.brake_ramp_m = float(g[i_s + int(np.argmax(w >= 0.9 * pk))] - g[i_s])
            dm.brake_length_m = float(g[i_r] - g[i_s])
            dm.entry_speed_kmh = float(v[i_s]) if np.isfinite(v[i_s]) else None
            hi = np.flatnonzero(np.nan_to_num(br[i_pk:i_r + 1]) >= 0.8 * pk)
            i80 = i_pk + int(hi[-1]) if len(hi) else i_pk
            dm.release_span_m = float(g[i_r] - g[i80])
    if base.min_speed_m is not None:
        k = _ix(g, base.min_speed_m)
        hi = min(len(g), _ix(g, c.exit_m + 150) + 1)
        on = np.flatnonzero(np.nan_to_num(th[k:hi]) >= 0.10)
        dm.throttle_on_m = float(g[k + int(on[0])]) if len(on) else None
    if st is not None:
        a, b = _ix(g, c.apex_m - 30), _ix(g, c.apex_m + 30)
        s = np.abs(st[a:b + 1])
        dm.steer_abs_mean = float(np.nanmean(s)) if np.isfinite(s).any() else None
    if st is not None and base.brake_start_m is not None and base.brake_release_m is not None:
        a, b = _ix(g, c.entry_m), _ix(g, c.exit_m)
        sw = np.abs(np.nan_to_num(st[a:b + 1]))
        if len(sw) and sw.max() > 0:
            thr_s = max(0.05, 0.25 * float(sw.max()))
            i_s, i_r = _ix(g, base.brake_start_m), _ix(g, base.brake_release_m)
            seg_b, seg_s = np.nan_to_num(br[i_s:i_r + 1]), np.abs(np.nan_to_num(st[i_s:i_r + 1]))
            step = float(g[1] - g[0]) if len(g) > 1 else 1.0
            dm.trail_m = float(((seg_b > BRAKE_THR) & (seg_s > thr_s)).sum() * step)
    if base.min_speed_m is not None:
        k = _ix(g, base.min_speed_m)
        hi = min(len(g), _ix(g, c.exit_m + 150) + 1)
        tw = np.nan_to_num(th[k:hi])
        lo10, hi90 = np.flatnonzero(tw >= 0.10), np.flatnonzero(tw >= 0.90)
        if len(lo10) and len(hi90) and hi90[0] >= lo10[0]:
            dm.throttle_ramp_m = float(g[k + int(hi90[0])] - g[k + int(lo10[0])])
        gr = lap.ch.get("gear")
        if gr is not None and np.isfinite(gr[k]):
            dm.gear_apex = int(gr[k])
    gr = lap.ch.get("gear")
    if gr is not None:
        w = gr[_ix(g, c.entry_m):_ix(g, c.exit_m) + 1]
        w = w[np.isfinite(w)]
        dm.shifts = int((np.diff(w) != 0).sum()) if len(w) > 1 else 0
    lo = max(0.0, c.entry_m - 120.0)
    b1 = max(lo, c.apex_m - 30.0)
    if b1 <= lo:
        b1 = (lo + c.apex_m) / 2
    b2 = c.apex_m + 30.0
    b3 = max(c.exit_m, b2 + 1.0)
    pts = [_ix(g, x) for x in (lo, b1, b2, b3)]
    t = lap.t
    dm.bounds_m = (lo, b1, b2, b3)
    for name, (i0, i1) in zip(PHASES, zip(pts[:-1], pts[1:])):
        dm.seg_t[name] = float(t[i1] - t[i0]) if np.isfinite(t[i0]) and np.isfinite(t[i1]) else None
    return dm


def confidence(effect_ratio: float, impact_s: float | None, reliability: float, aligned_ok: bool = True, why: list[str] | None = None) -> dict:
    """Score in 0..1 from (size of the effect vs its threshold) x (time actually lost) x (reliability of the reference)."""
    eff = min(1.0, max(0.0, effect_ratio) / 2.0)
    tim = 0.0 if impact_s is None else min(1.0, abs(impact_s) / 0.1)
    s = reliability * (0.35 + 0.40 * eff + 0.25 * tim)
    if not aligned_ok:
        s *= 0.5
    lvl = "alta" if s >= 0.65 else "media" if s >= 0.40 else "bassa"
    r = list(why or [])
    r.append(f"riferimento affidabile al {reliability * 100:.0f}%")
    if impact_s is None:
        r.append("tempo di fase non misurabile")
    return {"level": lvl, "score": round(float(s), 3), "reasons": r}


@dataclass
class DrivingFinding:
    type: str
    corner: str
    phase: str
    lap: int
    ref_lap: int
    evidence: dict
    time_impact_s: float | None          # time lost (+) in the affected phase vs the reference
    confidence: dict
    label: str = ""
    provenance: str = "computed"
    note: str = ("Measured difference vs the reference lap, judged on the whole corner; the phase time change is attributed "
                 "by location and is not proof of cause.")

    def to_json(self) -> dict:
        return asdict(self)


def _r(x):
    return None if x is None else round(float(x), 2)


def analyse(lap: AlignedLap, ref: AlignedLap, corners: list[Corner], th: DrivingThresholds | None = None,
            reliability: float = 1.0) -> dict:
    """Compare ``lap`` with ``ref`` corner by corner. Pure function of its inputs (same laps -> same result)."""
    th = th or DrivingThresholds()
    q_ok = bool(lap.quality.get("ok") and ref.quality.get("ok"))
    d = delta_time(lap, ref)
    rows, findings, gains = [], [], []
    for c in corners:
        m, r = driving_metrics(lap, c), driving_metrics(ref, c)
        bm, br_ = m.base, r.base
        seg = {}
        for p in PHASES:
            a, b = m.seg_t.get(p), r.seg_t.get(p)
            seg[p] = {"lap_s": a, "ref_s": b, "delta_s": None if a is None or b is None else round(a - b, 3)}
        sd = {p: seg[p]["delta_s"] for p in PHASES}
        known = [x for x in sd.values() if x is not None]
        zd = round(float(sum(known)), 3) if len(known) == 3 else None
        rows.append({"corner": c.id, "lap": m.to_json(), "ref": r.to_json(), "segments": seg, "zone_delta_s": zd})

        def add(t, phase, ratio, ev, why=None):
            imp = sd.get(phase)
            findings.append(DrivingFinding(t, c.id, phase, lap.number, ref.number, {k: _r(x) for k, x in ev.items()}, imp,
                                           confidence(ratio, imp, reliability, q_ok, why), LABELS_IT[t]))
        ms_d = None if bm.min_speed_kmh is None or br_.min_speed_kmh is None else bm.min_speed_kmh - br_.min_speed_kmh
        ex_d = None if bm.exit_speed_kmh is None or br_.exit_speed_kmh is None else bm.exit_speed_kmh - br_.exit_speed_kmh
        tail = [x for x in (sd["mid"], sd["exit"]) if x is not None]
        tail_loss = sum(tail) if tail else None
        b_d = None if bm.brake_start_m is None or br_.brake_start_m is None else bm.brake_start_m - br_.brake_start_m
        # ---- braking point, judged on the whole corner
        if b_d is not None:
            if b_d <= -th.brake_point_m and (zd is None or zd >= -0.01):
                add("early_braking", "entry", -b_d / th.brake_point_m,
                    {"lap_brake_m": bm.brake_start_m, "ref_brake_m": br_.brake_start_m, "diff_m": b_d,
                     "lap_min_kmh": bm.min_speed_kmh, "ref_min_kmh": br_.min_speed_kmh})
            elif b_d >= th.brake_point_m:
                slow = (ms_d is not None and ms_d <= -th.min_speed_kmh) or (ex_d is not None and ex_d <= -th.exit_speed_kmh) \
                    or (tail_loss is not None and tail_loss >= th.line_loss_s)
                if zd is not None and zd <= -th.zone_gain_s:
                    gains.append({"type": "late_braking_gain", "label": LABELS_IT["late_braking_gain"], "corner": c.id, "lap": lap.number,
                                  "ref_lap": ref.number, "time_gain_s": -zd,
                                  "evidence": {"lap_brake_m": _r(bm.brake_start_m), "ref_brake_m": _r(br_.brake_start_m), "diff_m": _r(b_d)},
                                  "provenance": "computed"})
                elif slow and (zd is None or zd >= th.zone_loss_s):
                    add("inefficient_late_braking", "entry", b_d / th.brake_point_m,
                        {"lap_brake_m": bm.brake_start_m, "ref_brake_m": br_.brake_start_m, "diff_m": b_d,
                         "min_speed_diff_kmh": ms_d, "exit_speed_diff_kmh": ex_d})
        # ---- braking too long: released later than the reference
        rel_d = None if bm.brake_release_m is None or br_.brake_release_m is None else bm.brake_release_m - br_.brake_release_m
        if m.brake_length_m is not None and r.brake_length_m is not None and rel_d is not None:
            ln = m.brake_length_m - r.brake_length_m
            if ln >= th.long_brake_m and rel_d >= th.release_later_m and (zd is None or zd >= th.zone_loss_s):
                add("braking_too_long", "entry", ln / th.long_brake_m,
                    {"lap_len_m": m.brake_length_m, "ref_len_m": r.brake_length_m, "release_diff_m": rel_d})
        # ---- abrupt release
        if m.release_span_m is not None and bm.brake_peak and bm.brake_peak >= 0.5:
            ref_span = r.release_span_m
            # abrupt = clearly more abrupt than the reference's own release (an equally abrupt reference is not a difference)
            if ref_span is not None and ref_span > th.abrupt_span_m and m.release_span_m <= th.abrupt_ratio * ref_span \
                    and ((sd["mid"] is not None and sd["mid"] >= 0.01) or (zd is not None and zd >= th.zone_loss_s)):
                add("abrupt_release", "mid", th.abrupt_span_m / max(m.release_span_m, 0.5),
                    {"lap_release_span_m": m.release_span_m, "ref_release_span_m": ref_span, "lap_peak": bm.brake_peak})
        # ---- delayed acceleration
        t_d = None if bm.throttle_pickup_m is None or br_.throttle_pickup_m is None else bm.throttle_pickup_m - br_.throttle_pickup_m
        on_d = None if m.throttle_on_m is None or r.throttle_on_m is None else m.throttle_on_m - r.throttle_on_m
        if (t_d is not None and t_d >= th.throttle_m) or (on_d is not None and on_d >= th.throttle_m):
            add("delayed_acceleration", "exit", max(t_d or 0, on_d or 0) / th.throttle_m,
                {"lap_full_throttle_m": bm.throttle_pickup_m, "ref_full_throttle_m": br_.throttle_pickup_m, "diff_m": t_d,
                 "lap_throttle_on_m": m.throttle_on_m, "ref_throttle_on_m": r.throttle_on_m})
        # ---- minimum speed
        if ms_d is not None and ms_d <= -th.min_speed_kmh and ((sd["mid"] is not None and sd["mid"] >= 0.01) or (zd is not None and zd >= th.zone_loss_s / 2)
                                                              or sd["mid"] is None):
            add("insufficient_min_speed", "mid", -ms_d / th.min_speed_kmh,
                {"lap_min_kmh": bm.min_speed_kmh, "ref_min_kmh": br_.min_speed_kmh, "diff_kmh": ms_d})
        # ---- line: more steering around the apex without a pedal explanation
        if m.steer_abs_mean is not None and r.steer_abs_mean is not None and r.steer_abs_mean > 0.02:
            ratio = m.steer_abs_mean / r.steer_abs_mean
            pedals_ok = (b_d is None or abs(b_d) < th.brake_point_m) and (t_d is None or t_d < th.throttle_m)
            if ratio >= th.steer_ratio and pedals_ok and ((ms_d is not None and ms_d <= -1.0) or (sd["mid"] is not None and sd["mid"] >= th.line_loss_s)):
                add("inefficient_line", "mid", (ratio - 1.0) / (th.steer_ratio - 1.0),
                    {"lap_steer_mean": m.steer_abs_mean, "ref_steer_mean": r.steer_abs_mean, "ratio": ratio, "min_speed_diff_kmh": ms_d})
        # ---- trail braking (only when the reference actually trails and this lap loses time on entry/centre)
        names = {f.type for f in findings if f.corner == c.id}
        if m.trail_m is not None and r.trail_m is not None:
            em_loss = (sd["entry"] or 0.0) + (sd["mid"] or 0.0)
            slow = (ms_d is not None and ms_d <= -th.min_speed_kmh) or em_loss >= th.seg_loss_s
            if r.trail_m >= th.trail_min_m and m.trail_m <= th.trail_ratio * r.trail_m and slow \
                    and not names & {"braking_too_long", "abrupt_release"}:
                add("insufficient_trail_braking", "entry", (r.trail_m - m.trail_m) / th.trail_min_m,
                    {"lap_trail_m": m.trail_m, "ref_trail_m": r.trail_m, "min_speed_diff_kmh": ms_d})
            elif m.trail_m - r.trail_m >= th.trail_excess_m and m.trail_m >= 1.8 * max(r.trail_m, 1.0) \
                    and ((sd["mid"] or 0.0) + (sd["exit"] or 0.0) >= th.seg_loss_s) and (rel_d is not None and rel_d >= th.release_later_m) \
                    and not names & {"braking_too_long", "abrupt_release"}:
                add("excess_trail_braking", "mid", (m.trail_m - r.trail_m) / th.trail_excess_m,
                    {"lap_trail_m": m.trail_m, "ref_trail_m": r.trail_m, "release_diff_m": rel_d})
        # ---- throttle progression: much faster than the reference AND the exit is slower (no claim about wheelspin: not measured)
        if m.throttle_ramp_m is not None and r.throttle_ramp_m is not None and r.throttle_ramp_m >= th.ramp_min_m \
                and m.throttle_ramp_m <= th.ramp_ratio * r.throttle_ramp_m and (sd["exit"] or 0.0) >= th.seg_loss_s \
                and "delayed_acceleration" not in names:
            add("aggressive_throttle", "exit", (r.throttle_ramp_m - m.throttle_ramp_m) / th.ramp_min_m,
                {"lap_ramp_m": m.throttle_ramp_m, "ref_ramp_m": r.throttle_ramp_m, "exit_speed_diff_kmh": ex_d})
        # ---- gear at the apex differs from the reference while the corner is slower
        if m.gear_apex is not None and r.gear_apex is not None and m.gear_apex != r.gear_apex and r.gear_apex > 0 and m.gear_apex > 0 \
                and ((ms_d is not None and ms_d <= -th.min_speed_kmh) or (sd["exit"] or 0.0) >= th.seg_loss_s):
            add("gear_choice", "mid", 1.0, {"lap_gear": m.gear_apex, "ref_gear": r.gear_apex, "min_speed_diff_kmh": ms_d, "lap_shifts": m.shifts, "ref_shifts": r.shifts})
        # ---- generic phase losses not already explained
        have = {f.phase for f in findings if f.corner == c.id}
        for p in PHASES:
            if p not in have and sd[p] is not None and sd[p] >= th.seg_loss_s:
                add(f"{p}_loss", p, sd[p] / th.seg_loss_s, {"phase_delta_s": sd[p]})
    findings.sort(key=lambda f: -(f.time_impact_s or 0.0))
    fin = d[np.isfinite(d)]
    return {"lap": lap.number, "ref_lap": ref.number, "total_delta_s": float(fin[-1]) if len(fin) else None, "aligned_ok": q_ok,
            "reference_reliability": round(float(reliability), 3), "corners": rows, "findings": [f.to_json() for f in findings], "gains": gains,
            "thresholds": asdict(th), "provenance": "computed"}


def zones(ref: AlignedLap, corners: list[Corner], min_brake_m: float = 10.0) -> list[dict]:
    """Braking / release / acceleration zones measured on the reference lap (distance ranges + their peak)."""
    g, br, th = ref.grid, np.nan_to_num(ref.ch["brake"]), np.nan_to_num(ref.ch["throttle"])
    out: list[dict] = []
    for c in corners:
        m = driving_metrics(ref, c)
        b = m.base
        if b.brake_start_m is not None and b.brake_release_m is not None and b.brake_release_m - b.brake_start_m >= min_brake_m:
            out.append({"type": "brake", "corner": c.id, "from_m": b.brake_start_m, "to_m": b.brake_release_m,
                        "peak": _r(b.brake_peak), "peak_m": _r(m.brake_peak_m)})
            end = _r(b.brake_release_m + max(10.0, m.release_span_m or 0.0))
            out.append({"type": "release", "corner": c.id, "from_m": _r(b.brake_release_m - (m.release_span_m or 0.0)), "to_m": end})
        if m.throttle_on_m is not None:
            out.append({"type": "accel", "corner": c.id, "from_m": _r(m.throttle_on_m), "to_m": _r(max(c.exit_m, b.throttle_pickup_m or c.exit_m))})
    return out
