"""SQLite catalog: metadata of sessions (never telemetry samples), versioned migrations, backup."""
from __future__ import annotations

import sqlite3
import time
import uuid
from pathlib import Path

MIGRATIONS: list[tuple[int, str]] = [
    (1, """
    CREATE TABLE sessions (
        id TEXT PRIMARY KEY,
        started_at REAL NOT NULL,
        ended_at REAL,
        source TEXT NOT NULL,                 -- lmu_shm | duckdb_import | synthetic
        is_synthetic INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL,                 -- recording | complete | incomplete
        track TEXT, vehicle TEXT, vehicle_class TEXT, session_type TEXT, session_code INTEGER,
        game_version INTEGER, track_length_m REAL,
        samples INTEGER NOT NULL DEFAULT 0,
        samples_lost INTEGER NOT NULL DEFAULT 0,
        data_path TEXT NOT NULL,              -- derived DuckDB file with our samples
        original_path TEXT                    -- LMU original (never modified), if imported
    );
    CREATE INDEX idx_sessions_started ON sessions(started_at);
    """),
    (2, """
    CREATE TABLE track_profiles (
        track TEXT NOT NULL, layout TEXT NOT NULL DEFAULT '',
        corners_json TEXT NOT NULL,           -- user-confirmed corner map (manual editor)
        updated_at REAL NOT NULL,
        PRIMARY KEY (track, layout)
    );
    """),
    (3, """
    CREATE TABLE goals (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL NOT NULL,
        track TEXT NOT NULL, vehicle TEXT NOT NULL DEFAULT '',
        metric TEXT NOT NULL,            -- best_lap_s | lap_std_s | slow_corner_loss_s
        target REAL NOT NULL, baseline REAL, note TEXT, status TEXT NOT NULL DEFAULT 'active'
    );
    CREATE TABLE messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT, conversation TEXT NOT NULL, created_at REAL NOT NULL,
        role TEXT NOT NULL, session_id TEXT, content_json TEXT NOT NULL
    );
    CREATE INDEX idx_messages_conv ON messages(conversation, created_at);
    CREATE TABLE settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
    CREATE TABLE setups (
        id TEXT PRIMARY KEY, imported_at REAL NOT NULL, session_id TEXT, source TEXT NOT NULL,
        original_path TEXT, name TEXT, raw_json TEXT NOT NULL      -- verbatim copy; originals are never modified
    );
    """),
    (4, """
    ALTER TABLE setups ADD COLUMN raw_text TEXT;     -- byte-faithful text of the original setup file (when it came from a file)
    ALTER TABLE setups ADD COLUMN sha256 TEXT;
    ALTER TABLE setups ADD COLUMN fmt TEXT;          -- json | svm | other
    """),
]


class Catalog:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.migrate()
        self.recover_incomplete()

    def schema_version(self) -> int:
        self.db.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at REAL)")
        row = self.db.execute("SELECT MAX(version) v FROM schema_migrations").fetchone()
        return row["v"] or 0

    def migrate(self) -> int:
        cur = self.schema_version()
        for ver, sql in MIGRATIONS:
            if ver > cur:
                with self.db:  # one transaction per migration
                    self.db.executescript("BEGIN;" + sql)
                    self.db.execute("INSERT INTO schema_migrations VALUES (?,?)", (ver, time.time()))
        return self.schema_version()

    def recover_incomplete(self) -> int:
        """Sessions left in 'recording' by a crash are kept and flagged 'incomplete' (data never deleted)."""
        with self.db:
            cur = self.db.execute("UPDATE sessions SET status='incomplete' WHERE status='recording'")
        return cur.rowcount

    def create_session(self, *, source: str, is_synthetic: bool, data_path: str, ctx) -> str:
        sid = uuid.uuid4().hex
        with self.db:
            self.db.execute(
                "INSERT INTO sessions(id,started_at,source,is_synthetic,status,track,vehicle,vehicle_class,session_type,"
                "session_code,game_version,track_length_m,data_path) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (sid, time.time(), source, int(is_synthetic), "recording", ctx.track_name, ctx.vehicle_name,
                 ctx.vehicle_class, ctx.session_type, ctx.session_code, ctx.game_version, ctx.track_length_m, data_path))
        return sid

    def update_counts(self, sid: str, samples: int, lost: int) -> None:
        with self.db:
            self.db.execute("UPDATE sessions SET samples=?, samples_lost=? WHERE id=?", (samples, lost, sid))

    def finish_session(self, sid: str, samples: int, lost: int, complete: bool) -> None:
        with self.db:
            self.db.execute("UPDATE sessions SET ended_at=?, status=?, samples=?, samples_lost=? WHERE id=?",
                            (time.time(), "complete" if complete else "incomplete", samples, lost, sid))

    def list_sessions(self, include_synthetic: bool = True) -> list[dict]:
        q = "SELECT * FROM sessions" + ("" if include_synthetic else " WHERE is_synthetic=0") + " ORDER BY started_at DESC"
        return [dict(r) for r in self.db.execute(q)]

    def get_track_profile(self, track: str, layout: str = "") -> list[dict] | None:
        import json
        r = self.db.execute("SELECT corners_json FROM track_profiles WHERE track=? AND layout=?", (track, layout)).fetchone()
        return json.loads(r[0]) if r else None

    def put_track_profile(self, track: str, corners: list[dict], layout: str = "") -> None:
        import json
        with self.db:
            self.db.execute("INSERT INTO track_profiles VALUES (?,?,?,?) ON CONFLICT(track,layout) DO UPDATE SET "
                            "corners_json=excluded.corners_json, updated_at=excluded.updated_at",
                            (track, layout, json.dumps(corners), time.time()))

    def get_session(self, sid: str) -> dict | None:
        r = self.db.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
        return dict(r) if r else None

    # --- goals / messages / settings / setups -------------------------------------------------
    def add_goal(self, track, vehicle, metric, target, baseline=None, note=None) -> int:
        with self.db:
            cur = self.db.execute("INSERT INTO goals(created_at,track,vehicle,metric,target,baseline,note) VALUES (?,?,?,?,?,?,?)",
                                  (time.time(), track, vehicle, metric, target, baseline, note))
        return cur.lastrowid

    def list_goals(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM goals ORDER BY id DESC")]

    def set_goal_status(self, gid: int, status: str) -> None:
        with self.db:
            self.db.execute("UPDATE goals SET status=? WHERE id=?", (status, gid))

    def add_message(self, conversation: str, role: str, content: dict, session_id: str | None = None) -> None:
        import json
        with self.db:
            self.db.execute("INSERT INTO messages(conversation,created_at,role,session_id,content_json) VALUES (?,?,?,?,?)",
                            (conversation, time.time(), role, session_id, json.dumps(content)))

    def list_messages(self, conversation: str) -> list[dict]:
        import json
        return [{**dict(r), "content": json.loads(r["content_json"])} for r in
                self.db.execute("SELECT * FROM messages WHERE conversation=? ORDER BY id", (conversation,))]

    def get_setting(self, key: str, default=None):
        import json
        r = self.db.execute("SELECT value_json FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(r[0]) if r else default

    def put_setting(self, key: str, value) -> None:
        import json
        with self.db:
            self.db.execute("INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json", (key, json.dumps(value)))

    def integrity_ok(self) -> bool:
        return self.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

    def backup(self, dest: Path | str) -> Path:
        dest = Path(dest)
        out = sqlite3.connect(dest)
        with out:
            self.db.backup(out)
        out.close()
        return dest

    def close(self) -> None:
        self.db.close()
