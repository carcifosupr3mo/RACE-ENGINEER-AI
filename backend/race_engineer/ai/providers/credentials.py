"""API-key handling. Keys are NEVER written to config files, logs, the catalog or sent to the frontend.

Lookup order: (1) environment variable named in the provider config, (2) OS credential store through ``keyring``
(Windows Credential Manager on Windows). ``store_key`` only writes to the OS credential store.
"""
from __future__ import annotations

import logging
import os
import re

SERVICE = "RaceEngineerAI"
DEFAULT_ENV = {"nvidia": "NVIDIA_API_KEY", "groq": "GROQ_API_KEY"}
_KEY_RE = re.compile(r"(nvapi-[A-Za-z0-9_\-]{8,}|gsk_[A-Za-z0-9]{8,}|sk-[A-Za-z0-9_\-]{12,}|Bearer\s+[A-Za-z0-9._\-]{12,})")


def redact(text: str) -> str:
    return _KEY_RE.sub("<redacted-key>", str(text))


class RedactFilter(logging.Filter):
    """Attach to the root logger so a key can never reach a log file by accident."""
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


def _keyring():
    try:
        import keyring
        return keyring
    except Exception:
        return None


def resolve_key(provider: str, env_name: str | None = None) -> tuple[str | None, str]:
    """-> (key or None, source) where source is 'env:<NAME>' | 'keyring' | 'missing'. The key itself is only returned to adapters."""
    name = env_name or DEFAULT_ENV.get(provider, provider.upper() + "_API_KEY")
    if v := os.environ.get(name):
        return v.strip(), f"env:{name}"
    kr = _keyring()
    if kr:
        try:
            v = kr.get_password(SERVICE, provider)
            if v:
                return v, "keyring"
        except Exception:
            pass
    return None, "missing"


def key_status(provider: str, env_name: str | None = None) -> dict:
    """Safe for the UI: says WHERE a key was found, never the key (not even a prefix)."""
    _, src = resolve_key(provider, env_name)
    return {"provider": provider, "configured": src != "missing", "source": src, "keyring_available": _keyring() is not None}


def store_key(provider: str, key: str) -> dict:
    kr = _keyring()
    if not kr:
        return {"stored": False, "reason": "keyring not installed: set the environment variable instead (pip install keyring)"}
    try:
        kr.set_password(SERVICE, provider, key.strip())
        return {"stored": True, "where": "OS credential store"}
    except Exception as e:
        return {"stored": False, "reason": redact(f"{type(e).__name__}: {e}")}


def delete_key(provider: str) -> bool:
    kr = _keyring()
    try:
        kr and kr.delete_password(SERVICE, provider)
        return True
    except Exception:
        return False
