"""``python -m race_engineer verify-lmu``: one-shot real-LMU verification producing a sanitized report.

Run it on the Windows PC with LMU open and a session loaded (on track, driving if possible).
It is READ-ONLY with respect to the game: it only reads the ``LMU_Data`` mapping and the install
folders. The report contains NO credentials, NO user name (home paths are shortened to ``~``) and NO
driver names; it can be shared safely. Nothing is uploaded anywhere.

Every check ends as pass / fail / unknown: "unknown" is never presented as a pass.
"""
from __future__ import annotations

import dataclasses
import json
import os
import platform
import re
import sys
import time
from pathlib import Path

from . import layout as L
from .discovery import find_install, is_lmu_process_running
from .reader import MappingNotFound, SharedMemoryReader, open_backend

READ_ONLY_FORBIDDEN = ("FILE_MAP_WRITE", "FILE_MAP_ALL_ACCESS", "PAGE_READWRITE", "WriteProcessMemory",
                       "OpenProcess", "CreateRemoteThread", "VirtualAllocEx", "SetWindowsHookEx", "CreateFileMapping")


def sanitize(s: str) -> str:
    """Shorten personal path prefixes (user name) so the report can be shared."""
    s = str(s)
    for env in ("USERPROFILE", "HOME"):
        v = os.environ.get(env)
        if v:
            s = s.replace(v, "~").replace(v.replace("\\", "/"), "~")
    return re.sub(r"(?i)(users[\\/])[^\\/]+", r"\1<user>", s)


def check_read_only_source() -> dict:
    """Static proof for this build: the package source contains no write/inject API for the mapping or the game."""
    root = Path(__file__).resolve().parent.parent
    hits = []
    for p in root.rglob("*.py"):
        if p.name == "verify.py":
            continue
        try:
            t = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for w in READ_ONLY_FORBIDDEN:
            if w in t:
                hits.append(f"{p.relative_to(root)}:{w}")
    return {"ok": not hits, "forbidden_api_hits": hits,
            "access_flag_used": "FILE_MAP_READ only (reader.py)", "kind": "static source scan"}


def _c(cid: str, ok, title: str, detail: str = "") -> dict:
    return {"id": cid, "ok": ok, "title": title, "detail": sanitize(detail)}


