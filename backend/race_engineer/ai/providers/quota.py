"""AIQuotaManager: local accounting of free-tier limits, persisted in SQLite (survives restarts).

Limits are CONFIG (defaults = what the providers' docs said on 2026-11-09 for the free plan; NVIDIA's are
unverified/conservative). Provider response headers can only tighten them. ``can_send`` is checked BEFORE a request so
that free quota is not burnt on calls that would be rejected, and no paid request can result from exceeding it.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass


@dataclass
class Limits:
    rpm: int | None = None
    rpd: int | None = None
    tpm: int | None = None
    tpd: int | None = None
    reserve: float = 0.8        # use at most 80% of any limit: head-room for clock skew and other clients on the same key


DEFAULT_LIMITS = {
    "groq": Limits(rpm=30, rpd=1000, tpm=8000, tpd=200_000),           # Groq docs, free plan, 2026-11-09
    "nvidia": Limits(rpm=30, rpd=None, tpm=None, tpd=None),             # UNVERIFIED: conservative; NVIDIA trial credits/limits vary per account
}


class AIQuotaManager:
    def __init__(self, db_path, limits: dict[tuple[str, str], Limits] | None = None, clock=time.time):
        self.clock = clock
        self.limits = limits or {}
        self._lock = threading.Lock()
        self.db = sqlite3.connect(str(db_path), check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS usage(ts REAL NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL, tokens INTEGER NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS blocks(provider TEXT NOT NULL, model TEXT NOT NULL, until REAL NOT NULL, reason TEXT, PRIMARY KEY(provider, model))")
        self.db.execute("CREATE INDEX IF NOT EXISTS ix_usage ON usage(provider, model, ts)")
        self.db.commit()

    def limits_for(self, provider: str, model: str) -> Limits:
        return self.limits.get((provider, model)) or DEFAULT_LIMITS.get(provider) or Limits()

    def _sum(self, provider, model, window_s):
        r = self.db.execute("SELECT COUNT(*), COALESCE(SUM(tokens),0) FROM usage WHERE provider=? AND model=? AND ts>?",
                            (provider, model, self.clock() - window_s)).fetchone()
        return r[0], r[1]

    def usage(self, provider, model) -> dict:
        with self._lock:
            rm, tm = self._sum(provider, model, 60)
            rd, td = self._sum(provider, model, 86400)
        return {"rpm": rm, "tpm": tm, "rpd": rd, "tpd": td, "limits": vars(self.limits_for(provider, model))}

    def blocked_until(self, provider, model) -> float:
        with self._lock:
            r = self.db.execute("SELECT until FROM blocks WHERE provider=? AND model=?", (provider, model)).fetchone()
        return r[0] if r and r[0] > self.clock() else 0.0

    def block(self, provider, model, seconds: float, reason: str) -> None:
        with self._lock:
            self.db.execute("INSERT OR REPLACE INTO blocks VALUES (?,?,?,?)", (provider, model, self.clock() + seconds, reason))
            self.db.commit()

    def clear_block(self, provider, model) -> None:
        with self._lock:
            self.db.execute("DELETE FROM blocks WHERE provider=? AND model=?", (provider, model))
            self.db.commit()

    def can_send(self, provider, model, est_tokens: int) -> tuple[bool, str, float]:
        """-> (ok, reason, seconds_until_retry)."""
        if (b := self.blocked_until(provider, model)):
            return False, "blocked", b - self.clock()
        lim = self.limits_for(provider, model)
        with self._lock:
            rm, tm = self._sum(provider, model, 60)
            rd, td = self._sum(provider, model, 86400)
        f = lim.reserve
        if lim.rpm and rm + 1 > lim.rpm * f:
            return False, "rpm", 60.0 / max(1, lim.rpm)
        if lim.tpm and tm + est_tokens > lim.tpm * f:
            return False, "tpm", 30.0
        if lim.rpd and rd + 1 > lim.rpd * f:
            return False, "rpd", 3600.0
        if lim.tpd and td + est_tokens > lim.tpd * f:
            return False, "tpd", 3600.0
        return True, "", 0.0

    def record(self, provider, model, tokens: int) -> None:
        with self._lock:
            self.db.execute("INSERT INTO usage VALUES (?,?,?,?)", (self.clock(), provider, model, int(tokens)))
            self.db.execute("DELETE FROM usage WHERE ts < ?", (self.clock() - 90000,))
            self.db.commit()

    def note_headers(self, provider, model, headers: dict) -> None:
        """Groq sends remaining-request/token headers: if the provider says we are out, believe it over our own count."""
        try:
            rr = headers.get("x-ratelimit-remaining-requests")
            rt = headers.get("x-ratelimit-remaining-tokens")
            if rr is not None and float(rr) <= 0:
                self.block(provider, model, 600.0, "provider reports 0 requests remaining")
            elif rt is not None and float(rt) < 200:
                self.block(provider, model, 30.0, "provider reports tokens nearly exhausted")
        except ValueError:
            pass

    def close(self):
        self.db.close()
