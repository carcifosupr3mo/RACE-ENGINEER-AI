"""Read-only importer/inspector for LMU's native DuckDB telemetry files (UserData/Telemetry/*.duckdb).

SCHEMA STATUS: the structure used here (metadata / channelsList / eventsList + one table per channel,
fixed-frequency tables without timestamps, event tables with ``ts``) comes from PUBLIC THIRD-PARTY
DOCUMENTATION of real LMU files (see docs/TELEMETRY-FORMAT.md). It could not be checked against a real
file here. The reader therefore discovers everything from the file itself and reports deviations
instead of assuming them.

The original file is only ever opened with ``read_only=True``; callers can additionally pass
``copy_first=True`` to work on a scratch copy (protects against a file still held by the game).
"""
from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import numpy as np

from ..model.provenance import Provenance

CATALOG_TABLES = {"metadata", "channelsList", "eventsList"}
# channels needed for lap analysis (Phase 3); absence is reported, never invented
CORE_CHANNELS = ["Ground Speed", "Throttle Pos", "Brake Pos", "Steering Pos", "Engine RPM", "Lap Dist", "GPS Time"]
CORE_EVENTS = ["Lap", "Gear", "Lap Time"]


def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


@dataclass
class DuckdbInspection:
    path: str
    ok: bool = True
    problems: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    channels: list[dict] = field(default_factory=list)   # name, frequency, unit, columns, rows, duration_s
    events: list[dict] = field(default_factory=list)     # name, unit, columns, rows
    missing_core_channels: list[str] = field(default_factory=list)
    missing_core_events: list[str] = field(default_factory=list)
    undeclared_tables: list[str] = field(default_factory=list)
    duration_inconsistency: list[str] = field(default_factory=list)
    provenance: str = Provenance.DUCKDB_IMPORT.value


class LmuDuckdb:
    def __init__(self, path: str | Path, copy_first: bool = False):
        self.original = Path(path)
        self._tmp: Path | None = None
        src = self.original
        if copy_first:
            self._tmp = Path(tempfile.mkdtemp(prefix="re_ai_duck_")) / src.name
            shutil.copy2(src, self._tmp)
            src = self._tmp
        self.con = duckdb.connect(str(src), read_only=True)

    def close(self) -> None:
        self.con.close()
        if self._tmp:
            shutil.rmtree(self._tmp.parent, ignore_errors=True)

    def __enter__(self): return self
    def __exit__(self, *a): self.close()

    def tables(self) -> dict[str, list[tuple[str, str]]]:
        rows = self.con.execute(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_schema='main' ORDER BY table_name, ordinal_position").fetchall()
        out: dict[str, list[tuple[str, str]]] = {}
        for t, c, d in rows:
            out.setdefault(t, []).append((c, d))
        return out

    def inspect(self) -> DuckdbInspection:
        r = DuckdbInspection(str(self.original))
        tabs = self.tables()
        for t in CATALOG_TABLES:
            if t not in tabs:
                r.ok = False
                r.problems.append(f"catalog table '{t}' missing: file does not match the documented LMU layout")
        if "metadata" in tabs:
            r.metadata = {k: v for k, v in self.con.execute("SELECT key, value FROM metadata").fetchall()}
        declared: set[str] = set()
        if "channelsList" in tabs:
            for name, freq, unit in self.con.execute("SELECT channelName, frequency, unit FROM channelsList ORDER BY 1").fetchall():
                declared.add(name)
                info = {"name": name, "frequency": freq, "unit": unit, "columns": [c for c, _ in tabs.get(name, [])],
                        "rows": None, "duration_s": None, "present": name in tabs}
                if name in tabs:
                    info["rows"] = self.con.execute(f"SELECT COUNT(*) FROM {q(name)}").fetchone()[0]
                    if freq:
                        info["duration_s"] = round(info["rows"] / freq, 3)
                else:
                    r.problems.append(f"channel '{name}' declared in channelsList but table is missing")
                r.channels.append(info)
        if "eventsList" in tabs:
            for name, unit in self.con.execute("SELECT eventName, unit FROM eventsList ORDER BY 1").fetchall():
                declared.add(name)
                info = {"name": name, "unit": unit, "columns": [c for c, _ in tabs.get(name, [])], "rows": None,
                        "present": name in tabs}
                if name in tabs:
                    info["rows"] = self.con.execute(f"SELECT COUNT(*) FROM {q(name)}").fetchone()[0]
                r.events.append(info)
        r.undeclared_tables = sorted(set(tabs) - declared - CATALOG_TABLES)
        have_ch = {c["name"] for c in r.channels if c["present"]}
        have_ev = {e["name"] for e in r.events if e["present"]}
        r.missing_core_channels = [c for c in CORE_CHANNELS if c not in have_ch]
        r.missing_core_events = [e for e in CORE_EVENTS if e not in have_ev]
        durs = [c["duration_s"] for c in r.channels if c["duration_s"] and c["frequency"] and c["frequency"] >= 10]
        if durs:
            med = float(np.median(durs))
            r.duration_inconsistency = [f"{c['name']}: {c['duration_s']}s vs median {med:.1f}s" for c in r.channels
                                        if c["duration_s"] and c["frequency"] and c["frequency"] >= 10
                                        and abs(c["duration_s"] - med) > max(1.0, 0.02 * med)]
        if r.missing_core_channels or r.missing_core_events:
            r.problems.append("core channels missing: " + ", ".join(r.missing_core_channels + r.missing_core_events))
        return r

    def read_channel(self, name: str) -> dict:
        """Fixed-frequency channel -> values + RECONSTRUCTED relative time (index / frequency).

        The absolute start offset is NOT known from the channel table alone (see docs); callers needing
        absolute time must align through the master timeline channel and event ``ts`` values.
        """
        freq = self.con.execute("SELECT frequency, unit FROM channelsList WHERE channelName = ?", [name]).fetchone()
        if not freq:
            raise KeyError(f"{name!r} is not a declared fixed-frequency channel")
        cols = [c for c, _ in self.tables()[name]]
        arr = np.array(self.con.execute(f"SELECT {', '.join(q(c) for c in cols)} FROM {q(name)}").fetchall(), dtype=float)
        # NOTE: relies on DuckDB's insertion-order preservation for tables (documented DuckDB behaviour).
        t = np.arange(len(arr)) / freq[0] if freq[0] else None
        return {"name": name, "unit": freq[1], "frequency": freq[0], "columns": cols, "values": arr, "t_rel_s": t,
                "provenance": Provenance.DUCKDB_IMPORT.value}

    def read_events(self, name: str) -> dict:
        cols = [c for c, _ in self.tables()[name]]
        rows = self.con.execute(f"SELECT {', '.join(q(c) for c in cols)} FROM {q(name)} ORDER BY ts").fetchall()
        return {"name": name, "columns": cols, "rows": rows, "provenance": Provenance.DUCKDB_IMPORT.value}
