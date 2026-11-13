"""Lap segmentation and validity (Phase 2). Original samples are never modified or deleted."""
from __future__ import annotations

from dataclasses import dataclass, field

import duckdb
import numpy as np

COLS = ["wall_time", "session_time_s", "lap_number", "lap_dist_m", "speed_kmh", "throttle", "brake", "steering",
        "rpm", "gear", "in_pits", "lap_invalidated", "last_lap_time_s", "fuel_l", "pos_x_m", "pos_z_m", "sector",
        "ambient_temp_c", "track_temp_c", "cur_sector1_s", "cur_sector2_s", "provenance"] + [
    f"tyre_{w}_{c}" for w in ("fl", "fr", "rl", "rr")
    for c in ("pressure_kpa", "temp_left_c", "temp_center_c", "temp_right_c", "carcass_temp_c", "wear", "brake_temp_c")]


@dataclass
class SessionData:
    cols: dict[str, np.ndarray]
    track_length_m: float
    provenance: str

    def __len__(self) -> int:
        return len(self.cols["session_time_s"])


def load_session(path: str, track_length_m: float) -> SessionData:
    con = duckdb.connect(str(path), read_only=True)
    try:
        have = {r[0] for r in con.execute("select column_name from information_schema.columns where table_name='samples'").fetchall()}
        sel = [c for c in COLS if c in have]
        rows = con.execute(f"select {', '.join(sel)} from samples order by session_time_s").fetchall()
    finally:
        con.close()
    cols: dict[str, np.ndarray] = {}
    for i, c in enumerate(sel):
        vals = [r[i] for r in rows]
        if c == "provenance":
            cols[c] = np.array(vals, dtype=object)
        else:
            cols[c] = np.array([np.nan if v is None else float(v) for v in vals])
    prov = ",".join(sorted(set(cols.get("provenance", [])))) if rows else ""
    return SessionData(cols, track_length_m, prov)


def unwrap_lap_distance(dist: np.ndarray, track_length_m: float) -> np.ndarray:
    """The lap counter and the lap distance do not change on the same sample at the start line (seen in real LMU data).
    A few samples at the START of a lap that still carry the previous lap's distance (~track length) are shifted by -L, a few at the
    END that already wrapped are shifted by +L, so the distance is monotonic across the line. Jumps in the middle of a lap are left alone."""
    d = np.array(dist, dtype=float)
    L = float(track_length_m or 0.0)
    if L <= 0 or len(d) < 3:
        return d
    edge = max(20, len(d) // 50)
    jumps = np.flatnonzero(np.isfinite(d[1:]) & np.isfinite(d[:-1]) & (d[:-1] - d[1:] > L / 2)) + 1      # d[j] is far below d[j-1]
    if len(jumps) and jumps[0] <= edge:
        d[:jumps[0]] -= L
    if len(jumps) and len(d) - jumps[-1] <= edge and (len(jumps) > 1 or jumps[0] > edge):
        d[jumps[-1]:] += L
    return d


TIME_GAP_LIMIT_S = 0.5            # a hole in the samples longer than this makes the lap unusable (shorter ones are only noted: distance-based alignment covers them)
GAME_TIME_TOLERANCE_S = 0.5       # the game's published lap time must agree with the clock to this much, otherwise the clock wins


@dataclass
class Lap:
    number: int
    i0: int
    i1: int                      # exclusive
    time_s: float | None
    time_source: str             # 'game_last_lap_time' (direct) | 'computed_from_session_time' | 'none'
    status: str                  # complete | incomplete | invalid
    reasons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)       # things worth knowing that do NOT make the lap unusable
    coverage: float = 0.0
    max_gap_m: float = 0.0
    valid_for_analysis: bool = False

    def to_json(self) -> dict:
        return {"number": self.number, "samples": self.i1 - self.i0, "time_s": self.time_s, "time_source": self.time_source,
                "status": self.status, "reasons": self.reasons, "notes": self.notes, "coverage": round(self.coverage, 4),
                "max_gap_m": round(self.max_gap_m, 1), "valid_for_analysis": self.valid_for_analysis}


