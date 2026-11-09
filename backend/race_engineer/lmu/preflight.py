"""Pre-flight check for the real-LMU verification on Windows. Strictly read-only (only a write probe inside OUR data folder).

Answers, as one JSON document: which app/commit, is our data folder writable, where is LMU, is it running, does the
``LMU_Data`` mapping exist, which native DuckDB telemetry files and setup files exist. Needs no AI key and no network.
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path

from ..app_info import info as app_info
from ..storage.paths import data_dir
from .discovery import find_install, is_lmu_process_running
from .reader import MappingNotFound, SharedMemoryReader, open_backend


def _writable(folder: Path) -> dict:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / f".write_probe_{uuid.uuid4().hex[:8]}"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
        return {"path": str(folder), "writable": True}
    except OSError as e:
        return {"path": str(folder), "writable": False, "error": f"{type(e).__name__}: {e}"}


def run(shm_path: str | None = None) -> dict:
    from ..setup.inspect import find_setup_files
    root = data_dir()
    rep: dict = {"tool": "race_engineer preflight", "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 "app": app_info(), "platform": {"sys_platform": sys.platform, "os_name": os.name},
                 "data_dir": _writable(root), "reports_dir": _writable(root / "reports"), "missing": [], "warnings": []}
    inst = find_install()
    rep["lmu_install"] = {"found": inst.found, "game_dir": inst.game_dir, "user_data": inst.user_data,
                          "telemetry_dir": inst.telemetry_dir, "steam_build_id": inst.steam_build_id,
                          "headers_dir": inst.shared_memory_header_dir, "notes": inst.notes}
    rep["lmu_process_running"] = is_lmu_process_running()
    m: dict = {"present": False, "size": None, "game_version": None, "error": None, "override": bool(shm_path)}
    try:
        be = open_backend(path_override=shm_path)
        m.update(present=True, size=be.size, description=be.description)
        try:
            m["game_version"] = SharedMemoryReader(be).read_generic().gameVersion
        except Exception as e:                       # decoding problems are findings, not crashes
            m["error"] = f"read failed: {type(e).__name__}: {e}"
        finally:
            be.close()
    except MappingNotFound as e:
        m["error"] = str(e)
    rep["mapping"] = m
    duck = sorted(inst.duckdb_files, key=lambda f: f["mtime"], reverse=True)
    rep["duckdb_files"] = [{"path": f["path"], "size": f["size"], "mtime": f["mtime"]} for f in duck[:30]]
    svm = find_setup_files(inst.user_data) if inst.user_data else []
    svm_sorted = sorted(svm, key=lambda p: Path(p).stat().st_mtime, reverse=True)
    rep["setup_files"] = svm_sorted[:50]
    if not rep["data_dir"]["writable"] or not rep["reports_dir"]["writable"]:
        rep["missing"].append("data_dir_not_writable")
    if not inst.found:
        rep["missing"].append("lmu_install (set LMU_GAME_DIR, or the game is not under a Steam library)")
    if rep["lmu_process_running"] is False:
        rep["missing"].append("lmu_not_running")
    if not m["present"]:
        rep["missing"].append("lmu_data_mapping (Enable Plugins + full restart + load a session)")
    if not duck:
        rep["warnings"].append("no native .duckdb telemetry file found yet (LMU writes it when a session/lap closes; pass --duckdb-file to use another folder)")
    if not svm_sorted:
        rep["warnings"].append("no .svm setup file found in UserData/player/Settings (location UNVERIFIED; pass -SetupFile to use another)")
    if sys.platform != "win32" and not shm_path:
        rep["warnings"].append("not Windows: a real-LMU verification is only possible on the Windows PC")
    return rep
