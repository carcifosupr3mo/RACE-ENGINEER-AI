"""Driver development (Phase 7): history, goals, training derived from MEASURED weak points only."""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

import numpy as np

from ..storage.catalog import Catalog
from .align import align_lap
from .compare import compare, consistency
from .corners import detect_corners
from .laps import load_session, segment_laps, summarize

_CACHE: dict = {}
SLOW_CORNER_KMH = 100.0


def session_stats(row: dict) -> dict:
    """Per-session numbers: lap summary + per-corner measured loss/consistency vs the session's own best lap."""
    key = (row["id"], row["samples"])
    if key in _CACHE:
        return _CACHE[key]
    sd = load_session(row["data_path"], row["track_length_m"] or 0.0)
    laps = segment_laps(sd)
    out = {"summary": summarize(laps), "corners": [], "valid_laps": [l.number for l in laps if l.valid_for_analysis]}
    ok = [l for l in laps if l.valid_for_analysis and l.time_s]
    if len(ok) >= 3:
        best = min(ok, key=lambda l: l.time_s)
        al = {l.number: align_lap(sd, l) for l in ok}
        if all(a.quality["ok"] for a in al.values()):
            ref = al[best.number]
            cs = detect_corners(ref)
            cons = {c["corner"]: c for c in consistency(list(al.values()), cs)}
            loss = defaultdict(list)
            findings = defaultdict(lambda: defaultdict(int))
            for n, a in al.items():
                if n == best.number:
                    continue
                res = compare(a, ref, cs)
                for r in res["corners"]:
                    z = r["lap"]["zone_time_delta_s"]
                    if z is not None:
                        loss[r["corner"]].append(z)
                for f in res["findings"]:
                    findings[f["corner"]][f["type"]] += 1
            for c in cs:
                out["corners"].append({"corner": c.id, "provisional": c.provisional, "apex_m": c.apex_m, "min_speed_kmh": c.min_speed_kmh,
                                       "slow": c.min_speed_kmh < SLOW_CORNER_KMH,
                                       "mean_loss_s": round(float(np.mean(loss[c.id])), 4) if loss[c.id] else None,
                                       "n_compared": len(loss[c.id]), "consistency": cons.get(c.id),
                                       "finding_counts": dict(findings[c.id])})
    _CACHE[key] = out
    return out


def history(catalog: Catalog, include_synthetic: bool = False, period: str = "week", sim: str | None = None) -> dict:
    groups: dict = defaultdict(list)
    for row in catalog.list_sessions(include_synthetic, sim=sim):
        if row["status"] == "recording" or not row["samples"]:
            continue
        st = session_stats(row)["summary"]
        if st["best_time_s"] is None:
            continue
        d = dt.datetime.fromtimestamp(row["started_at"])
        pkey = {"day": d.strftime("%Y-%m-%d"), "week": f"{d.isocalendar().year}-W{d.isocalendar().week:02d}", "month": d.strftime("%Y-%m")}[period]
        groups[(row["track"], row["vehicle"])].append({"session": row["id"], "period": pkey, "started_at": row["started_at"], "synthetic": bool(row["is_synthetic"]),
                                                       "best_time_s": st["best_time_s"], "mean_time_s": st["mean_time_s"], "std_time_s": st["std_time_s"], "laps_valid": st["laps_valid"]})
    out = []
    for (track, veh), items in groups.items():
        items.sort(key=lambda x: x["started_at"])
        per: dict = {}
        for it in items:
            p = per.setdefault(it["period"], {"period": it["period"], "sessions": 0, "best_time_s": None, "std_values": []})
            p["sessions"] += 1
            p["best_time_s"] = it["best_time_s"] if p["best_time_s"] is None else min(p["best_time_s"], it["best_time_s"])
            if it["std_time_s"] is not None:
                p["std_values"].append(it["std_time_s"])
        series = [{"period": p["period"], "sessions": p["sessions"], "best_time_s": p["best_time_s"],
                   "mean_std_s": round(float(np.mean(p["std_values"])), 4) if p["std_values"] else None} for p in per.values()]
        out.append({"track": track, "vehicle": veh, "sessions": items, "series": series})
    return {"period": period, "groups": out, "include_synthetic": include_synthetic}