def snapshot_checks(rd: SharedMemoryReader) -> list[dict]:
    """Plausibility of one decoded snapshot (units, ranges, strings). 'unknown' when the car is not live."""
    out = []
    snap = rd.read_snapshot()
    g, info = snap.generic, snap.info
    out.append(_c("game_version", True if g.gameVersion > 0 else None, "gameVersion in mapping (0 = not published / layout offset suspect)", f"gameVersion={g.gameVersion}"))
    out.append(_c("num_vehicles", 0 <= info.mNumVehicles <= L.MAX_MAPPED_VEHICLES, "mNumVehicles within 0..104",
                  f"mNumVehicles={info.mNumVehicles}"))
    out.append(_c("player_found", snap.veh is not None, "player vehicle found in scoring (mIsPlayer)",
                  f"telemetry slot idx={snap.player_idx} has_vehicle={snap.player_has_vehicle} active={snap.active_vehicles}"))
    track = bytes(info.mTrackName).split(b"\0")[0].decode("utf-8", "replace")
    out.append(_c("track_string", bool(track) and track.isprintable(), "track name decodes to printable text", f"mTrackName={track!r}"))
    out.append(_c("track_length", 500 < info.mLapDist < 30000, "track length 500..30000 m", f"mLapDist={info.mLapDist:.1f}"))
    t = snap.telem
    if t is None:
        out.append(_c("telemetry_slot", None, "player telemetry not available in this snapshot",
                      "load a session and get into the car (on track), then re-run"))
        return out
    import math
    sp = math.sqrt(t.mLocalVel.x ** 2 + t.mLocalVel.y ** 2 + t.mLocalVel.z ** 2) * 3.6
    out += [
        _c("speed_range", 0 <= sp < 450, "speed from mLocalVel in 0..450 km/h", f"{sp:.1f} km/h"),
        _c("rpm_range", 0 <= t.mEngineRPM < 25000, "engine RPM 0..25000", f"{t.mEngineRPM:.0f}"),
        _c("rpm_vs_max", t.mEngineMaxRPM > 3000 and t.mEngineRPM <= t.mEngineMaxRPM * 1.1, "RPM <= 1.1 x max RPM",
           f"rpm={t.mEngineRPM:.0f} max={t.mEngineMaxRPM:.0f}"),
        _c("gear_range", -1 <= t.mGear <= 9, "gear -1..9", f"{t.mGear}"),
        _c("pedals_range", all(-0.001 <= v <= 1.001 for v in (t.mUnfilteredThrottle, t.mUnfilteredBrake, t.mUnfilteredClutch)),
           "unfiltered throttle/brake/clutch in 0..1", f"thr={t.mUnfilteredThrottle:.3f} brk={t.mUnfilteredBrake:.3f} clu={t.mUnfilteredClutch:.3f}"),
        _c("steering_range", -1.001 <= t.mUnfilteredSteering <= 1.001, "unfiltered steering -1..1", f"{t.mUnfilteredSteering:.3f}"),
        _c("fuel_range", 0 <= t.mFuel <= 300, "fuel 0..300 L", f"{t.mFuel:.2f} L (capacity {t.mFuelCapacity:.1f})"),
        _c("elapsed_time", t.mElapsedTime > 0, "mElapsedTime > 0", f"{t.mElapsedTime:.3f} s"),
        _c("tyre_pressure_kpa", all(10 < w.mPressure < 600 for w in t.mWheels) or all(w.mPressure == 0 for w in t.mWheels),
           "tyre pressures plausible (kPa) or all-zero (unavailable)", str([round(w.mPressure, 1) for w in t.mWheels])),
        _c("tyre_temp_kelvin", all(250 < w.mTemperature[1] < 500 for w in t.mWheels) or all(w.mTemperature[1] == 0 for w in t.mWheels),
           "tyre carcass temp plausible in Kelvin (250..500) or unavailable", str([round(w.mTemperature[1], 1) for w in t.mWheels])),
        _c("brake_temp_unit", all(0 <= w.mBrakeTemp < 2000 for w in t.mWheels),
           "brake temperature plausible; UNIT must be confirmed on a hot brake (header says Celsius)", str([round(w.mBrakeTemp, 1) for w in t.mWheels])),
    ]
    return out


def _quality(db_path: Path, session_id: str, expected_hz: float) -> dict:
    import duckdb
    con = duckdb.connect(str(db_path), read_only=True)
    n = con.execute("select count(*) from samples").fetchone()[0]
    if not n:
        return {"rows": 0}
    cols = [r[0] for r in con.execute("describe samples").fetchall()
            if r[1] in ("DOUBLE", "FLOAT", "INTEGER", "BIGINT", "SMALLINT", "TINYINT") and r[0] not in ("wall_time",)]
    sel = ", ".join(f'min("{c}"), max("{c}"), avg("{c}"), count("{c}")' for c in cols)
    row = con.execute(f"select {sel} from samples").fetchone()
    ch = {}
    for i, c in enumerate(cols):
        mn, mx, av, cnt = row[i * 4:i * 4 + 4]
        ch[c] = {"min": mn, "max": mx, "mean": av, "non_null": cnt, "constant": mn == mx}
    et = [r[0] for r in con.execute("select session_time_s from samples order by wall_time").fetchall()] if "session_time_s" in cols else []
    back = sum(1 for a, b in zip(et, et[1:]) if b < a)
    wall = con.execute("select min(wall_time), max(wall_time) from samples").fetchone()
    dur = (wall[1] - wall[0]) if wall[0] is not None else 0
    prov = dict(con.execute("select provenance, count(*) from samples group by 1").fetchall())
    con.close()
    return {"rows": n, "wall_start": wall[0], "wall_end": wall[1], "wall_duration_s": round(dur, 2), "mean_hz": round(n / dur, 1) if dur > 0 else None,
            "expected_hz": expected_hz, "elapsed_time_going_backwards": back, "provenance_counts": prov,
            "channels_all_null": sorted(c for c, v in ch.items() if v["non_null"] == 0),
            "channels_constant": sorted(c for c, v in ch.items() if v["constant"] and v["non_null"]),
            "channel_stats": ch}


