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
    (5, """
    CREATE TABLE coach_tips (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL NOT NULL, session_id TEXT,
        track TEXT NOT NULL, vehicle TEXT NOT NULL DEFAULT '', synthetic INTEGER NOT NULL DEFAULT 0,
        corner TEXT NOT NULL, type TEXT NOT NULL, key TEXT NOT NULL,          -- key = '<corner>.<type>'
        lap_issued INTEGER, confidence TEXT, impact_before_s REAL, mag_before REAL,
        instruction_json TEXT NOT NULL,
        status TEXT NOT NULL,            -- nuovo | mostrato | applicato | da_rivalutare | non_verificabile
        shown_at REAL, shown_lap INTEGER, evaluated_lap INTEGER,
        outcome TEXT,                    -- seguito_migliorato | seguito_non_efficace | parziale | non_seguito | peggiorato | non_confrontabile | corretto
        impact_after_s REAL, evaluations INTEGER NOT NULL DEFAULT 0, skipped INTEGER NOT NULL DEFAULT 0, closed_at REAL
    );
    CREATE INDEX idx_coach_tips ON coach_tips(track, vehicle, synthetic, key, status);
    CREATE TABLE coach_habits (
        track TEXT NOT NULL, vehicle TEXT NOT NULL DEFAULT '', synthetic INTEGER NOT NULL DEFAULT 0,
        corner TEXT NOT NULL, type TEXT NOT NULL,
        laps_seen INTEGER NOT NULL DEFAULT 0, total_impact_s REAL NOT NULL DEFAULT 0,
        first_seen REAL, last_seen REAL, last_session_id TEXT, sessions INTEGER NOT NULL DEFAULT 0, fixed_at REAL,
        PRIMARY KEY (track, vehicle, synthetic, corner, type)
    );
    CREATE TABLE coach_laps (
        session_id TEXT NOT NULL, lap INTEGER NOT NULL, track TEXT NOT NULL, vehicle TEXT NOT NULL DEFAULT '', synthetic INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL, time_s REAL, delta_best_s REAL, findings INTEGER, review_json TEXT,
        PRIMARY KEY (session_id, lap)
    );
    """),
    (6, """
    -- every session belongs to ONE simulator; everything recorded so far came from Le Mans Ultimate ('lmu')
    ALTER TABLE sessions ADD COLUMN sim TEXT NOT NULL DEFAULT 'lmu';
    CREATE INDEX idx_sessions_sim ON sessions(sim, started_at);
    ALTER TABLE goals ADD COLUMN sim TEXT NOT NULL DEFAULT 'lmu';
    """),
    (7, """
    -- every per-simulator memory carries its simulator (existing rows = Le Mans Ultimate). Columns only: no row is rewritten or removed.
    -- NOTE: the primary keys of coach_habits / track_profiles do not contain `sim` yet; they must be rebuilt (with a backup) in the
    -- migration that enables a SECOND simulator, together with scoping the Coach queries (see docs/SIMULATORS.md, "Architettura").
    ALTER TABLE coach_tips ADD COLUMN sim TEXT NOT NULL DEFAULT 'lmu';
    ALTER TABLE coach_habits ADD COLUMN sim TEXT NOT NULL DEFAULT 'lmu';
    ALTER TABLE coach_laps ADD COLUMN sim TEXT NOT NULL DEFAULT 'lmu';
    ALTER TABLE setups ADD COLUMN sim TEXT NOT NULL DEFAULT 'lmu';
    ALTER TABLE track_profiles ADD COLUMN sim TEXT NOT NULL DEFAULT 'lmu';
    ALTER TABLE messages ADD COLUMN sim TEXT NOT NULL DEFAULT 'lmu';
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
        if 0 < cur < MIGRATIONS[-1][0]:
            # an update that changes the schema first keeps a copy of the catalog (never overwritten, only added)
            bak = self.path.with_name(f"{self.path.name}.before-v{MIGRATIONS[-1][0]}.bak")
            if not bak.exists():
                try:
                    self.backup(bak)
                except (OSError, sqlite3.Error):
                    pass
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

    def create_session(self, *, source: str, is_synthetic: bool, data_path: str, ctx, sim: str = "lmu") -> str:
        sid = uuid.uuid4().hex
        with self.db:
            self.db.execute(
                "INSERT INTO sessions(id,started_at,source,is_synthetic,status,track,vehicle,vehicle_class,session_type,"
                "session_code,game_version,track_length_m,data_path,sim) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (sid, time.time(), source, int(is_synthetic), "recording", ctx.track_name, ctx.vehicle_name,
                 ctx.vehicle_class, ctx.session_type, ctx.session_code, ctx.game_version, ctx.track_length_m, data_path, sim))
        return sid

    def update_counts(self, sid: str, samples: int, lost: int) -> None:
        with self.db:
            self.db.execute("UPDATE sessions SET samples=?, samples_lost=? WHERE id=?", (samples, lost, sid))

    def finish_session(self, sid: str, samples: int, lost: int, complete: bool) -> None:
        with self.db:
            self.db.execute("UPDATE sessions SET ended_at=?, status=?, samples=?, samples_lost=? WHERE id=?",
                            (time.time(), "complete" if complete else "incomplete", samples, lost, sid))

    def list_sessions(self, include_synthetic: bool = True, sim: str | None = None) -> list[dict]:
        """``sim`` limits the list to one simulator (sessions of different games are never mixed)."""
        where, args = [], []
        if not include_synthetic:
            where.append("is_synthetic=0")
        if sim:
            where.append("sim=?"); args.append(sim)
        q = "SELECT * FROM sessions" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY started_at DESC"
        return [dict(r) for r in self.db.execute(q, args)]

    def get_track_profile(self, track: str, layout: str = "") -> list[dict] | None:
        import json
        r = self.db.execute("SELECT corners_json FROM track_profiles WHERE track=? AND layout=?", (track, layout)).fetchone()
        corners = json.loads(r[0]) if r else None
        return corners or None        # an EMPTY saved profile (older versions allowed saving one) counts as "no profile": detection stays in charge

    def put_track_profile(self, track: str, corners: list[dict], layout: str = "") -> None:
        import json
        with self.db:
            self.db.execute("INSERT INTO track_profiles(track,layout,corners_json,updated_at) VALUES (?,?,?,?) ON CONFLICT(track,layout) DO UPDATE SET "
                            "corners_json=excluded.corners_json, updated_at=excluded.updated_at",
                            (track, layout, json.dumps(corners), time.time()))

    def get_session(self, sid: str) -> dict | None:
        r = self.db.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
        return dict(r) if r else None

    # --- goals / messages / settings / setups -------------------------------------------------
    def add_goal(self, track, vehicle, metric, target, baseline=None, note=None, sim: str = "lmu") -> int:
        with self.db:
            cur = self.db.execute("INSERT INTO goals(created_at,track,vehicle,metric,target,baseline,note,sim) VALUES (?,?,?,?,?,?,?,?)",
                                  (time.time(), track, vehicle, metric, target, baseline, note, sim))
        return cur.lastrowid

    def list_goals(self, sim: str | None = None) -> list[dict]:
        if sim:
            return [dict(r) for r in self.db.execute("SELECT * FROM goals WHERE sim=? ORDER BY id DESC", (sim,))]
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

    # Per-simulator settings live under their own key prefix, so one game's configuration can never overwrite another's.
    def get_sim_setting(self, sim: str, key: str, default=None):
        return self.get_setting(f"sim.{sim}.{key}", default)

    def put_sim_setting(self, sim: str, key: str, value) -> None:
        self.put_setting(f"sim.{sim}.{key}", value)

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