def segment_laps(d: SessionData, min_coverage: float = 0.98, max_gap_m: float = 50.0,
                 max_time_gap_factor: float = 5.0, time_gap_limit_s: float = TIME_GAP_LIMIT_S) -> list[Lap]:
    c, L = d.cols, d.track_length_m
    n = len(d)
    if n == 0:
        return []
    ln = c["lap_number"]
    bounds = [0] + [i for i in range(1, n) if ln[i] != ln[i - 1]] + [n]
    t = c["session_time_s"]
    med_dt = float(np.median(np.diff(t))) if n > 2 else 0.0
    laps: list[Lap] = []
    for k in range(len(bounds) - 1):
        i0, i1 = bounds[k], bounds[k + 1]
        lap = Lap(int(ln[i0]), i0, i1, None, "none", "incomplete")
        dist = unwrap_lap_distance(c["lap_dist_m"][i0:i1], L)
        closed = (k + 1) < (len(bounds) - 1)
        reasons = lap.reasons
        if len(dist) >= 2 and np.isfinite(dist).all():
            span = float(min(np.nanmax(dist), L) - max(np.nanmin(dist), 0.0))
            lap.coverage = span / L if L else 0.0
            gaps = np.diff(dist)
            gaps = gaps[(gaps > -L / 2)]                       # ignore the wrap at the line
            lap.max_gap_m = float(np.max(gaps)) if len(gaps) else 0.0
            started_at_line = float(dist[0]) < max(30.0, 0.02 * L) or float(dist[0]) > L - max(30.0, 0.02 * L)
        else:
            started_at_line = False
        if not started_at_line:
            reasons.append("does_not_start_at_line")
        if lap.coverage < min_coverage:
            reasons.append(f"coverage_{lap.coverage:.2f}")
        if lap.max_gap_m > max_gap_m:
            reasons.append(f"distance_gap_{lap.max_gap_m:.0f}m")
        tt = np.diff(t[i0:i1])
        if med_dt > 0 and len(tt) and float(tt.max()) > max_time_gap_factor * med_dt:
            (reasons if float(tt.max()) > time_gap_limit_s else lap.notes).append(f"time_gap_{float(tt.max()):.2f}s")
        if not closed:
            reasons.append("lap_not_closed")
        # lap time: game's value (direct) is published as last_lap_time in the NEXT lap's samples
        if closed:
            nxt = c["last_lap_time_s"][bounds[k + 1]:bounds[k + 2]] if "last_lap_time_s" in c else np.array([])
            nxt = nxt[np.isfinite(nxt) & (nxt > 0)]
            clock = float(t[bounds[k + 1]] - t[i0])
            # the game keeps this lap's time constant for the WHOLE next lap but publishes it a moment late: the first samples of the
            # next lap can still carry the previous lap's value (real data: two laps with the identical time). Take the settled value.
            game = float(np.median(nxt)) if len(nxt) else None
            if game is not None and abs(game - clock) <= GAME_TIME_TOLERANCE_S:
                lap.time_s, lap.time_source = game, "game_last_lap_time"
            else:
                lap.time_s, lap.time_source = clock, "computed_from_session_time"
                if game is not None:
                    lap.notes.append(f"game_time_mismatch_{game:.3f}s_clock_{clock:.3f}s")
        invalid = "lap_invalidated" in c and bool(np.nansum(c["lap_invalidated"][i0:i1]) > 0)   # all-NaN = unknown, not invalid
        pit = "in_pits" in c and bool(np.nansum(c["in_pits"][i0:i1]) > 0)
        if invalid:
            lap.status = "invalid"; reasons.append("invalidated_by_game")
        elif not reasons:
            lap.status = "complete"
        if pit:
            reasons.append("pit_lane")
        lap.valid_for_analysis = lap.status == "complete" and not pit
        laps.append(lap)
    return laps


def summarize(laps: list[Lap]) -> dict:
    ok = [l for l in laps if l.valid_for_analysis and l.time_s]
    times = [l.time_s for l in ok]
    return {"laps_total": len(laps), "laps_valid": len(ok),
            "best_lap": min(ok, key=lambda l: l.time_s).number if ok else None,
            "best_time_s": min(times) if times else None, "mean_time_s": float(np.mean(times)) if times else None,
            "std_time_s": float(np.std(times)) if len(times) > 1 else None,
            "note": "means/std use only complete, valid, non-pit laps"}
