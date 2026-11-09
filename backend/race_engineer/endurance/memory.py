"""RaceMemory: local, append-only, provider-independent memory of a long race (SQLite WAL). Survives crash/restart."""
from __future__ import annotations

import json
import sqlite3
import threading
import time


class RaceMemory:
    def __init__(self, path, clock=time.time):
        self.clock = clock
        self._lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, wall REAL, race_s REAL, session_id TEXT, kind TEXT,
            severity INTEGER, lap INTEGER, data TEXT, dedup_key TEXT);
        CREATE TABLE IF NOT EXISTS summaries(id INTEGER PRIMARY KEY AUTOINCREMENT, wall REAL, race_s REAL, session_id TEXT, kind TEXT,
            source TEXT, text TEXT, payload TEXT, status TEXT);
        CREATE TABLE IF NOT EXISTS laps(session_id TEXT, lap INTEGER, time_s REAL, valid INTEGER, fuel_used REAL, stint INTEGER,
            tyre_max_c REAL, wear_min REAL, PRIMARY KEY(session_id, lap));
        CREATE TABLE IF NOT EXISTS stints(session_id TEXT, stint INTEGER, start_race_s REAL, end_race_s REAL, laps INTEGER,
            avg_lap_s REAL, fuel_used REAL, PRIMARY KEY(session_id, stint));
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
        """)
        self.db.commit()

    # --- generic ---------------------------------------------------------
    def put_meta(self, key, value):
        with self._lock:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, json.dumps(value)))
            self.db.commit()

    def get_meta(self, key, default=None):
        with self._lock:
            r = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(r[0]) if r else default

    def add_event(self, session_id, race_s, kind, severity, lap, data, dedup_key=None) -> int:
        with self._lock:
            cur = self.db.execute("INSERT INTO events(wall,race_s,session_id,kind,severity,lap,data,dedup_key) VALUES (?,?,?,?,?,?,?,?)",
                                  (self.clock(), race_s, session_id, kind, int(severity), lap, json.dumps(data), dedup_key))
            self.db.commit()
            return cur.lastrowid

    def events_since(self, session_id, since_id: int = 0, min_severity: int = 99, limit: int = 200) -> list[dict]:
        with self._lock:
            rows = self.db.execute("SELECT id,race_s,kind,severity,lap,data FROM events WHERE session_id=? AND id>? AND severity<=? ORDER BY id LIMIT ?",
                                   (session_id, since_id, min_severity, limit)).fetchall()
        return [{"id": r[0], "race_s": r[1], "kind": r[2], "severity": r[3], "lap": r[4], "data": json.loads(r[5])} for r in rows]

    def add_lap(self, session_id, lap, time_s, valid, fuel_used, stint, tyre_max_c, wear_min):
        with self._lock:
            self.db.execute("INSERT OR REPLACE INTO laps VALUES (?,?,?,?,?,?,?,?)", (session_id, lap, time_s, int(valid), fuel_used, stint, tyre_max_c, wear_min))
            self.db.commit()

    def recent_laps(self, session_id, n=8) -> list[dict]:
        with self._lock:
            rows = self.db.execute("SELECT lap,time_s,valid,fuel_used,stint,tyre_max_c,wear_min FROM laps WHERE session_id=? ORDER BY lap DESC LIMIT ?",
                                   (session_id, n)).fetchall()
        return [dict(zip(("lap", "time_s", "valid", "fuel_used", "stint", "tyre_max_c", "wear_min"), r)) for r in reversed(rows)]

    def lap_count(self, session_id) -> int:
        with self._lock:
            return self.db.execute("SELECT COUNT(*) FROM laps WHERE session_id=?", (session_id,)).fetchone()[0]

    def best_lap(self, session_id) -> float | None:
        with self._lock:
            r = self.db.execute("SELECT MIN(time_s) FROM laps WHERE session_id=? AND valid=1", (session_id,)).fetchone()
        return r[0]

    def add_stint(self, session_id, stint, start, end, laps, avg_lap, fuel_used):
        with self._lock:
            self.db.execute("INSERT OR REPLACE INTO stints VALUES (?,?,?,?,?,?,?)", (session_id, stint, start, end, laps, avg_lap, fuel_used))
            self.db.commit()

    def stints(self, session_id) -> list[dict]:
        with self._lock:
            rows = self.db.execute("SELECT stint,start_race_s,end_race_s,laps,avg_lap_s,fuel_used FROM stints WHERE session_id=? ORDER BY stint", (session_id,)).fetchall()
        return [dict(zip(("stint", "start_race_s", "end_race_s", "laps", "avg_lap_s", "fuel_used"), r)) for r in rows]

    def add_summary(self, session_id, race_s, kind, source, text, payload, status="ok"):
        with self._lock:
            self.db.execute("INSERT INTO summaries(wall,race_s,session_id,kind,source,text,payload,status) VALUES (?,?,?,?,?,?,?,?)",
                            (self.clock(), race_s, session_id, kind, source, text, json.dumps(payload), status))
            self.db.commit()

    def summaries(self, session_id=None, kind=None, limit=100) -> list[dict]:
        q, a = "SELECT wall,race_s,kind,source,text,status FROM summaries WHERE 1=1", []
        if session_id:
            q += " AND session_id=?"; a.append(session_id)
        if kind:
            q += " AND kind=?"; a.append(kind)
        with self._lock:
            rows = self.db.execute(q + " ORDER BY id DESC LIMIT ?", (*a, limit)).fetchall()
        return [dict(zip(("wall", "race_s", "kind", "source", "text", "status"), r)) for r in rows]

    def counts(self) -> dict:
        with self._lock:
            return {t: self.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("events", "summaries", "laps", "stints")}

    def close(self):
        with self._lock:
            self.db.close()
