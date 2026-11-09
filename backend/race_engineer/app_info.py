"""Version and build identity of this installation (for reports). The commit is recorded at build time in build_info.json."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from . import __version__


def _candidates() -> list[Path]:
    c = [Path(sys.executable).resolve().parent / "build_info.json"] if getattr(sys, "frozen", False) else []
    c.append(Path(__file__).resolve().parents[2] / "build_info.json")
    return c


def info() -> dict:
    out = {"version": __version__, "commit": None, "built_utc": None, "frozen": bool(getattr(sys, "frozen", False)),
           "commit_source": "unknown (no build_info.json: build predates commit recording, or running from source)"}
    for p in _candidates():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.update(commit=d.get("commit"), built_utc=d.get("built_utc"), commit_source="build_info.json")
        break
    if not out["commit"] and os.environ.get("RE_COMMIT"):
        out.update(commit=os.environ["RE_COMMIT"], commit_source="RE_COMMIT env")
    return out
