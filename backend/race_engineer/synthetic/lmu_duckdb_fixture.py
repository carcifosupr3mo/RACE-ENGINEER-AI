"""Build a SYNTHETIC DuckDB file that follows the *documented* LMU telemetry structure.

This tests the importer logic only. It does not prove that real LMU files match: the documented
structure is third-party, see docs/TELEMETRY-FORMAT.md.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np

from .track import SCENARIOS, SyntheticTrack, frames

CHANNELS = [("GPS Time", 100, "s", "DOUBLE"), ("Ground Speed", 100, "km/h", "FLOAT"), ("Engine RPM", 100, "RPM", "FLOAT"),
            ("Steering Pos", 100, "%", "FLOAT"), ("Throttle Pos", 50, "%", "FLOAT"), ("Brake Pos", 50, "%", "FLOAT"),
            ("Lap Dist", 10, "m", "FLOAT"), ("Fuel Level", 20, "L", "FLOAT")]
EVENTS = [("Lap", "none", "USMALLINT"), ("Gear", "none", "TINYINT"), ("Lap Time", "s", "FLOAT")]


def build(path: Path, scenario: str = "constant", laps: int = 2, drop_channels: tuple[str, ...] = (),
          truncate: tuple[str, int] | None = None) -> Path:
    fr = list(frames(SyntheticTrack(), SCENARIOS[scenario], laps=laps))
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE metadata(key VARCHAR NOT NULL, value VARCHAR)")
    con.executemany("INSERT INTO metadata VALUES (?,?)", [
        ("Version", "1"), ("TrackName", "[SYNTHETIC] Test Circuit"), ("TrackLayout", "synthetic"),
        ("CarName", "[SYNTHETIC] GT #00"), ("CarClass", "SYNTH"), ("SessionType", "Practice"),
        ("DriverName", "Synthetic Driver"), ("RecordingTime", "2000-01-01T00_00_00Z")])
    con.execute("CREATE TABLE channelsList(channelName VARCHAR NOT NULL, frequency INTEGER, unit VARCHAR)")
    con.execute("CREATE TABLE eventsList(eventName VARCHAR NOT NULL, unit VARCHAR)")
    for name, hz, unit, typ in CHANNELS:
        if name in drop_channels:
            continue
        step = 100 // hz
        sel = fr[::step]
        key = {"GPS Time": lambda f: f["t"], "Ground Speed": lambda f: f["speed_ms"] * 3.6, "Engine RPM": lambda f: f["rpm"],
               "Steering Pos": lambda f: f["steer"] * 100, "Throttle Pos": lambda f: f["throttle"] * 100,
               "Brake Pos": lambda f: f["brake"] * 100, "Lap Dist": lambda f: f["lap_dist"], "Fuel Level": lambda f: f["fuel"]}[name]
        vals = [float(key(f)) for f in sel]
        if truncate and truncate[0] == name:
            vals = vals[:truncate[1]]
        con.execute(f'CREATE TABLE "{name}"(value {typ})')
        con.execute(f'INSERT INTO "{name}" SELECT unnest(?)', [vals])
        con.execute("INSERT INTO channelsList VALUES (?,?,?)", [name, hz, unit])
    laps_seen = {}
    for f in fr:
        laps_seen.setdefault(f["lap"], f["t"])
    for name, unit, typ in EVENTS:
        con.execute(f'CREATE TABLE "{name}"(ts DOUBLE, value {typ})')
        con.execute("INSERT INTO eventsList VALUES (?,?)", [name, unit])
    con.executemany('INSERT INTO "Lap" VALUES (?,?)', [(t, l) for l, t in laps_seen.items()])
    prev = None
    for f in fr:
        if f["gear"] != prev:
            con.execute('INSERT INTO "Gear" VALUES (?,?)', [f["t"], f["gear"]])
            prev = f["gear"]
    con.close()
    return path
