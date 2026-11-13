"""Provider adapters (OpenAI-compatible chat completions). Free-tier ONLY: a model must be in ``allowed_models``.

Verified facts (2026-11-09, no account keys available in the dev environment):
* NVIDIA ``GET https://integrate.api.nvidia.com/v1/models`` is public and lists ``nvidia/nemotron-3.5-lightning-30b-a3b``.
  Listing a model does NOT prove it is a free endpoint for a given account: confirm in build.nvidia.com.
* Groq docs list ``openai/gpt-oss-120b`` and ``qwen/qwen3.8-27b``; free-plan limits there: 30 RPM, 1K RPD, 8K TPM, 200K TPD.
"""
from __future__ import annotations

import re
import time

import httpx

from .credentials import redact, resolve_key
from .types import AIResponse, ProviderError

_THINK = re.compile(r"<think>.*?</think>", re.S)


def classify_http(status: int, body: str, headers) -> ProviderError:
    ra = None
    try:
        ra = float(headers.get("retry-after")) if headers.get("retry-after") else None
    except ValueError:
        pass
    low = (body or "").lower()
    msg = redact((body or "")[:200])
    if status in (401, 403):
        return ProviderError("auth", msg, status=status)
    if status == 402 or "insufficient" in low or "quota" in low and status != 429 or "billing" in low:
        return ProviderError("quota", msg, ra, status)
    if status == 404 or "model_not_found" in low or "does not exist" in low or "decommissioned" in low:
        return ProviderError("model_unavailable", msg, ra, status)
    if status == 429:
        return ProviderError("rate_limit", msg, ra, status)
    if status in (408, 504):
        return ProviderError("timeout", msg, ra, status)
    if status >= 500:
        return ProviderError("server", msg, ra, status)
    return ProviderError("bad_request", msg, None, status)


class OpenAICompatAdapter:
    name = "openai_compat"
    default_base = ""
    key_env: str | None = None
    extra_body: dict = {}

    def __init__(self, models: list[str], allowed_models: list[str] | None = None, base_url: str | None = None,
                 key_env: str | None = None, transport: httpx.BaseTransport | None = None, key_override: str | None = None):
        self.models = list(models)
        self.allowed = set(allowed_models if allowed_models is not None else models)
        self.base_url = (base_url or self.default_base).rstrip("/")
        self.key_env = key_env or self.key_env
        self._transport = transport
        self._key_override = key_override      # tests only
        self.last_headers: dict = {}

    # -- key -------------------------------------------------------------
    def _key(self) -> str:
        k = self._key_override or resolve_key(self.name, self.key_env)[0]
        if not k:
            raise ProviderError("not_configured", f"no API key for {self.name} (env var or Credential Manager)")
        return k

    def configured(self) -> bool:
        return bool(self._key_override or resolve_key(self.name, self.key_env)[0])

    # -- calls -----------------------------------------------------------
    def list_models(self, timeout_s: float = 15.0) -> list[str]:
        try:
            with httpx.Client(timeout=timeout_s, transport=self._transport) as c:
                r = c.get(self.base_url + "/models", headers={"Authorization": f"Bearer {self._key()}"})
        except httpx.TimeoutException as e:
            raise ProviderError("timeout", type(e).__name__)
        except httpx.HTTPError as e:
            raise ProviderError("network", redact(str(e)))
        if r.status_code != 200:
            raise classify_http(r.status_code, r.text, r.headers)
        return [m["id"] for m in r.json().get("data", [])]

    def complete(self, model: str, system: str, user: str, max_tokens: int, timeout_s: float) -> AIResponse:
        if model not in self.allowed:        # hard guard: never call a model that is not an explicitly allowed FREE model
            raise ProviderError("blocked", f"model {model!r} is not in the allowed free-model list")
        t0 = time.monotonic()
        budget, tin, tout = max_tokens, 0, 0
        for attempt in (1, 2):
            text, finish, usage = self._post(model, system, user, budget, timeout_s)
            tin += int(usage.get("prompt_tokens", 0)); tout += int(usage.get("completion_tokens", 0))
            if text:
                return AIResponse(text, self.name, model, tin, tout, time.monotonic() - t0)
            if attempt == 1 and finish == "length":
                # reasoning models spend the whole token budget "thinking" and return no visible answer: retry once with room to answer
                budget = max(max_tokens * 4, 600)
                continue
            break
        why = ("il modello ha esaurito i token nel ragionamento senza dare una risposta" if finish == "length"
               else "il modello ha risposto con un testo vuoto")
        raise ProviderError("bad_response", f"empty completion ({why}; finish_reason={finish})")

    def _post(self, model: str, system: str, user: str, max_tokens: int, timeout_s: float) -> tuple[str, str | None, dict]:
        body = {"model": model, "temperature": 0.2, "max_tokens": max_tokens, "stream": False,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], **self.extra_body}
        try:
            with httpx.Client(timeout=timeout_s, transport=self._transport) as c:
                r = c.post(self.base_url + "/chat/completions", json=body, headers={"Authorization": f"Bearer {self._key()}"})
        except httpx.TimeoutException as e:
            raise ProviderError("timeout", type(e).__name__)
        except httpx.HTTPError as e:
            raise ProviderError("network", redact(f"{type(e).__name__}: {e}"))
        self.last_headers = {k.lower(): v for k, v in r.headers.items() if k.lower().startswith(("x-ratelimit", "retry-after"))}
        if r.status_code != 200:
            raise classify_http(r.status_code, r.text, r.headers)
        try:
            d = r.json()
            ch = d["choices"][0]
            text = _THINK.sub("", ch["message"].get("content") or "").strip()
            return text, ch.get("finish_reason"), d.get("usage") or {}
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            raise ProviderError("bad_response", "unparseable completion")


class NVIDIAAdapter(OpenAICompatAdapter):
    name = "nvidia"
    default_base = "https://integrate.api.nvidia.com/v1"
    key_env = "NVIDIA_API_KEY"


class GroqAdapter(OpenAICompatAdapter):
    name = "groq"
    default_base = "https://api.groq.com/openai/v1"
    key_env = "GROQ_API_KEY"
    extra_body = {"reasoning_effort": "low"}      # keeps gpt-oss/qwen reasoning short (tokens are the scarce free-tier resource)

    def complete(self, model, system, user, max_tokens, timeout_s):
        if not model.startswith("openai/gpt-oss"):
            self.extra_body = {}                   # only gpt-oss is documented to take reasoning_effort here
        else:
            self.extra_body = {"reasoning_effort": "low"}
        return super().complete(model, system, user, max_tokens, timeout_s)
