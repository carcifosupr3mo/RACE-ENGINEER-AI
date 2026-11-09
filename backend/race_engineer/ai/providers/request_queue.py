"""AIRequestQueue: persistent, prioritised, de-duplicated queue. Survives crashes/restarts; never sends stale requests.

Statuses: pending | sending | done | dropped_stale | dropped_dup | dropped_overflow | superseded
* dedup: a request whose ``dedup_key`` is already pending SUPERSEDES it (newest data wins, best priority kept); a key that
  completed less than ``cooldown_s`` ago is dropped (no repeated calls about the same event).
* TTL: a request older than ``ttl_s`` is dropped without being sent, also right after an internet outage ends.
* overflow: at most ``max_pending`` rows; the oldest LOW/NORMAL are dropped first.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Callable

from .manager import AIProviderManager
from .types import AIRequest, AIResponse, AllProvidersUnavailable, Priority


class AIRequestQueue:
    def __init__(self, db_path, manager: AIProviderManager, *, cooldown_s: dict[str, float] | None = None,
                 max_pending: int = 200, max_calls_per_hour: int = 120, clock: Callable[[], float] = time.time,
                 on_result: Callable[[AIRequest, AIResponse], None] | None = None):
        self.manager, self.clock, self.on_result = manager, clock, on_result
        self.cooldown_s = {"periodic_summary": 240.0, "event": 60.0, "pit_stop": 120.0, "stint_end": 120.0, **(cooldown_s or {})}
        self.max_pending, self.max_calls_per_hour = max_pending, max_calls_per_hour
        self._lock = threading.RLock()
        self.db = sqlite3.connect(str(db_path), check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS requests(
            id TEXT PRIMARY KEY, kind TEXT, priority INTEGER, system TEXT, user TEXT, created REAL, ttl_s REAL, dedup_key TEXT,
            max_tokens INTEGER, session_id TEXT, status TEXT, attempts INTEGER DEFAULT 0, finished REAL, result_json TEXT, error TEXT)""")
        self.db.execute("CREATE INDEX IF NOT EXISTS ix_q ON requests(status, priority, created)")
        self.db.commit()
        self.counters = {"submitted": 0, "dropped_dup": 0, "superseded": 0, "dropped_stale": 0, "dropped_overflow": 0,
                         "done": 0, "retried": 0, "rate_capped": 0}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.recover()

    # ------------------------------------------------------------------ persistence / recovery
    def recover(self) -> dict:
        """After a crash/restart: requests that were 'sending' go back to pending; stale ones are dropped."""
        with self._lock:
            self.db.execute("UPDATE requests SET status='pending' WHERE status='sending'")
            n = self._drop_stale()
            self.db.commit()
            p = self.db.execute("SELECT COUNT(*) FROM requests WHERE status='pending'").fetchone()[0]
        return {"pending": p, "dropped_stale": n}

    def _drop_stale(self) -> int:
        now = self.clock()
        cur = self.db.execute("UPDATE requests SET status='dropped_stale', finished=? WHERE status='pending' AND ? - created > ttl_s", (now, now))
        self.counters["dropped_stale"] += cur.rowcount
        return cur.rowcount

    # ------------------------------------------------------------------ submit
    def submit(self, req: AIRequest) -> str | None:
        with self._lock:
            now = self.clock()
            req.created = now                  # the queue owns time (injectable clock)
            self.counters["submitted"] += 1
            if req.dedup_key:
                row = self.db.execute("SELECT id, priority FROM requests WHERE status='pending' AND dedup_key=?", (req.dedup_key,)).fetchone()
                if row:
                    self.db.execute("UPDATE requests SET user=?, system=?, created=?, priority=?, ttl_s=? WHERE id=?",
                                    (req.user, req.system, req.created, min(row[1], int(req.priority)), req.ttl_s, row[0]))
                    self.db.commit()
                    self.counters["superseded"] += 1
                    return row[0]
                cd = self.cooldown_s.get(req.kind, 0.0)
                if cd and req.priority > Priority.CRITICAL:
                    recent = self.db.execute("SELECT 1 FROM requests WHERE dedup_key=? AND status IN ('done','sending') AND finished>?",
                                             (req.dedup_key, now - cd)).fetchone()
                    if recent:
                        self.counters["dropped_dup"] += 1
                        return None
            self.db.execute("INSERT INTO requests(id,kind,priority,system,user,created,ttl_s,dedup_key,max_tokens,session_id,status) "
                            "VALUES (?,?,?,?,?,?,?,?,?,?,'pending')",
                            (req.id, req.kind, int(req.priority), req.system, req.user, req.created, req.ttl_s, req.dedup_key, req.max_tokens, req.session_id))
            over = self.db.execute("SELECT COUNT(*) FROM requests WHERE status='pending'").fetchone()[0] - self.max_pending
            if over > 0:
                cur = self.db.execute("UPDATE requests SET status='dropped_overflow', finished=? WHERE id IN ("
                                      "SELECT id FROM requests WHERE status='pending' ORDER BY priority DESC, created ASC LIMIT ?)", (now, over))
                self.counters["dropped_overflow"] += cur.rowcount
            self.db.commit()
            return req.id

    # ------------------------------------------------------------------ processing
    def _next(self) -> AIRequest | None:
        self._drop_stale()
        r = self.db.execute("SELECT id,kind,priority,system,user,created,ttl_s,dedup_key,max_tokens,session_id FROM requests "
                            "WHERE status='pending' ORDER BY priority, created LIMIT 1").fetchone()
        if not r:
            return None
        return AIRequest(kind=r[1], priority=Priority(r[2]), system=r[3], user=r[4], created=r[5], ttl_s=r[6], dedup_key=r[7],
                         max_tokens=r[8], session_id=r[9], id=r[0])

    def _calls_last_hour(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM requests WHERE status='done' AND finished>?", (self.clock() - 3600,)).fetchone()[0]

    def pump(self) -> str:
        """Process at most one request. Returns 'idle' | 'done' | 'waiting' | 'rate_capped'. Deterministic: used by tests/simulation."""
        with self._lock:
            req = self._next()
            if req is None:
                self.db.commit()
                return "idle"
            if self._calls_last_hour() >= self.max_calls_per_hour and req.priority > Priority.CRITICAL:
                self.counters["rate_capped"] += 1
                return "rate_capped"
            self.db.execute("UPDATE requests SET status='sending', attempts=attempts+1 WHERE id=?", (req.id,))
            self.db.commit()
        try:
            resp = self.manager.complete(req)
        except AllProvidersUnavailable as e:
            with self._lock:
                self.db.execute("UPDATE requests SET status='pending', error=? WHERE id=?", (str(e)[:300], req.id))
                self.db.commit()
                self.counters["retried"] += 1
            return "waiting"
        with self._lock:
            self.db.execute("UPDATE requests SET status='done', finished=?, result_json=? WHERE id=?",
                            (self.clock(), json.dumps({"text": resp.text, "provider": resp.provider, "model": resp.model,
                                                       "tokens": resp.tokens_in + resp.tokens_out, "depth": resp.fallback_depth}), req.id))
            self.db.commit()
            self.counters["done"] += 1
        if self.on_result:
            try:
                self.on_result(req, resp)
            except Exception:
                pass
        return "done"

    def pending(self) -> int:
        with self._lock:
            return self.db.execute("SELECT COUNT(*) FROM requests WHERE status='pending'").fetchone()[0]

    def status_counts(self) -> dict:
        with self._lock:
            return dict(self.db.execute("SELECT status, COUNT(*) FROM requests GROUP BY status").fetchall())

    def results(self, kind: str | None = None, limit: int = 50) -> list[dict]:
        with self._lock:
            q = "SELECT id,kind,created,finished,result_json FROM requests WHERE status='done'" + (" AND kind=?" if kind else "") + " ORDER BY finished DESC LIMIT ?"
            rows = self.db.execute(q, (kind, limit) if kind else (limit,)).fetchall()
        return [{"id": r[0], "kind": r[1], "created": r[2], "finished": r[3], **json.loads(r[4])} for r in rows]

    # ------------------------------------------------------------------ worker thread (production)
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def loop():
            while not self._stop.is_set():
                st = self.pump()
                if st == "done":
                    continue
                wait = 2.0 if st == "idle" else max(2.0, min(60.0, self.manager.next_ready_in()))
                self._stop.wait(wait)
        self._thread = threading.Thread(target=loop, name="ai-queue", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(5)
