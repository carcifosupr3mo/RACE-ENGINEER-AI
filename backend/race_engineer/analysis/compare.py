"""Per-corner metrics, lap-vs-reference comparison and numerically-evidenced findings."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

import numpy as np

from .align import AlignedLap, delta_time
from .corners import Corner

BRAKE_THR = 0.10
THROTTLE_PICKUP = 0.90


@dataclass
class CornerMetrics:
    corner: str
    brake_start_m: float | None
    brake_release_m: float | None
    brake_peak: float | None
    min_speed_kmh: float | None
    min_speed_m: float | None
    throttle_pickup_m: float | None
    exit_speed_kmh: float | None
    coast_time_s: float | None
    zone_time_delta_s: float | None   # change of delta-to-reference across the corner zone (None for the reference itself)

    def to_json(self) -> dict:
        return {k: (None if v is None or (isinstance(v, float) and not np.isfinite(v)) else round(float(v), 3) if isinstance(v, float) else v)
                for k, v in asdict(self).items()}


def _first(mask: np.ndarray, grid: np.ndarray):
    idx = np.flatnonzero(mask)
    return float(grid[idx[0]]) if len(idx) else None


def corner_metrics(lap: AlignedLap, c: Corner, ref: AlignedLap | None = None, ref_corner: Corner | None = None) -> CornerMetrics:
    g = lap.grid
    v, th, br = lap.ch["speed_kmh"], lap.ch["throttle"], lap.ch["brake"]
    lo = max(0.0, c.entry_m - 120.0)
    zone = (g >= lo) & (g <= c.exit_m)
    pre = (g >= lo) & (g <= c.apex_m)
    # brake block that reaches the apex region: first brake sample in window, last brake sample before apex
    bidx = np.flatnonzero(pre & (np.nan_to_num(br) > BRAKE_THR))
    bstart = float(g[bidx[0]]) if len(bidx) else None
    brel = float(g[bidx[-1]]) if len(bidx) else None
    bpeak = float(np.nanmax(br[pre])) if len(bidx) else 0.0
    win = (g >= c.apex_m - 40) & (g <= c.apex_m + 40)
    if not np.isfinite(v[win]).any():
        return CornerMetrics(c.id, bstart, brel, bpeak, None, None, None, None, None, None)
    k = int(np.nanargmin(np.where(win, v, np.nan)))
    after = (g > g[k]) & (g <= c.exit_m + 150)
    pick = _first(after & (np.nan_to_num(th) >= THROTTLE_PICKUP), g)
    exit_idx = int(np.argmin(np.abs(g - c.exit_m)))
    coast = zone & (np.nan_to_num(th, nan=1) < 0.05) & (np.nan_to_num(br, nan=1) < 0.05)
    dt = np.gradient(lap.t)
    coast_t = float(np.nansum(dt[coast]))
    zt = None
    if ref is not None:
        d = delta_time(lap, ref)
        i0, i1 = int(np.argmin(np.abs(g - lo))), exit_idx
        zt = float(d[i1] - d[i0]) if np.isfinite(d[i0]) and np.isfinite(d[i1]) else None
    return CornerMetrics(c.id, bstart, brel, bpeak, float(v[k]), float(g[k]), pick, float(v[exit_idx]), coast_t, zt)


@dataclass
class Finding:
    type: str
    corner: str
    lap: int
    ref_lap: int
    evidence: dict
    time_impact_s: float | None
    provenance: str = "computed"
    note: str = "Measured difference vs the reference lap; the zone time change is attributed by location and is not proof of cause."

    def to_json(self) -> dict:
        return asdict(self)


@dataclass
class Thresholds:
    brake_point_m: float = 15.0
    min_speed_kmh: float = 2.0
    exit_speed_kmh: float = 3.0
    throttle_pickup_m: float = 15.0
    brake_peak: float = 0.15
    release_m: float = 15.0


def compare(lap: AlignedLap, ref: AlignedLap, corners: list[Corner], th: Thresholds = Thresholds()):
    rows, findings = [], []
    for c in corners:
        m = corner_metrics(lap, c, ref)
        r = corner_metrics(ref, c)
        rows.append({"corner": c.id, "lap": m.to_json(), "ref": r.to_json()})
        imp = m.zone_time_delta_s

        def add(t, **ev):
            findings.append(Finding(t, c.id, lap.number, ref.number, {k: round(float(x), 2) for k, x in ev.items()}, imp))
        if m.brake_start_m is not None and r.brake_start_m is not None:
            d = m.brake_start_m - r.brake_start_m
            if d <= -th.brake_point_m:
                add("early_braking", lap_brake_m=m.brake_start_m, ref_brake_m=r.brake_start_m, diff_m=d)
            elif d >= th.brake_point_m:
                add("late_braking", lap_brake_m=m.brake_start_m, ref_brake_m=r.brake_start_m, diff_m=d)
            if (m.brake_release_m is not None and r.brake_release_m is not None
                    and m.brake_release_m - r.brake_release_m <= -th.release_m):
                add("early_brake_release", lap_release_m=m.brake_release_m, ref_release_m=r.brake_release_m)
        if m.brake_peak is not None and r.brake_peak is not None and m.brake_peak - r.brake_peak >= th.brake_peak:
            add("brake_peak_higher", lap_peak=m.brake_peak, ref_peak=r.brake_peak)
        if m.min_speed_kmh is not None and r.min_speed_kmh is not None and r.min_speed_kmh - m.min_speed_kmh >= th.min_speed_kmh:
            add("low_min_speed", lap_kmh=m.min_speed_kmh, ref_kmh=r.min_speed_kmh, diff_kmh=m.min_speed_kmh - r.min_speed_kmh)
        if m.throttle_pickup_m is not None and r.throttle_pickup_m is not None and m.throttle_pickup_m - r.throttle_pickup_m >= th.throttle_pickup_m:
            add("late_throttle", lap_pickup_m=m.throttle_pickup_m, ref_pickup_m=r.throttle_pickup_m,
                diff_m=m.throttle_pickup_m - r.throttle_pickup_m)
        if m.exit_speed_kmh is not None and r.exit_speed_kmh is not None and r.exit_speed_kmh - m.exit_speed_kmh >= th.exit_speed_kmh:
            add("slow_exit", lap_kmh=m.exit_speed_kmh, ref_kmh=r.exit_speed_kmh, diff_kmh=m.exit_speed_kmh - r.exit_speed_kmh)
    findings.sort(key=lambda f: -(f.time_impact_s or 0))
    d = delta_time(lap, ref)
    return {"lap": lap.number, "ref_lap": ref.number, "total_delta_s": float(d[np.isfinite(d)][-1]) if np.isfinite(d).any() else None,
            "corners": rows, "findings": [f.to_json() for f in findings]}


def consistency(laps: list[AlignedLap], corners: list[Corner]) -> list[dict]:
    """Std-dev across laps of key per-corner metrics (needs >= 3 laps)."""
    out = []
    for c in corners:
        ms = [corner_metrics(l, c) for l in laps]
        def sd(attr):
            xs = [getattr(m, attr) for m in ms if getattr(m, attr) is not None]
            return round(float(np.std(xs)), 3) if len(xs) >= 3 else None
        out.append({"corner": c.id, "laps": len(ms), "min_speed_std_kmh": sd("min_speed_kmh"),
                    "brake_start_std_m": sd("brake_start_m"), "throttle_pickup_std_m": sd("throttle_pickup_m")})
    return out
