"""Compare values the user READ OFF THE LMU HUD at known moments with the recorded samples around those moments.

HUD and sampling are never simultaneous (display latency, the person looking, typing afterwards), so each annotation is
compared with ALL samples in a window (default +-1.5 s): a HUD value matches if it lies within [min - tol, max + tol] of that
window (gear/lap: if it is one of the values seen in the window). No millisecond precision is assumed or required.

Annotation file (JSON list), one entry per moment:
  {"epoch": 1731170000.5 | "utc": "2026-11-09T17:02:03Z", "speed_kmh": 143, "rpm": 7200, "gear": 4, "lap": 2,
   "throttle_pct": 100, "brake_pct": 0}      (every value optional; omit what you did not read)
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

WINDOW_S = 1.5
# (column in recording, scale to HUD units, absolute tolerance, relative tolerance)
FIELDS = {
    "speed_kmh": ("speed_kmh", 1.0, 3.0, 0.03),
    "rpm": ("rpm", 1.0, 150.0, 0.03),
    "throttle_pct": ("throttle", 100.0, 10.0, 0.0),
    "brake_pct": ("brake", 100.0, 10.0, 0.0),
}
DISCRETE = {"gear": "gear", "lap": "lap_number"}
MIN_PASS_RATE = 0.8
MIN_MARKS = 3


def _epoch(a: dict) -> float | None:
    if a.get("epoch") is not None:
        return float(a["epoch"])
    if a.get("utc"):
        return datetime.fromisoformat(str(a["utc"]).replace("Z", "+00:00")).timestamp()
    return None


def _window(con, t: float, w: float) -> list[dict]:
    cols = ["speed_kmh", "rpm", "throttle", "brake", "gear", "lap_number"]
    rows = con.execute(f"select {', '.join(cols)} from samples where wall_time between ? and ?", [t - w, t + w]).fetchall()
    return [dict(zip(cols, r)) for r in rows]


def compare(annotations: list[dict], samples_db: Path, window_s: float = WINDOW_S) -> dict:
    import duckdb
    con = duckdb.connect(str(samples_db), read_only=True)
    marks, per_field = [], {}
    try:
        for i, a in enumerate(annotations):
            t = _epoch(a)
            m: dict = {"index": i, "epoch": t, "results": {}}
            if t is None:
                m["error"] = "annotation has neither 'epoch' nor 'utc'"
                marks.append(m)
                continue
            win = _window(con, t, window_s)
            m["samples_in_window"] = len(win)
            if not win:
                m["error"] = "no recorded sample within the window (annotation outside the recording?)"
                marks.append(m)
                continue
            for k, (col, scale, atol, rtol) in FIELDS.items():
                if a.get(k) is None:
                    continue
                vals = [r[col] * scale for r in win if r[col] is not None]
                if not vals:
                    m["results"][k] = {"hud": a[k], "ok": None, "note": "channel not recorded"}
                    continue
                tol = max(atol, rtol * abs(float(a[k])))
                lo, hi = min(vals), max(vals)
                ok = lo - tol <= float(a[k]) <= hi + tol
                m["results"][k] = {"hud": a[k], "recorded_min": round(lo, 1), "recorded_max": round(hi, 1), "tolerance": round(tol, 1), "ok": ok}
            for k, col in DISCRETE.items():
                if a.get(k) is None:
                    continue
                seen = sorted({int(r[col]) for r in win if r[col] is not None})
                m["results"][k] = {"hud": a[k], "recorded_values": seen, "ok": int(a[k]) in seen,
                                   "offset_if_constant": (int(a[k]) - seen[0]) if len(seen) == 1 else None}
            marks.append(m)
    finally:
        con.close()
    for m in marks:
        for k, r in m["results"].items():
            f = per_field.setdefault(k, {"marks": 0, "pass": 0, "fail": 0})
            if r["ok"] is None:
                continue
            f["marks"] += 1
            f["pass" if r["ok"] else "fail"] += 1
    # a constant +-1 lap/gear offset is a CONVENTION difference (e.g. 0-based laps), reported but not hidden
    notes = []
    for k in DISCRETE:
        offs = {m["results"][k]["offset_if_constant"] for m in marks if k in m["results"] and not m["results"][k]["ok"]}
        offs.discard(None)
        n_fail = per_field.get(k, {}).get("fail", 0)
        if n_fail and len(offs) == 1 and per_field[k]["pass"] == 0:
            notes.append(f"'{k}': HUD differs from the recording by a constant {offs.pop():+d} - probably a numbering convention (to be confirmed by a human).")
    for k, f in per_field.items():
        f["pass_rate"] = round(f["pass"] / f["marks"], 2) if f["marks"] else None
    valid_marks = [m for m in marks if m["results"]]
    moving = any((m["results"].get("speed_kmh") or {}).get("hud", 0) and float(m["results"]["speed_kmh"]["hud"]) > 30 for m in valid_marks)
    reasons = []
    if len(valid_marks) < MIN_MARKS:
        reasons.append(f"need at least {MIN_MARKS} usable annotations, got {len(valid_marks)}")
    if not moving:
        reasons.append("no annotation taken while moving (speed > 30 km/h): a standstill cannot validate the channels")
    bad = [k for k, f in per_field.items() if f["marks"] and f["pass_rate"] < MIN_PASS_RATE]
    if bad:
        reasons.append("fields below %d%% agreement: %s" % (MIN_PASS_RATE * 100, ", ".join(bad)))
    if not per_field:
        reasons.append("no HUD value was provided")
    verdict = "HUD COMPARISON PASSED" if not reasons else "HUD COMPARISON NOT PASSED"
    return {"tool": "race_engineer hud-compare", "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "window_s": window_s, "tolerances": {k: {"abs": v[2], "rel": v[3]} for k, v in FIELDS.items()},
            "marks": marks, "per_field": per_field, "notes": notes, "reasons": reasons, "verdict": verdict}


def to_markdown(r: dict) -> str:
    m = ["# HUD comparison", f"*{r['utc']}* - window +-{r['window_s']} s around each annotation (no millisecond precision assumed)", "",
         f"**{r['verdict']}**" + ("".join(f"\n- {x}" for x in r["reasons"])), "",
         "| field | marks | pass | fail | pass rate |", "|---|---|---|---|---|"]
    for k, f in r["per_field"].items():
        m.append(f"| {k} | {f['marks']} | {f['pass']} | {f['fail']} | {f['pass_rate']} |")
    m += ["", "| # | field | HUD | recorded in window | ok |", "|---|---|---|---|---|"]
    for mk in r["marks"]:
        if mk.get("error"):
            m.append(f"| {mk['index']} | - | - | {mk['error']} | - |")
        for k, x in mk["results"].items():
            rec = x.get("recorded_values") or f"{x.get('recorded_min')}..{x.get('recorded_max')}"
            m.append(f"| {mk['index']} | {k} | {x['hud']} | {rec} | {x['ok']} |")
    m += [""] + [f"- {n}" for n in r["notes"]]
    m += ["", "A passed comparison is evidence about the CHANNEL MAPPING; the final acceptance decision stays with the user."]
    return "\n".join(m)


def run(annotations_path: str | Path, verify_json: str | Path, out_dir: Path | None = None, data_root: Path | None = None) -> tuple[dict, Path]:
    from ..storage.paths import data_dir
    vr = json.loads(Path(verify_json).read_text(encoding="utf-8"))
    ann = json.loads(Path(annotations_path).read_text(encoding="utf-8-sig"))
    if isinstance(ann, dict):
        ann = ann.get("annotations", [])
    rec = vr.get("recording")
    if not rec:
        raise SystemExit("the verification report has no recording (no samples were acquired)")
    root = Path(data_root) if data_root else Path(data_dir())
    db = root / "verify_runs" / rec["run_name"] / rec["data_file"]
    if not db.is_file():
        raise SystemExit(f"recording not found: {db}")
    rep = compare(ann, db)
    rep["verify_report"] = Path(verify_json).name
    rep["data_origin"] = vr.get("data_source")
    out = Path(out_dir) if out_dir else root / "reports"
    out.mkdir(parents=True, exist_ok=True)
    from ..storage.paths import unique_stem
    stem = unique_stem(out, "hud_comparison_")
    from .verify import sanitize, sanitize_obj
    (out / f"{stem}.json").write_text(json.dumps(sanitize_obj(rep), indent=2, default=str), encoding="utf-8")
    md = out / f"{stem}.md"
    md.write_text(sanitize(to_markdown(rep)), encoding="utf-8")
    return rep, md