def run(seconds: int = 60, out_dir: Path | None = None, shm_path: str | None = None, say=print) -> tuple[dict, Path]:
    from ..acquisition.engine import AcquisitionEngine
    from ..storage.catalog import Catalog
    from ..storage.paths import data_dir
    t0 = time.time()
    rep: dict = {"tool": "race_engineer verify-lmu", "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 "platform": {"os": platform.platform(), "python": sys.version.split()[0], "sys_platform": sys.platform},
                 "layout_source": L.LAYOUT_SOURCE, "expected_mapping_size": L.MAPPING_SIZE, "checks": [], "verdict": ""}
    from ..app_info import info as _app_info
    rep["app"] = _app_info()
    rep["data_source"] = "file/bridge override (--shm-path): NOT real LMU" if shm_path else "OS shared memory 'LMU_Data'"
    chk = rep["checks"]
    on_win = sys.platform == "win32"
    chk.append(_c("windows", on_win, "running on Windows",
                  "" if on_win else "NOT Windows: this run can NOT verify the real LMU on Windows (only a Wine/file bridge, if any)."))
    inst = find_install()
    rep["install"] = {k: sanitize(v) if isinstance(v, str) else v for k, v in dataclasses.asdict(inst).items()
                      if k in ("found", "game_dir", "user_data", "telemetry_dir", "shared_memory_header_dir", "notes")}
    rep["install"]["duckdb_files_count"] = len(inst.duckdb_files)
    chk.append(_c("lmu_installed", inst.found, "LMU installation found", rep["install"].get("game_dir") or ""))
    proc = is_lmu_process_running()
    chk.append(_c("process", proc, "LMU process running", "" if proc is not None else "cannot be determined here"))

    if inst.shared_memory_header_dir:
        from .header_layout import verify_header_dir
        hv = verify_header_dir(inst.shared_memory_header_dir)
        rep["header_layout_check"] = hv
        chk.append(_c("header_offsets", hv.get("all_match") if hv.get("checked") else None,
                      "struct sizes/offsets of OUR layout == offsets computed from the installed LMU headers",
                      json.dumps([s for s in hv.get("structs", []) if s.get("status") != "match"])[:800] or "all structs match"))
    else:
        chk.append(_c("header_offsets", None, "installed SharedMemoryInterface headers not found",
                      "offsets can only be cross-checked against the live mapping size and value plausibility"))
    chk.append(dict(_c("read_only", None, "reader is read-only"), **{"detail": "see read_only_source"}))
    rep["read_only_source"] = check_read_only_source()
    chk[-1]["ok"] = rep["read_only_source"]["ok"]

    try:
        be = open_backend(path_override=shm_path)
    except MappingNotFound as e:
        chk.append(_c("mapping", False, "LMU_Data mapping present", str(e)))
        rep["verdict"] = ("NOT VERIFIED: LMU_Data NOT reachable. In LMU: Settings > Gameplay > Enable Plugins, then fully restart LMU "
                          "and load a session. This tool never changes game settings.")
        return _finish(rep, out_dir, data_dir)
    rep["mapping"] = {"size": be.size, "description": be.description, "expected_min": L.MAPPING_SIZE}
    chk.append(_c("mapping", True, "LMU_Data mapping present", f"size={be.size} (Windows reports page-rounded size)"))
    chk.append(_c("mapping_size", be.size >= L.MAPPING_SIZE, "mapping size >= layout size",
                  f"{be.size} vs {L.MAPPING_SIZE}; a smaller real size means a DIFFERENT layout version"))
    rd = SharedMemoryReader(be)
    try:
        chk += snapshot_checks(rd)
        gv = rd.read_generic().gameVersion
        rep["game_version"] = gv
        ai = rd.read_generic().appInfo
        rep["application_state"] = {n: (v if isinstance(v, int) else bytes(v).split(b"\0")[0].decode("utf-8", "replace"))
                                    for n, v in ((n, getattr(ai, n)) for n, _ in L.AppState._fields_) if n != "mExpansion"}
    except Exception as e:  # report, never crash silently
        chk.append(_c("snapshot", False, "snapshot decoded", f"{type(e).__name__}: {e}"))
    finally:
        rd.close()

    # ---- live acquisition + recording
    vroot = Path(data_dir()) / "verify_runs" / time.strftime("%Y%m%d_%H%M%S")
    vroot.mkdir(parents=True, exist_ok=True)
    cat = Catalog(vroot / "catalog.sqlite")
    eng = AcquisitionEngine(lambda: open_backend(path_override=shm_path), catalog=cat, data_root=vroot, record=True)
    say(f"Recording real LMU telemetry for {seconds}s - drive on track and compare these numbers with the on-screen HUD:")
    eng.start()
    lines, seen = [], {"gears": set(), "laps": set(), "states": set()}
    vmax = rmax = 0.0
    try:
        for _ in range(seconds):
            time.sleep(1)
            s = eng.latest
            seen["states"].add(eng.state.value)
            if s:
                v = s.values
                vmax, rmax = max(vmax, v["speed_kmh"]), max(rmax, v["rpm"])
                seen["gears"].add(int(v["gear"]))
                seen["laps"].add(int(v["lap_number"]))
                line = (f"v={v['speed_kmh']:.0f}km/h rpm={v['rpm']:.0f} gear={int(v['gear'])} thr={v['throttle']:.2f} brk={v['brake']:.2f} "
                        f"steer={v['steering']:.2f} lap={int(v['lap_number'])} hz={eng.effective_hz():.0f}")
                lines.append(line)
                say(f"[{eng.state.value}] {line}")
            else:
                say(f"[{eng.state.value}] no sample yet")
    finally:
        diag = eng.diagnostics()
        sid = eng.session_id
        last = dict(eng.latest.values) if eng.latest else None
        eng.stop()
    rep["acquisition"] = {"seconds": seconds, "diagnostics": {k: v for k, v in diag.items() if k != "errors"},
                          "errors": [sanitize(e["msg"]) for e in diag["errors"]], "states_seen": sorted(seen["states"]),
                          "gears_seen": sorted(seen["gears"]), "laps_seen": sorted(seen["laps"]),
                          "speed_max_kmh": round(vmax, 1), "rpm_max": round(rmax, 0), "last_sample": last,
                          "per_second_log": lines[-20:]}
    rx, lost = diag["samples_received"], diag["samples_lost"]
    chk.append(_c("samples_flow", rx > 0, "samples received", f"{rx} samples, {diag['effective_hz']} Hz effective"))
    chk.append(_c("lost_samples", None if not rx else lost / max(1, rx + lost) < 0.01,
                  "lost samples < 1%", f"lost={lost} received={rx}"))
    row = cat.get_session(sid) if sid else None
    if row and rx:
        rep["recording_quality"] = _quality(Path(row["data_path"]), sid, diag["effective_hz"])
        q = rep["recording_quality"]
        try:
            rel = str(Path(row["data_path"]).relative_to(vroot))
        except ValueError:
            rel = Path(row["data_path"]).name
        rep["recording"] = {"run_name": vroot.name, "data_file": rel, "session_id": sid,
                            "wall_start_epoch": q.get("wall_start"), "wall_end_epoch": q.get("wall_end")}
        prov = q.get("provenance_counts") or {}
        real_only = bool(prov) and set(prov) == {"lmu_shm"} and not shm_path
        chk.append(_c("real_data_source", real_only, "every recorded sample comes from the REAL OS shared memory (provenance lmu_shm, no --shm-path)",
                      f"provenance={prov}; shm_path_override={bool(shm_path)}"))
        chk.append(_c("recording_rows", q.get("rows", 0) > 0 and abs(q["rows"] - rx) <= max(5, rx * 0.01),
                      "recorded rows == received samples", f"rows={q.get('rows')} received={rx}"))
        chk.append(_c("monotonic_time", q.get("elapsed_time_going_backwards", 1) == 0, "session time never goes backwards",
                      str(q.get("elapsed_time_going_backwards"))))
    chk.append(_c("manual_hud_compare", None, "MANUAL: compare speed/RPM/gear/lap above with the LMU HUD",
                  "fill 'manual_comparison' in the Markdown report; this step cannot be automated"))
    cat.close()
    rep["manual_comparison"] = {"hud_speed_kmh": None, "hud_rpm": None, "hud_gear": None, "hud_lap": None,
                                "note": "fill in by hand and keep with the report"}
    fails = [c for c in chk if c["ok"] is False]
    unknown = [c for c in chk if c["ok"] is None]
    rep["verdict"] = ("REAL LMU VERIFIED (automatic checks) - manual HUD comparison still required" if on_win and not fails and rx
                      else f"NOT VERIFIED: {len(fails)} failed check(s): " + ", ".join(c["id"] for c in fails)
                      if fails else "INCONCLUSIVE: no samples or not on Windows")
    rep["unknown_checks"] = [c["id"] for c in unknown]
    rep["duration_s"] = round(time.time() - t0, 1)
    return _finish(rep, out_dir, data_dir)


