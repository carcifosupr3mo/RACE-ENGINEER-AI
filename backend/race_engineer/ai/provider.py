"""Provider-agnostic LLM interface with timeout, budget and fallback. API keys are read ONLY from environment variables."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Protocol

import httpx


@dataclass
class LLMResult:
    text: str
    tokens_in: int = 0
    tokens_out: int = 0


class LLMError(Exception):
    pass


class LLMProvider(Protocol):
    name: str
    def complete(self, system: str, user: str, timeout_s: float) -> LLMResult: ...


class OpenAICompatProvider:
    """Any OpenAI-compatible chat endpoint: OpenAI, Ollama (/v1), LM Studio, llama.cpp server, ..."""
    def __init__(self, base_url: str, model: str, api_key_env: str | None = None, transport: httpx.BaseTransport | None = None):
        self.name = f"openai_compat:{model}"
        self.base_url, self.model, self.api_key_env, self._transport = base_url.rstrip("/"), model, api_key_env, transport

    def complete(self, system, user, timeout_s):
        headers = {}
        if self.api_key_env:
            key = os.environ.get(self.api_key_env)
            if not key:
                raise LLMError(f"environment variable {self.api_key_env} is not set")
            headers["Authorization"] = f"Bearer {key}"
        body = {"model": self.model, "temperature": 0, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        try:
            with httpx.Client(timeout=timeout_s, transport=self._transport) as c:
                r = c.post(self.base_url + "/chat/completions", json=body, headers=headers)
            r.raise_for_status()
            d = r.json()
            u = d.get("usage", {})
            return LLMResult(d["choices"][0]["message"]["content"], u.get("prompt_tokens", 0), u.get("completion_tokens", 0))
        except (httpx.HTTPError, KeyError, ValueError) as e:
            raise LLMError(f"{type(e).__name__}: {e}") from e


class AnthropicProvider:
    def __init__(self, model: str, api_key_env: str = "ANTHROPIC_API_KEY", base_url: str = "https://api.anthropic.com", transport=None):
        self.name = f"anthropic:{model}"
        self.model, self.api_key_env, self.base_url, self._transport = model, api_key_env, base_url.rstrip("/"), transport

    def complete(self, system, user, timeout_s):
        key = os.environ.get(self.api_key_env)
        if not key:
            raise LLMError(f"environment variable {self.api_key_env} is not set")
        body = {"model": self.model, "max_tokens": 1500, "system": system, "messages": [{"role": "user", "content": user}]}
        try:
            with httpx.Client(timeout=timeout_s, transport=self._transport) as c:
                r = c.post(self.base_url + "/v1/messages", json=body, headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
            r.raise_for_status()
            d = r.json()
            return LLMResult("".join(b.get("text", "") for b in d["content"]), d.get("usage", {}).get("input_tokens", 0), d.get("usage", {}).get("output_tokens", 0))
        except (httpx.HTTPError, KeyError, ValueError) as e:
            raise LLMError(f"{type(e).__name__}: {e}") from e


@dataclass
class Budget:
    daily_token_limit: int = 0         # 0 = unlimited
    price_in_per_1k: float = 0.0
    price_out_per_1k: float = 0.0
    day: str = ""
    tokens: int = 0
    cost: float = 0.0

    def check(self):
        self._roll()
        if self.daily_token_limit and self.tokens >= self.daily_token_limit:
            raise LLMError("daily token budget exhausted")

    def record(self, r: LLMResult):
        self._roll()
        self.tokens += r.tokens_in + r.tokens_out
        self.cost += r.tokens_in / 1000 * self.price_in_per_1k + r.tokens_out / 1000 * self.price_out_per_1k

    def _roll(self):
        d = time.strftime("%Y-%m-%d")
        if d != self.day:
            self.day, self.tokens, self.cost = d, 0, 0.0


@dataclass
class ProviderChain:
    providers: list = field(default_factory=list)
    budget: Budget = field(default_factory=Budget)
    timeout_s: float = 20.0

    def complete(self, system: str, user: str) -> tuple[LLMResult, str]:
        errs = []
        for p in self.providers:
            try:
                self.budget.check()
                r = p.complete(system, user, self.timeout_s)
                self.budget.record(r)
                return r, p.name
            except LLMError as e:
                errs.append(f"{p.name}: {e}")
        raise LLMError("; ".join(errs) or "no provider configured")


def from_settings(cfg: dict | None) -> ProviderChain | None:
    if not cfg or not cfg.get("enabled"):
        return None
    if cfg.get("mode") == "free_multi":      # NVIDIA -> Groq -> local; see ai/providers
        from .providers.chain import ManagerChain, get_manager
        return ManagerChain(get_manager(cfg.get("free_multi")))
    ps = []
    for p in cfg.get("providers", []):
        if p["type"] == "openai_compat":
            ps.append(OpenAICompatProvider(p["base_url"], p["model"], p.get("api_key_env")))
        elif p["type"] == "anthropic":
            ps.append(AnthropicProvider(p["model"], p.get("api_key_env", "ANTHROPIC_API_KEY")))
    b = cfg.get("budget", {})
    return ProviderChain(ps, Budget(b.get("daily_token_limit", 0), b.get("price_in_per_1k", 0.0), b.get("price_out_per_1k", 0.0)), cfg.get("timeout_s", 20.0))
