"""Runtime wiring: acquisition engine -> endurance pipeline (+ optional AI queue worker). Failures here never affect acquisition."""
from __future__ import annotations

import threading
from pathlib import Path

from ..ai.providers import AIRequestQueue
from ..ai.providers.chain import get_manager
from .memory import RaceMemory
from .pipeline import EndurancePipeline


class EnduranceService:
    def __init__(self, engine, catalog, root: Path, interval_s: float = 300.0):
        self.engine, self.catalog, self.root, self.interval_s = engine, catalog, Path(root), interval_s
        self.mem = RaceMemory(self.root / "race_memory.sqlite")
        self.pipelines: dict[str, EndurancePipeline] = {}
        self.current: EndurancePipeline | None = None
        self.queue: AIRequestQueue | None = None
        self._lock = threading.Lock()
        engine.on_session_start.append(self._start)
        engine.on_session_end.append(self._end)
        engine.on_sample.append(self._sample)

    def _ai_cfg(self) -> dict | None:
        cfg = self.catalog.get_setting("ai") or {}
        return cfg if cfg.get("enabled") and cfg.get("mode") == "free_multi" else None

    def _ensure_queue(self, cfg: dict) -> AIRequestQueue:
        if self.queue is None:
            self.queue = AIRequestQueue(self.root / "ai_queue.sqlite", get_manager(cfg.get("free_multi"), self.root),
                                        max_calls_per_hour=cfg.get("max_calls_per_hour", 120))
            self.queue.start()
        return self.queue

    def _start(self, sid: str, ctx, synthetic: bool) -> None:
        cfg = self._ai_cfg()
        q = self._ensure_queue(cfg) if (cfg and not synthetic) else None       # synthetic sessions never spend free quota
        p = EndurancePipeline(self.mem, q, sid, summary_interval_s=(cfg or {}).get("summary_interval_s", self.interval_s), ai_enabled=q is not None)
        with self._lock:
            self.pipelines[sid] = p
            self.current = p

    def _sample(self, s) -> None:
        p = self.current
        if p is not None:
            p.on_sample(s.values)

    def _end(self, sid: str) -> None:
        p = self.pipelines.get(sid)
        if p:
            p.end_session()

    def status(self) -> dict:
        p = self.current
        return {"memory": self.mem.counts(), "ai_queue": None if self.queue is None else {"pending": self.queue.pending(), "counters": self.queue.counters,
                                                                                               "status": self.queue.status_counts()},
                "current": None if p is None else {"session_id": p.sid, "stats": vars(p.stats), "state": p.det.snapshot(), "ai_enabled": p.ai_enabled},
                "note": "local analysis always on; AI is optional and only sees aggregates"}

    def stop(self) -> None:
        if self.queue:
            self.queue.stop()
