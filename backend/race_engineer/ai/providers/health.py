"""AIHealthMonitor: per-route circuit breaker with exponential back-off and recovery probes."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class RouteHealth:
    state: str = "unknown"          # unknown | ok | degraded | down
    consecutive_failures: int = 0
    open_until: float = 0.0
    last_error: str | None = None
    last_ok: float | None = None
    latency_ema_s: float | None = None
    successes: int = 0
    failures: int = 0
    down_since: float | None = None
    total_down_s: float = 0.0
    transitions: list = field(default_factory=list)


class AIHealthMonitor:
    def __init__(self, base_backoff_s: float = 5.0, max_backoff_s: float = 120.0, clock=time.time):
        self.base, self.max, self.clock = base_backoff_s, max_backoff_s, clock
        self.routes: dict[str, RouteHealth] = {}
        self._lock = threading.Lock()

    def _h(self, key) -> RouteHealth:
        return self.routes.setdefault(key, RouteHealth())

    def available(self, key: str) -> tuple[bool, float]:
        with self._lock:
            h = self._h(key)
            wait = h.open_until - self.clock()
            return wait <= 0, max(0.0, wait)        # when the breaker timer ends the next call IS the recovery probe

    def success(self, key: str, latency_s: float) -> None:
        with self._lock:
            h = self._h(key)
            if h.state == "down" and h.down_since:
                h.total_down_s += self.clock() - h.down_since
            if h.state in ("down", "degraded"):
                h.transitions.append((self.clock(), "recovered"))
            h.state, h.consecutive_failures, h.open_until, h.down_since = "ok", 0, 0.0, None
            h.last_ok, h.successes = self.clock(), h.successes + 1
            h.latency_ema_s = latency_s if h.latency_ema_s is None else 0.8 * h.latency_ema_s + 0.2 * latency_s

    def failure(self, key: str, kind: str, msg: str = "", retry_after: float | None = None) -> None:
        with self._lock:
            h = self._h(key)
            h.failures += 1
            h.consecutive_failures += 1
            h.last_error = f"{kind}: {msg}"[:200]
            back = min(self.max, self.base * 2 ** (h.consecutive_failures - 1))
            if retry_after:
                back = max(back, min(retry_after, self.max))
            if kind in ("auth", "not_configured"):
                back = max(back, 3600.0)          # nothing will fix a missing/invalid key by retrying
            h.open_until = self.clock() + back
            was = h.state
            h.state = "down" if h.consecutive_failures >= 3 or kind in ("auth", "not_configured", "model_unavailable") else "degraded"
            if h.state == "down" and was != "down":
                h.down_since = self.clock()
                h.transitions.append((self.clock(), "down"))

    def snapshot(self) -> dict:
        with self._lock:
            now = self.clock()
            return {k: {"state": h.state, "consecutive_failures": h.consecutive_failures, "retry_in_s": max(0, round(h.open_until - now, 1)),
                        "last_error": h.last_error, "successes": h.successes, "failures": h.failures,
                        "latency_ema_s": None if h.latency_ema_s is None else round(h.latency_ema_s, 2),
                        "total_down_s": round(h.total_down_s + ((now - h.down_since) if h.down_since else 0), 1)}
                    for k, h in self.routes.items()}
