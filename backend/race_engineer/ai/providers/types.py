"""Shared types of the multi-provider AI layer. One internal interface for every provider."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import IntEnum


class Priority(IntEnum):
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3


@dataclass
class AIRequest:
    kind: str                       # e.g. periodic_summary | stint_end | pit_stop | event | final_report | chat
    system: str
    user: str
    priority: Priority = Priority.NORMAL
    ttl_s: float = 600.0            # a request older than this is STALE and is never sent
    dedup_key: str | None = None    # same key within the cooldown -> merged / dropped
    max_tokens: int = 600
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created: float = field(default_factory=time.time)
    session_id: str | None = None

    def stale(self, now: float | None = None) -> bool:
        return (now or time.time()) - self.created > self.ttl_s

    def est_tokens(self) -> int:
        return (len(self.system) + len(self.user)) // 3 + self.max_tokens   # conservative: ~3 chars/token


@dataclass
class AIResponse:
    text: str
    provider: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_s: float = 0.0
    fallback_depth: int = 0         # 0 = primary route answered


class ProviderError(Exception):
    """kind: rate_limit | quota | server | timeout | network | auth | model_unavailable | bad_request | bad_response | not_configured | blocked"""
    def __init__(self, kind: str, msg: str = "", retry_after: float | None = None, status: int | None = None):
        super().__init__(f"{kind}: {msg}" if msg else kind)
        self.kind, self.retry_after, self.status = kind, retry_after, status


class AllProvidersUnavailable(Exception):
    def __init__(self, reasons: list[str]):
        super().__init__("; ".join(reasons) or "no provider configured")
        self.reasons = reasons
