"""Version numbers: only plain ``MAJOR.MINOR.PATCH`` (optionally with a leading ``v``) is STABLE. ``0.6.7-rc1`` is a pre-release."""
from __future__ import annotations

import re

_STABLE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def parse_stable(tag: str | None) -> tuple[int, int, int] | None:
    m = _STABLE.match((tag or "").strip())
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def parse_loose(tag: str | None) -> tuple[int, int, int] | None:
    """Installed version: tolerates a suffix such as ``0.6.7-rc1`` (compared as 0.6.7)."""
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", (tag or "").strip())
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def fmt(v: tuple[int, int, int]) -> str:
    return ".".join(map(str, v))
