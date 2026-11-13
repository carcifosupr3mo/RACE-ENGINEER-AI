"""Session report: where time is won and lost over ALL valid laps (ideal lap, per-zone potential, consistency).

The track is cut into zones from the reference lap's corners (corner entry..exit) and the straights between them. Every valid lap
gets a time per zone (from the distance-aligned elapsed time, never timestamp-to-timestamp). Then:
* ideal lap = sum of the best time of each zone over all laps (a theoretical target, not a promise: zones are not independent);
* a zone's potential = what the BEST lap still leaves there (its time minus the best time ever done in that zone);
* a zone's consistency loss = median zone time minus best zone time (what you give away on a normal lap).
"""
from __future__ import annotations

import numpy as np

from .align import AlignedLap
from .corners import Corner


def build_zones(corners: list[Corner], track_length_m: float, min_len_m: float = 30.0) -> list[dict]:
    """Corner zones + the straights between them, covering 0..L without overlaps."""
    zones: list[dict] = []
    pos = 0.0
    for c in sorted(corners, key=lambda c: c.entry_m):
        a, b = max(c.entry_m, pos), min(c.exit_m, track_length_m)
        if b - a < min_len_m:
            continue
        if a - pos >= min_len_m:
            zones.append({"id": f"S{len(zones) + 1}", "kind": "straight", "label": f"Rettilineo prima di {c.name or c.id}", "start_m": pos, "end_m": a})
        elif zones and a > pos:
            a = pos                      # tiny gap: glue to the corner
        zones.append({"id": c.id, "kind": "corner", "label": c.name or c.id, "start_m": a, "end_m": b, "apex_m": c.apex_m})
        pos = b
    if track_length_m - pos >= min_len_m:
        zones.append({"id": f"S{len(zones) + 1}", "kind": "straight",
                      "label": "Rettilineo finale" if corners else "Giro intero", "start_m": pos, "end_m": track_length_m})
    elif zones:
        zones[-1]["end_m"] = track_length_m
    if not zones:
        zones.append({"id": "S1", "kind": "straight", "label": "Giro intero", "start_m": 0.0, "end_m": track_length_m})
    return zones


def _zone_time(al: AlignedLap, z: dict) -> float | None:
    g = al.grid
    i0 = int(np.searchsorted(g, z["start_m"]))
    i1 = min(len(g) - 1, int(np.searchsorted(g, z["end_m"])) - 1) if z["end_m"] < g[-1] else len(g) - 1
    if i1 <= i0:
        return None
    a, b = al.t[i0], al.t[i1]
    if i0 == 0 and not np.isfinite(a):
        a = 0.0                          # t is the time since the lap started: the line itself is time zero
    return float(b - a) if np.isfinite(a) and np.isfinite(b) and b > a else None


def _s(x: float, d: int = 3) -> str:
    return f"{x:.{d}f}".replace(".", ",")


def build_report(aligned: dict[int, AlignedLap], lap_times: dict[int, float], corners: list[Corner], track_length_m: float,
                 provisional: bool) -> dict:
    nums = sorted(aligned)
    zones = build_zones(corners, track_length_m)
    zt = {n: [_zone_time(aligned[n], z) for z in zones] for n in nums}
    best_lap = min(nums, key=lambda n: lap_times[n]) if nums else None
    out_zones: list[dict] = []
    for k, z in enumerate(zones):
        vals = [(zt[n][k], n) for n in nums if zt[n][k] is not None]
        if not vals:
            continue
        tb, nb = min(vals)
        arr = np.array([v for v, _ in vals])
        med = float(np.median(arr))
        mine = zt[best_lap][k] if best_lap in zt else None
        out_zones.append({**z, "index": k, "best_s": round(tb, 3), "best_lap": nb, "median_s": round(med, 3),
                          "std_s": round(float(arr.std()), 3) if len(arr) > 1 else None,
                          "best_lap_s": round(mine, 3) if mine is not None else None,
                          "potential_s": round(max(0.0, (mine - tb)) if mine is not None else 0.0, 3),
                          "mean_s": round(float(arr.mean()), 3), "consistency_loss_s": round(max(0.0, float(arr.mean()) - tb), 3), "laps": len(vals)})
    idx = {z["index"]: z for z in out_zones}
    laps_out = []
    for n in nums:
        row = {"number": n, "time_s": round(lap_times[n], 3), "delta_best_s": round(lap_times[n] - lap_times[best_lap], 3), "is_best": n == best_lap,
               "zones": [None if zt[n][z["index"]] is None else round(zt[n][z["index"]] - z["best_s"], 3) for z in out_zones]}
        laps_out.append(row)
    best_s = lap_times[best_lap] if best_lap is not None else None
    complete = best_lap is not None          # zones with no usable time on any lap are simply left out (e.g. a lap that stops short of the line)
    gain = None
    ideal = None
    if complete and len(nums) >= 2:
        # anchored on the best lap's real time: its own zones minus the best zones ever done (same clock for both sides)
        gain = round(sum(z["potential_s"] for z in out_zones), 3)
        ideal = round(best_s - gain, 3)
    times = np.array([lap_times[n] for n in nums]) if nums else np.array([])
    cons = None
    if len(times) >= 3:
        cons = {"std_s": round(float(times.std()), 3), "within_0_5s_pct": round(float((times <= times.min() + 0.5).mean() * 100)),
                "spread_s": round(float(times.max() - times.min()), 3)}
    trend = None
    if len(times) >= 4:
        slope = float(np.polyfit(np.arange(len(times)), times, 1)[0])
        trend = {"slope_s_per_lap": round(slope, 3), "label": "stai migliorando" if slope < -0.05 else "stai peggiorando" if slope > 0.05 else "ritmo stabile"}
    # prioritised advice, biggest gain first; only gains that are measurable (>= 0.02 s) and in plain Italian
    adv = []
    for z in out_zones:
        if len(nums) < 2:
            break
        if z["potential_s"] >= 0.02:
            adv.append({"zone": z["label"], "zone_id": z["id"], "kind": "potential", "gain_s": z["potential_s"], "ref_lap": z["best_lap"],
                        "text": f"{z['label']}: nel tuo giro migliore (giro {best_lap}) perdi {_s(z['potential_s'])} s rispetto al tuo miglior passaggio qui "
                                f"(giro {z['best_lap']}). Rivedi come hai guidato quel punto nel giro {z['best_lap']}."})
        elif z["consistency_loss_s"] >= 0.05:
            adv.append({"zone": z["label"], "zone_id": z["id"], "kind": "consistency", "gain_s": z["consistency_loss_s"], "ref_lap": z["best_lap"],
                        "text": f"{z['label']}: sei incostante (in media +{_s(z['consistency_loss_s'])} s rispetto al tuo meglio, giro {z['best_lap']}). "
                                f"Cerca di ripetere ogni volta lo stesso punto di frenata e di gas."})
    adv.sort(key=lambda a: -a["gain_s"])
    return {"zones": out_zones, "laps": laps_out, "best_lap": best_lap, "best_time_s": round(best_s, 3) if best_s is not None else None,
            "ideal_time_s": ideal, "ideal_gain_s": gain,
            "consistency": cons, "trend": trend, "advice": adv[:6], "corners_provisional": provisional,
            "note": "Il giro ideale è la somma dei tuoi migliori tempi di ogni zona: è un obiettivo teorico, le zone non sono indipendenti "
                    "(uscire meglio da una curva cambia la velocità nel rettilineo dopo)."}
