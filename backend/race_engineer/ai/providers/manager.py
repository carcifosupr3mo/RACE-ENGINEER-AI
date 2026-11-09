"""AIProviderManager: ordered routes, quota + health aware, with automatic fallback and final 'local' fallback.

Order (spec): 1 NVIDIA primary -> 2 NVIDIA alternative (only if user confirmed it is free) -> 3 Groq gpt-oss ->
4 Groq qwen -> local analysis (the caller's rules engine; raising AllProvidersUnavailable means "use local").
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

from .adapters import GroqAdapter, NVIDIAAdapter, OpenAICompatAdapter
from .health import AIHealthMonitor
from .quota import AIQuotaManager, Limits
from .types import AIRequest, AIResponse, AllProvidersUnavailable, ProviderError

NVIDIA_PRIMARY = "nvidia/nemotron-3.5-lightning-30b-a3b"
GROQ_MODELS = ["openai/gpt-oss-120b", "qwen/qwen3.8-27b"]


@dataclass
class Route:
    adapter: OpenAICompatAdapter
    model: str

    @property
    def key(self) -> str:
        return f"{self.adapter.name}:{self.model}"


@dataclass
class ManagerStats:
    requests: int = 0
    served: int = 0
    fallbacks: int = 0
    local_fallbacks: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    errors: dict = field(default_factory=dict)
    by_route: dict = field(default_factory=dict)


class AIProviderManager:
    def __init__(self, routes: list[Route], quota: AIQuotaManager, health: AIHealthMonitor | None = None, timeout_s: float = 25.0):
        self.routes, self.quota, self.health, self.timeout_s = routes, quota, health or AIHealthMonitor(), timeout_s
        self.stats = ManagerStats()
        self._lock = threading.Lock()

    def available_routes(self, est_tokens: int = 0) -> list[tuple[Route, str]]:
        out = []
        for r in self.routes:
            ok_h, _ = self.health.available(r.key)
            ok_q, why, _ = self.quota.can_send(r.adapter.name, r.model, est_tokens)
            out.append((r, "" if ok_h and ok_q and r.adapter.configured() else (why or ("health" if not ok_h else "no_key"))))
        return out

    def next_ready_in(self, est_tokens: int = 0) -> float:
        """Seconds until some route might accept a request (used by the queue to sleep instead of hammering)."""
        best = 1e9
        for r in self.routes:
            if not r.adapter.configured():
                continue
            _, w1 = self.health.available(r.key)
            _, _, w2 = self.quota.can_send(r.adapter.name, r.model, est_tokens)
            best = min(best, max(w1, w2))
        return 0.0 if best == 1e9 and not self.routes else best

    def complete(self, req: AIRequest) -> AIResponse:
        with self._lock:
            self.stats.requests += 1
        reasons, depth = [], 0
        est = req.est_tokens()
        for r in self.routes:
            if req.stale(self.quota.clock()):
                raise AllProvidersUnavailable(["request became stale before it could be sent"])
            ok_h, wait = self.health.available(r.key)
            ok_q, why, _ = self.quota.can_send(r.adapter.name, r.model, est)
            if not r.adapter.configured():
                reasons.append(f"{r.key}: no key")
                continue
            if not ok_h:
                reasons.append(f"{r.key}: circuit open {wait:.0f}s")
                depth += 1
                continue
            if not ok_q:
                reasons.append(f"{r.key}: quota {why}")
                depth += 1
                continue
            try:
                resp = r.adapter.complete(r.model, req.system, req.user, req.max_tokens, self.timeout_s)
            except ProviderError as e:
                self._on_error(r, e)
                reasons.append(f"{r.key}: {e}")
                depth += 1
                if e.kind == "bad_request":       # our fault, not the provider's: another provider will not help either
                    break
                continue
            self.health.success(r.key, resp.latency_s)
            self.quota.record(r.adapter.name, r.model, (resp.tokens_in + resp.tokens_out) or est)
            self.quota.note_headers(r.adapter.name, r.model, r.adapter.last_headers)
            resp.fallback_depth = depth
            with self._lock:
                s = self.stats
                s.served += 1
                s.fallbacks += 1 if depth else 0
                s.tokens_in += resp.tokens_in
                s.tokens_out += resp.tokens_out
                br = s.by_route.setdefault(r.key, {"ok": 0, "err": 0, "tokens": 0})
                br["ok"] += 1
                br["tokens"] += resp.tokens_in + resp.tokens_out
            return resp
        with self._lock:
            self.stats.local_fallbacks += 1
        raise AllProvidersUnavailable(reasons)

    def _on_error(self, r: Route, e: ProviderError) -> None:
        if e.kind != "bad_request":
            self.health.failure(r.key, e.kind, str(e), e.retry_after)
        if e.kind == "rate_limit":
            self.quota.block(r.adapter.name, r.model, e.retry_after or 30.0, "429")
        elif e.kind == "quota":
            self.quota.block(r.adapter.name, r.model, 3600.0, "quota exhausted")
        elif e.kind == "model_unavailable":
            self.quota.block(r.adapter.name, r.model, 3600.0, "model unavailable")
        with self._lock:
            self.stats.errors[e.kind] = self.stats.errors.get(e.kind, 0) + 1
            self.stats.by_route.setdefault(r.key, {"ok": 0, "err": 0, "tokens": 0})["err"] += 1

    def status(self) -> dict:
        return {"routes": [{"route": r.key, "configured": r.adapter.configured(), "blocked_reason": why or None,
                            "usage": self.quota.usage(r.adapter.name, r.model)} for r, why in self.available_routes()],
                "health": self.health.snapshot(),
                "stats": {k: v for k, v in vars(self.stats).items()}}


def build_default_manager(db_path, cfg: dict | None = None, transport=None, key_overrides: dict | None = None,
                          clock=None) -> AIProviderManager:
    """Default free-only route order. ``cfg`` may override models/limits/base urls; paid models can never be added without
    also being put in ``allowed_models`` by the user."""
    import time
    cfg = cfg or {}
    ko = key_overrides or {}
    nv = cfg.get("nvidia", {})
    gq = cfg.get("groq", {})
    nv_models = [nv.get("model", NVIDIA_PRIMARY)]
    if nv.get("alternative_model") and nv.get("alternative_confirmed_free"):   # only when the user confirmed it is a free endpoint
        nv_models.append(nv["alternative_model"])
    nvidia = NVIDIAAdapter(nv_models, nv.get("allowed_models"), nv.get("base_url"), nv.get("api_key_env"), transport, ko.get("nvidia"))
    groq = GroqAdapter(gq.get("models", GROQ_MODELS), gq.get("allowed_models"), gq.get("base_url"), gq.get("api_key_env"), transport, ko.get("groq"))
    routes = []
    if nv.get("enabled", True):
        routes += [Route(nvidia, m) for m in nv_models]
    if gq.get("enabled", True):
        routes += [Route(groq, m) for m in groq.models]
    limits = {}
    for prov, c in (("nvidia", nv), ("groq", gq)):
        for m, lim in (c.get("limits") or {}).items():
            limits[(prov, m)] = Limits(**lim)
    clk = clock or time.time
    return AIProviderManager(routes, AIQuotaManager(db_path, limits, clk), AIHealthMonitor(clock=clk), cfg.get("timeout_s", 25.0))