def evaluate_goal(catalog: Catalog, g: dict) -> dict:
    rows = [r for r in catalog.list_sessions(True, sim=g.get("sim")) if r["track"] == g["track"] and (not g["vehicle"] or r["vehicle"] == g["vehicle"])
            and r["status"] != "recording" and r["started_at"] >= g["created_at"] - 1 and r["samples"]]
    vals = []
    for r in rows:
        st = session_stats(r)
        if g["metric"] == "best_lap_s" and st["summary"]["best_time_s"] is not None:
            vals.append(st["summary"]["best_time_s"])
        elif g["metric"] == "lap_std_s" and st["summary"]["std_time_s"] is not None:
            vals.append(st["summary"]["std_time_s"])
        elif g["metric"] == "slow_corner_loss_s":
            ls = [c["mean_loss_s"] for c in st["corners"] if c["slow"] and c["mean_loss_s"] is not None]
            if ls:
                vals.append(float(np.mean([max(0.0, x) for x in ls])))
    cur = min(vals) if vals else None
    base = g["baseline"]
    res = {**g, "sessions_considered": len(rows), "current": cur, "achieved": cur is not None and cur <= g["target"]}
    if cur is not None and base is not None and base != g["target"]:
        res["progress"] = round(max(0.0, min(1.0, (base - cur) / (base - g["target"]))), 3)
    return res


def training_plan(catalog: Catalog, session_id: str, top: int = 3) -> dict:
    row = catalog.get_session(session_id)
    st = session_stats(row)
    if not st["corners"]:
        return {"available": False, "reason": "needs >= 3 valid laps with good alignment quality", "items": []}
    ranked = []
    for c in st["corners"]:
        cons = c["consistency"] or {}
        score = (c["mean_loss_s"] or 0.0) + 0.02 * (cons.get("brake_start_std_m") or 0.0) + 0.05 * (cons.get("min_speed_std_kmh") or 0.0)
        ranked.append((score, c))
    ranked.sort(key=lambda x: -x[0])
    items = []
    for score, c in ranked[:top]:
        if score <= 0.02:
            continue
        cons = c["consistency"] or {}
        facts = {"corner": c["corner"], "mean_loss_vs_best_lap_s": c["mean_loss_s"], "brake_start_std_m": cons.get("brake_start_std_m"),
                 "min_speed_std_kmh": cons.get("min_speed_std_kmh"), "finding_counts": c["finding_counts"], "laps_compared": c["n_compared"]}
        if c["finding_counts"]:
            main = max(c["finding_counts"], key=c["finding_counts"].get)
            focus = {"early_braking": "ripeti il punto di frenata: segna un riferimento fisso e avvicinalo gradualmente",
                     "late_braking": "frenata troppo tardiva rispetto al tuo giro migliore: verifica velocità minima e uscita",
                     "late_throttle": "anticipa la ripresa del gas dopo l'apice, in modo progressivo",
                     "low_min_speed": "lavora sulla velocità minima: meno velocità persa in inserimento",
                     "slow_exit": "cura l'uscita: apice e gas per massimizzare la velocità in uscita",
                     "early_brake_release": "mantieni il freno più a lungo nella fase di rilascio",
                     "brake_peak_higher": "modula il picco di frenata"}.get(main, "analizza il punto")
        else:
            main, focus = "inconsistency", "ripeti la stessa traiettoria/frenata: la variabilità tra giri è il punto debole misurato"
        items.append({"title": f"Curva {c['corner']}: {focus}", "basis": main, "facts": facts, "provisional_corner_id": c["provisional"],
                      "drill": "5 giri focalizzati solo su questa curva, poi confronta punto di frenata e velocità minima con il giro migliore"})
    return {"available": True, "items": items, "note": "Derived only from measured loss and lap-to-lap variability in this session."}
