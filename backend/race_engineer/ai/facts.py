"""Fact base: the ONLY material the engineer (rules or LLM) may talk about. Every fact = id + text + numbers + provenance."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

import numpy as np

from ..analysis import driver as drv
from ..analysis.align import align_lap
from ..analysis.compare import compare, consistency, corner_metrics
from ..analysis.corners import apply_profile, detect_corners
from ..analysis.laps import load_session, segment_laps, summarize
from ..analysis.tyrefuel import fuel_report, tyre_report
from ..storage.catalog import Catalog


@dataclass
class Fact:
    id: str
    kind: str
    text: str                     # human sentence containing the numbers
    values: dict = field(default_factory=dict)
    provenance: str = "computed"

    def to_json(self):
        return asdict(self)


def _fmt(t):
    return "n/d" if t is None else f"{t:.3f} s"


def sector_times(sd, laps):
    out = {}
    c = sd.cols
    if "cur_sector1_s" not in c or "cur_sector2_s" not in c:
        return out
    for l in laps:
        if not (l.valid_for_analysis and l.time_s):
            continue
        s1 = np.nanmax(c["cur_sector1_s"][l.i0:l.i1]) if np.isfinite(c["cur_sector1_s"][l.i0:l.i1]).any() else np.nan
        s12 = np.nanmax(c["cur_sector2_s"][l.i0:l.i1]) if np.isfinite(c["cur_sector2_s"][l.i0:l.i1]).any() else np.nan
        if np.isfinite(s1) and np.isfinite(s12) and s1 > 0 and s12 > s1:
            out[l.number] = (float(s1), float(s12 - s1), float(l.time_s - s12))
    return out


def build_facts(catalog: Catalog, session_id: str) -> tuple[list[Fact], dict]:
    row = catalog.get_session(session_id)
    if row is None:
        raise KeyError("unknown session")
    sd = load_session(row["data_path"], row["track_length_m"] or 0.0)
    laps = segment_laps(sd)
    summ = summarize(laps)
    prov = sd.provenance
    F: list[Fact] = []
    meta = {"session": row, "n_valid": summ["laps_valid"], "provenance": prov, "corners_provisional": True, "alignment_ok": True}
    F.append(Fact("S1", "session", f"Sessione {row['session_type']} a {row['track']} con {row['vehicle']}: {summ['laps_total']} giri, {summ['laps_valid']} validi.",
                  {"laps_total": summ["laps_total"], "laps_valid": summ["laps_valid"]}, prov))
    if summ["best_time_s"] is not None:
        F.append(Fact("S2", "session", f"Giro migliore: giro {summ['best_lap']} in {summ['best_time_s']:.3f} s; media giri validi {summ['mean_time_s']:.3f} s"
                      + (f"; deviazione standard {summ['std_time_s']:.3f} s." if summ["std_time_s"] is not None else "."),
                      {"best_lap": summ["best_lap"], "best_time_s": summ["best_time_s"], "mean_time_s": summ["mean_time_s"], "std_time_s": summ["std_time_s"]}, prov))
    for l in laps:
        if l.valid_for_analysis and l.time_s:
            F.append(Fact(f"L{l.number}", "lap", f"Giro {l.number}: {l.time_s:.3f} s ({l.time_source}).", {"lap": l.number, "time_s": l.time_s}, "direct" if l.time_source == "game_last_lap_time" else "computed"))
        else:
            F.append(Fact(f"L{l.number}", "lap", f"Giro {l.number} non valido per l'analisi: stato {l.status} ({', '.join(l.reasons) or 'n/d'}).", {"lap": l.number}, "computed"))
    # sectors
    st = sector_times(sd, laps)
    if st:
        for i in range(3):
            best_lap = min(st, key=lambda n: st[n][i])
            F.append(Fact(f"SEC{i + 1}", "sector", f"Miglior settore {i + 1}: {st[best_lap][i]:.3f} s (giro {best_lap}).", {"sector": i + 1, "time_s": st[best_lap][i], "lap": best_lap}, "computed"))
    ok = [l for l in laps if l.valid_for_analysis and l.time_s]
    if len(ok) >= 4:
        sl = float(np.polyfit([l.number for l in ok], [l.time_s for l in ok], 1)[0])
        F.append(Fact("PACE", "pace", f"Tendenza del tempo giro sui giri validi: {sl:+.3f} s per giro (n={len(ok)}).", {"slope_s_per_lap": sl, "n": len(ok)}, "computed"))
    meta["laps"] = {l.number: l.time_s for l in ok}
    if len(ok) >= 2:
        best = min(ok, key=lambda l: l.time_s)
        al = {l.number: align_lap(sd, l) for l in ok}
        meta["alignment_ok"] = all(a.quality["ok"] for a in al.values())
        if meta["alignment_ok"]:
            ref = al[best.number]
            prof = catalog.get_track_profile(row["track"] or "")
            cs = apply_profile(detect_corners(ref), prof)
            meta["corners_provisional"] = prof is None
            for c in cs:
                m = corner_metrics(ref, c)
                F.append(Fact(f"C{c.id}", "corner", f"Curva {c.name or c.id} (giro migliore {best.number}): apice a {c.apex_m:.0f} m, velocità minima {m.min_speed_kmh:.0f} km/h"
                              + (f", frenata da {m.brake_start_m:.0f} m" if m.brake_start_m is not None else ", senza frenata rilevata")
                              + (f", gas pieno da {m.throttle_pickup_m:.0f} m." if m.throttle_pickup_m is not None else "."),
                              {"apex_m": c.apex_m, "min_speed_kmh": m.min_speed_kmh, "brake_start_m": m.brake_start_m, "throttle_pickup_m": m.throttle_pickup_m}, "computed"))
            loss: dict = {}
            for n, a in al.items():
                if n == best.number:
                    continue
                res = compare(a, ref, cs)
                F.append(Fact(f"D{n}", "lap_delta", f"Giro {n} vs giro migliore {best.number}: delta totale {res['total_delta_s']:+.3f} s.", {"lap": n, "ref_lap": best.number, "total_delta_s": res["total_delta_s"]}, "computed"))
                for i, f in enumerate(res["findings"]):
                    ev = ", ".join(f"{k}={v}" for k, v in f["evidence"].items())
                    imp = f["time_impact_s"]
                    F.append(Fact(f"F{n}.{f['corner']}.{f['type']}", "finding",
                                  f"Giro {n}, curva {f['corner']}: {f['type']} ({ev})" + (f"; variazione del tempo di zona {imp:+.3f} s." if imp is not None else "."),
                                  {"lap": n, "corner": f["corner"], "type": f["type"], "time_impact_s": imp, **f["evidence"]}, "computed"))
                for r in res["corners"]:
                    z = r["lap"]["zone_time_delta_s"]
                    if z is not None:
                        loss.setdefault(r["corner"], []).append(z)
            for c in cs:
                if loss.get(c.id):
                    F.append(Fact(f"LOSS.{c.id}", "corner_loss", f"Curva {c.name or c.id}: variazione media del tempo di zona vs giro migliore {np.mean(loss[c.id]):+.3f} s su {len(loss[c.id])} giri.",
                                  {"corner": c.id, "mean_zone_delta_s": float(np.mean(loss[c.id])), "n": len(loss[c.id])}, "computed"))
            if len(ok) >= 3:
                for c in consistency(list(al.values()), cs):
                    F.append(Fact(f"K.{c['corner']}", "consistency", f"Curva {c['corner']}: variabilità su {c['laps']} giri — velocità minima ±{c['min_speed_std_kmh']} km/h, punto di frenata ±{c['brake_start_std_m']} m, gas ±{c['throttle_pickup_std_m']} m.",
                                  {k: v for k, v in c.items() if k != "corner"} | {"corner": c["corner"]}, "computed"))
    fr = fuel_report(sd, laps)
    if fr.get("mean_l_per_lap"):
        F.append(Fact("FUEL", "fuel", f"Consumo medio {fr['mean_l_per_lap']:.3f} L/giro su {fr['n']} giri puliti; carburante residuo {fr['current_fuel_l']:.1f} L, circa {fr['laps_remaining']:.1f} giri.",
                      {"mean_l_per_lap": fr["mean_l_per_lap"], "n": fr["n"], "current_fuel_l": fr["current_fuel_l"], "laps_remaining": fr["laps_remaining"]}, "computed"))
    tr = tyre_report(sd, laps)
    if tr.get("available") and tr["trends"].get("fl.wear_end"):
        t = tr["trends"]["fl.wear_end"]
        F.append(Fact("TYRE", "tyre", f"Usura anteriore sinistra: {t['slope_per_lap']:+.4f} (frazione) per giro su {t['n']} giri.", {"slope_per_lap": t["slope_per_lap"], "n": t["n"]}, "computed"))
    # data availability
    miss = [c for c in ("speed_kmh", "throttle", "brake", "steering", "lap_dist_m", "fuel_l") if c not in sd.cols or not np.isfinite(sd.cols[c]).any()]
    meta["missing_channels"] = miss
    if miss:
        F.append(Fact("MISS", "missing", "Canali non disponibili in questa sessione: " + ", ".join(miss) + ".", {}, "unavailable"))
    # history
    h = drv.history(catalog, include_synthetic=bool(row["is_synthetic"]), period="week")
    g = next((x for x in h["groups"] if x["track"] == row["track"] and x["vehicle"] == row["vehicle"]), None)
    if g and len(g["series"]) >= 2:
        a, b = g["series"][-2], g["series"][-1]
        F.append(Fact("HIST", "history", f"Miglior giro settimana {b['period']}: {b['best_time_s']:.3f} s; settimana precedente {a['period']}: {a['best_time_s']:.3f} s (differenza {b['best_time_s'] - a['best_time_s']:+.3f} s).",
                      {"best_now_s": b["best_time_s"], "best_prev_s": a["best_time_s"], "diff_s": b["best_time_s"] - a["best_time_s"]}, "computed"))
    return F, meta
