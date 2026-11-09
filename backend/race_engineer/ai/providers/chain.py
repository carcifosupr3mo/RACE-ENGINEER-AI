"""Glue between the multi-provider manager and the existing grounded-chat code (same ``complete(system,user)`` contract)."""
from __future__ import annotations

import threading
from pathlib import Path

from ..provider import LLMError, LLMResult
from .manager import AIProviderManager, build_default_manager
from .types import AIRequest, AllProvidersUnavailable, Priority

_cache: dict[str, AIProviderManager] = {}
_lock = threading.Lock()


def get_manager(cfg: dict | None = None, root: Path | None = None) -> AIProviderManager:
    from ...storage.paths import data_dir
    root = Path(root) if root else data_dir()
    with _lock:
        key = str(root)
        if key not in _cache:
            _cache[key] = build_default_manager(root / "ai_state.sqlite", cfg)
        return _cache[key]


def reset_cache() -> None:
    with _lock:
        _cache.clear()


class ManagerChain:
    """Drop-in for ``ProviderChain``: any failure surfaces as LLMError so the caller falls back to the local rules engine."""
    def __init__(self, manager: AIProviderManager, session_id: str | None = None):
        self.manager = manager
        self.session_id = session_id

    @property
    def providers(self):
        return [r for r in self.manager.routes if r.adapter.configured()]

    def complete(self, system: str, user: str):
        req = AIRequest(kind="chat", system=system, user=user, priority=Priority.HIGH, ttl_s=60.0, max_tokens=900, session_id=self.session_id)
        try:
            r = self.manager.complete(req)
        except AllProvidersUnavailable as e:
            raise LLMError(str(e)) from e
        return LLMResult(r.text, r.tokens_in, r.tokens_out), f"{r.provider}:{r.model}"
