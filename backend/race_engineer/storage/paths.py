from __future__ import annotations

import os
import sys
from pathlib import Path


def data_dir() -> Path:
    """App data root. Override with RACE_ENGINEER_DATA. Never inside the LMU folder."""
    if env := os.environ.get("RACE_ENGINEER_DATA"):
        p = Path(env)
    elif sys.platform == "win32":  # pragma: no cover
        p = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "RaceEngineerAI"
    else:
        p = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "race-engineer-ai"
    p.mkdir(parents=True, exist_ok=True)
    return p
