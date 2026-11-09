"""Corner detection from a reference lap (provisional numbering) and user-editable track profiles."""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
from scipy.signal import find_peaks

from .align import AlignedLap


@dataclass
class Corner:
    id: str                 # "P1".. when provisional; user-assigned names when mapped
    apex_m: float
    entry_m: float          # brake application / start of zone
    exit_m: float           # end of zone (speed regained)
    min_speed_kmh: float
    provisional: bool = True
    name: str | None = None

    def to_json(self) -> dict:
        return asdict(self)


def detect_corners(ref: AlignedLap, prominence_kmh: float = 15.0, min_sep_m: float = 120.0,
                   brake_thr: float = 0.10) -> list[Corner]:
    """Local speed minima. NUMBERS ARE PROVISIONAL (P1, P2, ...): real turn numbers are never invented."""
    v = ref.ch["speed_kmh"].copy()
    ok = np.isfinite(v)
    if ok.sum() < 10:
        return []
    v[~ok] = np.nanmax(v)
    step = float(ref.grid[1] - ref.grid[0])
    peaks, _ = find_peaks(-v, prominence=prominence_kmh, distance=max(1, int(min_sep_m / step)))
    br = np.nan_to_num(ref.ch.get("brake", np.zeros_like(v)))
    out: list[Corner] = []
    look_back, look_fwd = int(300 / step), int(400 / step)
    for n, p in enumerate(peaks, 1):
        # entry: start of the contiguous braking block that ends at/before the apex; if the car did not
        # brake, the point of local maximum speed in the 300 m before the apex.
        i = p
        while i > 0 and br[i] <= brake_thr and p - i < look_back:      # skip lift/coast right before apex
            i -= 1
        if br[i] > brake_thr:
            while i > 0 and br[i - 1] > brake_thr:
                i -= 1
            entry = i
        else:
            lo = max(0, p - look_back)
            entry = lo + int(np.argmax(v[lo:p + 1]))
        # exit: speed recovered to halfway between apex speed and the max speed in the next 400 m
        hi = min(len(v), p + look_fwd)
        target = v[p] + 0.5 * (float(v[p:hi].max()) - float(v[p]))
        j = p
        while j < hi - 1 and v[j] < target:
            j += 1
        out.append(Corner(f"P{n}", float(ref.grid[p]), float(ref.grid[entry]), float(ref.grid[j]), float(v[p])))
    return out


def apply_profile(detected: list[Corner], profile: list[dict] | None) -> list[Corner]:
    """Saved profile (manual editor) overrides detection; otherwise provisional segments are kept."""
    if not profile:
        return detected
    return [Corner(id=p["id"], apex_m=p["apex_m"], entry_m=p["entry_m"], exit_m=p["exit_m"],
                   min_speed_kmh=p.get("min_speed_kmh", float("nan")), provisional=False, name=p.get("name"))
            for p in profile]
