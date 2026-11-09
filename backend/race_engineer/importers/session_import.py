"""Import an LMU native DuckDB telemetry file as a session in OUR derived store (original untouched).

ASSUMPTIONS (third-party documentation, unverified on real files; reported in the import result):
 * fixed-frequency channels start together at ``GPS Time[0]`` (session time) and advance by 1/frequency;
 * ``Lap`` events (ts = session seconds) give the lap number; ``Lap Time`` events give completed lap times;
 * unit '%' channels are scaled to 0..1; steering sign is NOT verified (kept as documented: right positive, /100).
Channels not present stay None (provenance 'unavailable'). G-force channels are deliberately NOT imported
(documented name/content mismatch).
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from ..model.provenance import Provenance
from ..model.sample import Sample, SessionContext, session_type_name
from ..storage.catalog import Catalog
from ..storage.recorder import SessionRecorder
from .lmu_duckdb import LmuDuckdb

GRID_HZ = 50
MAP = {"Ground Speed": ("speed_kmh", 1.0), "Throttle Pos": ("throttle", 0.01), "Brake Pos": ("brake", 0.01),
       "Steering Pos": ("steering", 0.01), "Engine RPM": ("rpm", 1.0), "Lap Dist": ("lap_dist_m", 1.0),
       "Fuel Level": ("fuel_l", 1.0)}
SESSION_NAMES = {"practice": 1, "qualify": 5, "qualifying": 5, "race": 10, "warmup": 9, "test": 0}


def import_lmu_duckdb(path: str | Path, catalog: Catalog, data_root: Path, track_length_m: float | None = None) -> dict:
    path = Path(path)
    warnings: list[str] = []
    with LmuDuckdb(path, copy_first=True) as d:
        insp = d.inspect()
        if not insp.ok:
            raise ValueError("not an LMU telemetry DuckDB: " + "; ".join(insp.problems))
        meta = insp.metadata
        ch = {name: d.read_channel(name) for name in MAP if any(c["name"] == name for c in insp.channels)}
        gps = d.read_channel("GPS Time")["values"][:, 0] if any(c["name"] == "GPS Time" for c in insp.channels) else None
        laps = d.read_events("Lap")["rows"] if any(e["name"] == "Lap" for e in insp.events) else []
        lap_times = d.read_events("Lap Time")["rows"] if any(e["name"] == "Lap Time" for e in insp.events) else []
        gears = d.read_events("Gear")["rows"] if any(e["name"] == "Gear" for e in insp.events) else []
    if "Lap Dist" not in ch or not laps:
        raise ValueError("cannot build laps: 'Lap Dist' channel or 'Lap' events missing")
    t0 = float(gps[0]) if gps is not None and len(gps) else float(laps[0][0])
    if gps is None:
        warnings.append("GPS Time missing: start offset assumed equal to first Lap event")
    dur = min(len(c["values"]) / c["frequency"] for c in ch.values())
    ts = np.arange(0, dur, 1.0 / GRID_HZ)
    series = {}
    for name, (col, scale) in MAP.items():
        if name in ch:
            c = ch[name]
            idx = np.minimum((ts * c["frequency"]).astype(int), len(c["values"]) - 1)
            series[col] = c["values"][idx, 0] * (scale if c["unit"] == "%" or scale == 1.0 else 1.0)
    lap_ev = np.array([r[0] for r in laps]); lap_no = np.array([r[1] for r in laps])
    gear_ev = np.array([r[0] for r in gears]); gear_val = np.array([r[1] for r in gears])
    lt_ev = np.array([r[0] for r in lap_times]); lt_val = np.array([r[1] for r in lap_times])
    L = float(track_length_m or np.nanmax(series["lap_dist_m"]) * 1.0)
    ctx = SessionContext(track_name=meta.get("TrackName", ""), vehicle_name=meta.get("CarName", ""),
                         vehicle_class=meta.get("CarClass", ""), driver_name=meta.get("DriverName", ""),
                         session_type=meta.get("SessionType", "unknown").lower(), track_length_m=L)
    out_dir = data_root / "sessions"; out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"import_{int(time.time() * 1000)}.duckdb"
    sid = catalog.create_session(source="duckdb_import", is_synthetic=ctx.track_name.startswith("[SYNTHETIC]"),
                                 data_path=str(dest), ctx=ctx)
    rec = SessionRecorder(dest, sid)
    wall = time.time()
    for i, t in enumerate(ts):
        st = t0 + float(t)
        li = np.searchsorted(lap_ev, st, side="right") - 1
        gi = np.searchsorted(gear_ev, st, side="right") - 1
        ki = np.searchsorted(lt_ev, st, side="right") - 1
        vals = {c.name: None for c in __import__("race_engineer.model.channels", fromlist=["CHANNELS"]).CHANNELS}
        for col, arr in series.items():
            vals[col] = float(arr[i])
        vals["session_time_s"] = st
        vals["lap_number"] = int(lap_no[max(li, 0)])
        vals["gear"] = int(gear_val[gi]) if gi >= 0 else None
        vals["last_lap_time_s"] = float(lt_val[ki]) if ki >= 0 else -1.0
        rec.add(Sample(wall, Provenance.DUCKDB_IMPORT, vals))
    rec.close()
    catalog.finish_session(sid, rec.written, 0, complete=True)
    warnings.append("fixed-frequency channels aligned by index/frequency from GPS Time[0] (unverified on real files)")
    return {"session_id": sid, "samples": rec.written, "grid_hz": GRID_HZ, "warnings": warnings,
            "not_imported": ["G-force channels (name/content mismatch reported by third parties)", "tyre/brake/temperature channels (Phase 6)"]}
