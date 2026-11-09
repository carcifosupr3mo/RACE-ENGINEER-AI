"""One real, minimal request per configured provider route (spends a few tokens of FREE quota) + a guided report.

Never prints a key. With no key, nothing is sent and the report says exactly what is missing.
"""
from __future__ import annotations

import time

from .credentials import key_status, redact
from .manager import AIProviderManager
from .types import ProviderError

HOWTO = {
    "nvidia": "Create a key at build.nvidia.com (API key for the model), then set the environment variable NVIDIA_API_KEY "
              "or store it in Windows Credential Manager from the app (Settings > AI > Salva chiave).",
    "groq": "Create a key at console.groq.com (free plan, no card), then set GROQ_API_KEY or store it from the app.",
}


def run(manager: AIProviderManager, send: bool = True) -> dict:
    out = {"generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "routes": [], "keys": {}}
    listed: dict[str, list[str] | str] = {}
    for p in {r.adapter.name: r.adapter for r in manager.routes}.values():
        out["keys"][p.name] = key_status(p.name, p.key_env)
    for r in manager.routes:
        a = r.adapter
        row = {"route": r.key, "configured": a.configured(), "tested": False}
        if not a.configured():
            row["how_to"] = HOWTO.get(a.name, "set the API key environment variable")
            out["routes"].append(row)
            continue
        if a.name not in listed:
            try:
                listed[a.name] = a.list_models()
            except ProviderError as e:
                listed[a.name] = f"{e.kind}"
        lm = listed[a.name]
        row["model_listed_by_provider"] = (r.model in lm) if isinstance(lm, list) else f"unknown ({lm})"
        row["free_tier_note"] = ("Listing does NOT prove the model is a free endpoint for this account; the app only calls models in "
                                 "its allowed list and honours local quota limits.")
        if send and row["model_listed_by_provider"] is not False:
            ok, why, _ = manager.quota.can_send(a.name, r.model, 60)
            if not ok:
                row.update(tested=False, skipped=f"quota/block: {why}")
            else:
                t0 = time.monotonic()
                try:
                    resp = a.complete(r.model, "You are a connectivity test.", "Reply with the single word OK.", 20, manager.timeout_s)
                    manager.quota.record(a.name, r.model, resp.tokens_in + resp.tokens_out)
                    manager.quota.note_headers(a.name, r.model, a.last_headers)
                    row.update(tested=True, ok=True, latency_s=round(time.monotonic() - t0, 2), tokens=resp.tokens_in + resp.tokens_out,
                               ratelimit_headers=a.last_headers, reply_head=redact(resp.text[:30]))
                except ProviderError as e:
                    row.update(tested=True, ok=False, error_kind=e.kind, error=redact(str(e)), http_status=e.status)
        out["routes"].append(row)
    out["summary"] = ("no key configured: nothing sent" if not any(r["configured"] for r in out["routes"])
                      else f"{sum(1 for r in out['routes'] if r.get('ok'))}/{sum(1 for r in out['routes'] if r.get('tested'))} tested routes answered")
    return out
