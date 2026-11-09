"""Tyre & fuel engineering (Phase 6). Uses only valid laps; every aggregate declares n and exclusions."""
from __future__ import annotations

import numpy as np

from .laps import Lap, SessionData

WHEELS = ("fl", "fr", "rl", "rr")


def _col(d: SessionData, name: str):
    return d.cols.get(name)


def fuel_report(d: SessionData, laps: list[Lap], target_laps: int | None = None, margin_laps: float = 0.5) -> dict:
    """Fuel per lap from the fuel level at the start of consecutive laps.

    A lap is used only if: valid_for_analysis, a following lap exists, fuel samples are finite at both
    boundaries and the level never rises inside the lap (refuel => excluded and reported).
    """
    fuel = _col(d, "fuel_l")
    if fuel is None or not np.isfinite(fuel).any():
        return {"available": False, "reason": "fuel_l channel not available"}
    per, excluded = [], []
    by_no = {l.number: l for l in laps}
    for l in laps:
        nxt = by_no.get(l.number + 1)
        if not l.valid_for_analysis:
            excluded.append({"lap": l.number, "reason": ",".join(l.reasons) or l.status}); continue
        if nxt is None:
            excluded.append({"lap": l.number, "reason": "no following lap boundary"}); continue
        seg = fuel[l.i0:l.i1]
        a, b = fuel[l.i0], fuel[nxt.i0]
        if not (np.isfinite(a) and np.isfinite(b)) or np.isnan(seg).any():
            excluded.append({"lap": l.number, "reason": "fuel samples missing"}); continue
        if np.any(np.diff(seg) > 0.05) or b > a:
            excluded.append({"lap": l.number, "reason": "fuel level increased (refuel)"}); continue
        per.append({"lap": l.number, "fuel_used_l": round(float(a - b), 4), "provenance": "computed"})
    cur = fuel[np.isfinite(fuel)][-1]
    out = {"available": True, "current_fuel_l": round(float(cur), 3), "laps_used": [p["lap"] for p in per], "per_lap": per,
           "excluded": excluded, "provenance": d.provenance}
    if len(per) >= 2:
        xs = np.array([p["fuel_used_l"] for p in per])
        mean = float(xs.mean())
        out.update({"mean_l_per_lap": round(mean, 4), "std_l_per_lap": round(float(xs.std()), 4), "n": len(xs),
                    "laps_remaining": round(float(cur) / mean, 2) if mean > 0 else None})
        if target_laps:
            need = target_laps * mean
            out["plan"] = {"target_laps": target_laps, "fuel_needed_l": round(need, 2),
                           "safety_margin_laps": margin_laps, "safety_margin_provenance": "manual",
                           "fuel_with_margin_l": round(need + margin_laps * mean, 2),
                           "to_add_l": round(max(0.0, need + margin_laps * mean - float(cur)), 2)}
    else:
        out["note"] = f"need >= 2 clean laps for an average (have {len(per)}); no estimate given"
    return out


def tyre_report(d: SessionData, laps: list[Lap]) -> dict:
    ok = [l for l in laps if l.valid_for_analysis]
    if not ok or f"tyre_fl_pressure_kpa" not in d.cols:
        return {"available": False, "reason": "no valid laps or tyre channels missing"}
    rows, missing = [], set()
    for l in ok:
        row = {"lap": l.number, "wheels": {}}
        for w in WHEELS:
            def m(ch, end=False):
                a = d.cols.get(f"tyre_{w}_{ch}")
                if a is None:
                    missing.add(f"tyre_{w}_{ch}"); return None
                seg = a[l.i0:l.i1]
                seg = seg[np.isfinite(seg)]
                if not len(seg):
                    missing.add(f"tyre_{w}_{ch}"); return None
                return float(seg[-1] if end else seg.mean())
            tl, tc, tr = m("temp_left_c"), m("temp_center_c"), m("temp_right_c")
            row["wheels"][w] = {"pressure_kpa": m("pressure_kpa"), "temp_left_c": tl, "temp_center_c": tc, "temp_right_c": tr,
                                "carcass_c": m("carcass_temp_c"), "wear_end": m("wear", end=True), "brake_temp_c": m("brake_temp_c")}
        rows.append(row)
    def series(w, k): return [r["wheels"][w][k] for r in rows]
    trends = {}
    for w in WHEELS:
        for k in ("wear_end", "pressure_kpa", "temp_center_c"):
            ys = series(w, k)
            if len(ys) >= 3 and all(y is not None for y in ys):
                slope = float(np.polyfit([r["lap"] for r in rows], ys, 1)[0])
                trends[f"{w}.{k}"] = {"slope_per_lap": round(slope, 5), "n": len(ys)}
    last = rows[-1]["wheels"]
    def diff(a, b, k):
        x, y = last[a][k], last[b][k]
        return None if x is None or y is None else round(x - y, 2)
    return {"available": True, "laps_used": [r["lap"] for r in rows], "per_lap": rows,
            "differences_last_lap": {"pressure_fl_minus_fr_kpa": diff("fl", "fr", "pressure_kpa"), "pressure_rl_minus_rr_kpa": diff("rl", "rr", "pressure_kpa"),
                                     "temp_center_fl_minus_fr_c": diff("fl", "fr", "temp_center_c"), "temp_center_rl_minus_rr_c": diff("rl", "rr", "temp_center_c"),
                                     "pressure_front_minus_rear_kpa": None if None in (last["fl"]["pressure_kpa"], last["rl"]["pressure_kpa"]) else round(last["fl"]["pressure_kpa"] - last["rl"]["pressure_kpa"], 2)},
            "trends": trends, "missing_channels": sorted(missing), "provenance": d.provenance,
            "note": "Temperatures are left/centre/right of each tyre (LMU), not inner/outer. Correlation with car behaviour is NOT claimed."}
