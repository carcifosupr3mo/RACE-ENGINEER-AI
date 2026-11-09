"""``python -m race_engineer duckdb-report <file.duckdb>``: local schema + data-quality report of a real LMU telemetry file.

* The original file is NEVER modified (opened read-only on a scratch copy). Nothing is uploaded.
* Personal values are redacted: metadata keys that look personal (driver, player, user, steam, email, ...) are
  masked, user-home paths are shortened.
* The G-force question (third parties report that ``G Force Lat`` and ``G Force Long`` contents are swapped) is
  answered with EVIDENCE from the file itself, never by flipping axes on assumption: longitudinal acceleration
  derived from ``Ground Speed`` is correlated with both channels, and lateral acceleration derived from
  speed x heading-rate proxies (``Steering Pos``) likewise. The verdict only says what the data show;
  the importer keeps skipping G channels until a real file confirms the mapping.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import numpy as np

from ..lmu.verify import sanitize, sanitize_obj
from .lmu_duckdb import LmuDuckdb, q

PERSONAL = re.compile(r"driver|player|user|steam|email|account|name_?id|pc|machine|host", re.I)
SAFE_KEYS = re.compile(r"^(Track|Car|Session|Version|Recording|Game)", re.I)


def _redact(k: str, v: str) -> str:
    v = re.sub(r"(?i)(users[\\/])[^\\/\"]+", r"\1<user>", str(v))
    if PERSONAL.search(k) and not SAFE_KEYS.match(k):
        return "<redacted>"
    return v if len(v) <= 300 else v[:300] + f"...[{len(v)} chars]"


def json_tree(o, depth=0, max_depth=6):
    """Structure of a JSON value (types and keys) without large payloads; used for the CarSetup blob."""
    if depth >= max_depth:
        return "..."
    if isinstance(o, dict):
        return {k: json_tree(v, depth + 1, max_depth) for k, v in list(o.items())[:80]}
    if isinstance(o, list):
        return [json_tree(o[0], depth + 1, max_depth), f"... x{len(o)}"] if o else []
    return type(o).__name__ if not isinstance(o, (int, float)) or isinstance(o, bool) else o


def _series(d: LmuDuckdb, name: str, col: str = "value"):
    try:
        info = d.read_channel(name)
    except Exception:
        return None
    arr = info["values"]
    if arr.ndim == 1 or arr.shape[1] == 1:
        return info["frequency"], np.asarray(arr).reshape(-1), info["unit"]
    return info["frequency"], arr[:, 0], info["unit"]


def _resample(fs, x, target_hz=20.0):
    n = int(len(x) / fs * target_hz)
    if n < 10:
        return None
    t = np.arange(len(x)) / fs
    return np.interp(np.arange(n) / target_hz, t, x)


def _best_corr(a: np.ndarray, b: np.ndarray, max_lag: int = 20) -> tuple[float, int]:
    """Pearson correlation allowing a small time shift (reconstructed time has an unknown start offset)."""
    best = (0.0, 0)
    for lag in range(-max_lag, max_lag + 1):
        x = a[max(0, lag):len(a) + min(0, lag)]
        y = b[max(0, -lag):len(b) - max(0, lag)]
        n = min(len(x), len(y))
        if n < 30 or np.std(x[:n]) < 1e-9 or np.std(y[:n]) < 1e-9:
            continue
        c = float(np.corrcoef(x[:n], y[:n])[0, 1])
        if abs(c) > abs(best[0]):
            best = (c, lag)
    return best


def gforce_analysis(d: LmuDuckdb) -> dict:
    out: dict = {"question": "are 'G Force Lat'/'G Force Long' contents swapped? (third-party report, unverified)"}
    gl, gg = _series(d, "G Force Lat"), _series(d, "G Force Long")
    sp = _series(d, "Ground Speed")
    if not (gl and gg and sp):
        return dict(out, verdict="not_testable", reason="G Force Lat/Long and Ground Speed must all be present")
    hz = 20.0
    v = _resample(sp[0], sp[1], hz)
    lat, lon = _resample(gl[0], gl[1], hz), _resample(gg[0], gg[1], hz)
    if v is None or lat is None or lon is None:
        return dict(out, verdict="not_testable", reason="too few samples")
    unit = (sp[2] or "").lower()
    v_ms = v / 3.6 if "km" in unit else v
    n = min(len(v_ms), len(lat), len(lon))
    v_ms, lat, lon = v_ms[:n], lat[:n], lon[:n]
    acc = np.gradient(np.convolve(v_ms, np.ones(5) / 5, mode="same"), 1.0 / hz)   # longitudinal accel from speed
    c_long_long, l1 = _best_corr(acc, lon)
    c_long_lat, l2 = _best_corr(acc, lat)
    st = _series(d, "Steering Pos")
    c_steer_lat = c_steer_lon = None
    if st:
        s = _resample(st[0], st[1], hz)[:n]
        lat_proxy = s * v_ms ** 2          # ~ lateral accel up to a constant (steering angle x v^2)
        c_steer_lat = _best_corr(np.abs(lat_proxy), np.abs(lat))[0]
        c_steer_lon = _best_corr(np.abs(lat_proxy), np.abs(lon))[0]
    out.update(
        corr_dv_dt_vs_GForceLong=round(c_long_long, 3), corr_dv_dt_vs_GForceLat=round(c_long_lat, 3),
        corr_abs_steering_v2_vs_abs_GForceLat=None if c_steer_lat is None else round(c_steer_lat, 3),
        corr_abs_steering_v2_vs_abs_GForceLong=None if c_steer_lon is None else round(c_steer_lon, 3),
        ranges={"G Force Lat": [float(np.min(lat)), float(np.max(lat))], "G Force Long": [float(np.min(lon)), float(np.max(lon))]},
        units={"G Force Lat": gl[2], "G Force Long": gg[2]}, lag_samples_at_20hz=[l1, l2])
    strong = max(abs(c_long_long), abs(c_long_lat))
    if strong < 0.4:
        out["verdict"] = "inconclusive"
        out["reason"] = "speed-derived acceleration correlates weakly with both channels (too little braking/accel, or other units)"
    elif abs(c_long_long) > abs(c_long_lat) + 0.2:
        out["verdict"] = "as_named"
    elif abs(c_long_lat) > abs(c_long_long) + 0.2:
        out["verdict"] = "swapped"
    else:
        out["verdict"] = "inconclusive"
        out["reason"] = "both channels correlate similarly with speed-derived acceleration"
    out["sign_note"] = (f"sign of corr(dv/dt, G Force Long) = {np.sign(c_long_long):+.0f}; the importer does not flip "
                        "signs; report it so the convention can be fixed from evidence")
    out["action"] = ("keep G channels OUT of the import mapping until a real file gives verdict 'as_named' or 'swapped' "
                     "with strong correlation on at least two sessions")
    return out


def report(path: str | Path, out_dir: Path | None = None, sample_stats: bool = True) -> tuple[dict, Path]:
    rep: dict = {"tool": "race_engineer duckdb-report", "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 "file": {"name": Path(path).name, "size_bytes": Path(path).stat().st_size}, "original_modified": False}
    before = Path(path).stat()
    with LmuDuckdb(path, copy_first=True) as d:
        ins = d.inspect()
        rep["ok"] = ins.ok
        rep["problems"] = ins.problems
        rep["metadata"] = {k: _redact(k, v) for k, v in ins.metadata.items() if k != "CarSetup"}
        cs = ins.metadata.get("CarSetup")
        if cs:
            try:
                rep["car_setup_structure"] = json_tree(json.loads(cs))
                rep["car_setup_json_valid"] = True
            except ValueError:
                rep["car_setup_json_valid"] = False
                rep["car_setup_head"] = cs[:200]
        rep["channels"], rep["events"] = ins.channels, ins.events
        rep["missing_core_channels"], rep["missing_core_events"] = ins.missing_core_channels, ins.missing_core_events
        rep["undeclared_tables"], rep["duration_inconsistency"] = ins.undeclared_tables, ins.duration_inconsistency
        rep["tables_by_columns"] = {t: [f"{c}:{ty}" for c, ty in cols] for t, cols in list(d.tables().items())[:400]}
        if sample_stats:
            for ch in rep["channels"]:
                if not ch["present"] or not ch["rows"]:
                    continue
                cols = ch["columns"]
                sel = ", ".join(f"min({q(c)}), max({q(c)}), avg({q(c)})" for c in cols)
                row = d.con.execute(f"SELECT {sel} FROM {q(ch['name'])}").fetchone()
                ch["stats"] = {c: {"min": row[i * 3], "max": row[i * 3 + 1], "mean": row[i * 3 + 2]} for i, c in enumerate(cols)}
                ch["first_values"] = d.con.execute(f"SELECT * FROM {q(ch['name'])} LIMIT 3").fetchall()
        for ev in rep["events"]:
            if ev.get("present") and ev.get("rows"):
                ev["first_rows"] = d.con.execute(f"SELECT * FROM {q(ev['name'])} ORDER BY ts LIMIT 3").fetchall()
        rep["g_force_analysis"] = gforce_analysis(d)
    after = Path(path).stat()
    rep["original_modified"] = (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size)
    from ..storage.paths import data_dir, unique_stem
    out = Path(out_dir) if out_dir else data_dir() / "reports"
    out.mkdir(parents=True, exist_ok=True)
    stem = unique_stem(out, "duckdb_report_")
    (out / f"{stem}.json").write_text(json.dumps(sanitize_obj(rep), indent=2, default=str), encoding="utf-8")
    md = out / f"{stem}.md"
    md.write_text(sanitize(to_markdown(rep)), encoding="utf-8")
    return rep, md


def to_markdown(r: dict) -> str:
    m = ["# LMU DuckDB telemetry report", f"File: `{r['file']['name']}` ({r['file']['size_bytes']} B) - generated {r['generated_utc']}",
         f"Original file modified: **{r['original_modified']}**", "", f"Matches documented layout: **{r['ok']}**"]
    m += [f"- problem: {p}" for p in r["problems"]]
    m += ["", "## Metadata (personal keys redacted)"] + [f"- {k}: {v}" for k, v in r["metadata"].items()]
    m += ["", f"CarSetup JSON present: {r.get('car_setup_json_valid')}", "",
          "## Channels (name, Hz, unit, rows, columns)", "| name | Hz | unit | rows | cols | min..max |", "|---|---|---|---|---|---|"]
    for c in r["channels"]:
        st = c.get("stats", {})
        rng = "; ".join(f"{k}:{v['min']:.4g}..{v['max']:.4g}" for k, v in st.items() if v["min"] is not None)
        m.append(f"| {c['name']} | {c['frequency']} | {c['unit']} | {c['rows']} | {','.join(c['columns'])} | {rng} |")
    m += ["", "## Events"] + [f"- {e['name']} [{e['unit']}] rows={e['rows']} cols={e['columns']}" for e in r["events"]]
    m += ["", f"Missing core channels: {r['missing_core_channels']}; events: {r['missing_core_events']}",
          f"Undeclared tables: {r['undeclared_tables']}", f"Duration inconsistencies: {r['duration_inconsistency']}",
          "", "## G-force anomaly test", "```json", json.dumps(r["g_force_analysis"], indent=2, default=str), "```",
          "", "Local report: nothing uploaded; the .duckdb was opened read-only on a scratch copy."]
    return "\n".join(m)