def to_markdown(rep: dict) -> str:
    m = [f"# LMU verification report", f"*{rep['started_utc']}* - {rep['platform']['os']} - Python {rep['platform']['python']}", "",
         f"**Verdict: {rep['verdict']}**", "", "| check | result | detail |", "|---|---|---|"]
    for c in rep["checks"]:
        r = {True: "PASS", False: "**FAIL**", None: "unknown"}[c["ok"]]
        m.append(f"| {c['title']} | {r} | {str(c['detail']).replace('|', '/')[:300]} |")
    if "mapping" in rep:
        m += ["", f"mapping.size = {rep['mapping']['size']} (expected >= {rep['mapping']['expected_min']}), gameVersion = {rep.get('game_version')}"]
    a = rep.get("acquisition")
    if a:
        d = a["diagnostics"]
        m += ["", f"effective_hz = {d['effective_hz']}, received = {d['samples_received']}, lost = {d['samples_lost']}, "
                  f"reconnects = {d['reconnects']}, states = {a['states_seen']}"]
        q = rep.get("recording_quality") or {}
        m += [f"recording: rows={q.get('rows')} mean_hz={q.get('mean_hz')} constant channels={q.get('channels_constant')} "
              f"all-null channels={q.get('channels_all_null')}"]
    m += ["", "## Manual HUD comparison (fill in)", "| | tool | LMU HUD |", "|---|---|---|"]
    ls = (a or {}).get("last_sample") or {}
    for k, label in (("speed_kmh", "speed km/h"), ("rpm", "rpm"), ("gear", "gear"), ("lap_number", "lap")):
        m.append(f"| {label} | {ls.get(k)} | |")
    m += ["", "Contains no credentials; user paths are shortened. Not uploaded anywhere."]
    return "\n".join(m)


def _finish(rep: dict, out_dir, data_dir) -> tuple[dict, Path]:
    out = Path(out_dir) if out_dir else Path(data_dir()) / "reports"
    out.mkdir(parents=True, exist_ok=True)
    from ..storage.paths import unique_stem
    stem = unique_stem(out, "lmu_verification_")
    (out / f"{stem}.json").write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    (out / f"{stem}.md").write_text(to_markdown(rep), encoding="utf-8")
    return rep, out / f"{stem}.md"
