"""Distance-based lap alignment with data-quality checks (never timestamp-to-timestamp)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .laps import Lap, SessionData

CHANNELS = ["speed_kmh", "throttle", "brake", "steering", "rpm", "gear", "pos_x_m", "pos_z_m"]


@dataclass
class AlignedLap:
    number: int
    grid: np.ndarray               # metres
    t: np.ndarray                  # elapsed time at each grid point (s, from lap start)
    ch: dict[str, np.ndarray]
    quality: dict


def align_lap(d: SessionData, lap: Lap, step_m: float = 1.0, max_gap_m: float = 50.0) -> AlignedLap:
    c, L = d.cols, d.track_length_m
    sl = slice(lap.i0, lap.i1)
    dist = c["lap_dist_m"][sl].copy()
    tm = c["session_time_s"][sl] - c["session_time_s"][lap.i0]
    # enforce monotonic distance: drop samples that go backwards (jitter / wrap at the line)
    keep = np.ones(len(dist), bool)
    run = -np.inf
    for i, v in enumerate(dist):
        if not np.isfinite(v) or v < run - 1e-9:
            keep[i] = False
        else:
            run = v
    dist, tm = dist[keep], tm[keep]
    dist, uniq = np.unique(dist, return_index=True)
    tm = tm[uniq]
    grid = np.arange(0.0, L, step_m)
    inside = (grid >= dist[0]) & (grid <= dist[-1])
    t = np.full(len(grid), np.nan)
    t[inside] = np.interp(grid[inside], dist, tm)
    ch: dict[str, np.ndarray] = {}
    for name in CHANNELS:
        if name not in c:
            continue
        v = c[name][sl][keep][uniq]
        out = np.full(len(grid), np.nan)
        good = np.isfinite(v)
        if good.sum() >= 2:
            if name == "gear":   # stepwise: no interpolation between gears
                idx = np.searchsorted(dist[good], grid[inside], side="right") - 1
                out[inside] = v[good][np.clip(idx, 0, good.sum() - 1)]
            else:
                out[inside] = np.interp(grid[inside], dist[good], v[good])
        ch[name] = out
    gaps = np.diff(dist)
    q = {"coverage": float(inside.mean()), "dropped_backwards": int((~keep).sum()),
         "max_gap_m": float(gaps.max()) if len(gaps) else None,
         "ok": bool(inside.mean() >= 0.97 and (gaps.max() if len(gaps) else 1e9) <= max_gap_m)}
    return AlignedLap(lap.number, grid, t, ch, q)


def delta_time(lap: AlignedLap, ref: AlignedLap) -> np.ndarray:
    """Positive = `lap` is slower than `ref` at that distance (seconds)."""
    return lap.t - ref.t
