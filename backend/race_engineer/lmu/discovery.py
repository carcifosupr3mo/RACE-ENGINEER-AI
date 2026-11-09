"""Locate a Le Mans Ultimate installation and its data folders. Strictly read-only."""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

GAME_DIR_NAME = "Le Mans Ultimate"
STEAM_APP_ID_HINT = None  # intentionally not hard-coded: matched through installdir in appmanifest


@dataclass
class LmuInstall:
    found: bool = False
    game_dir: str | None = None
    user_data: str | None = None
    telemetry_dir: str | None = None
    telemetry_config: str | None = None
    shared_memory_header_dir: str | None = None
    steam_build_id: str | None = None
    steam_last_updated: int | None = None
    duckdb_files: list[dict] = field(default_factory=list)
    plugin_setting_hints: list[dict] = field(default_factory=list)
    searched: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def steam_roots(env: dict[str, str] | None = None, home: Path | None = None) -> list[Path]:
    env = os.environ if env is None else env
    home = home or Path.home()
    roots: list[Path] = []
    if override := env.get("LMU_GAME_DIR_PARENT"):
        roots.append(Path(override))
    if sys.platform == "win32":  # pragma: no cover
        try:
            import winreg
            for hive, key, val in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                                   (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath")):
                try:
                    with winreg.OpenKey(hive, key) as k:
                        roots.append(Path(winreg.QueryValueEx(k, val)[0]))
                except OSError:
                    pass
        except ImportError:
            pass
        for e in ("ProgramFiles(x86)", "ProgramFiles"):
            if env.get(e):
                roots.append(Path(env[e]) / "Steam")
    roots += [home / ".steam" / "steam", home / ".local" / "share" / "Steam",
              home / ".var/app/com.valvesoftware.Steam/.local/share/Steam"]
    return roots


def steam_libraries(root: Path) -> list[Path]:
    libs = [root]
    vdf = root / "steamapps" / "libraryfolders.vdf"
    try:
        text = vdf.read_text(encoding="utf-8", errors="replace")
        libs += [Path(p.replace("\\\\", "\\")) for p in re.findall(r'"path"\s+"([^"]+)"', text)]
    except OSError:
        pass
    seen, out = set(), []
    for lib in libs:
        if str(lib) not in seen:
            seen.add(str(lib))
            out.append(lib)
    return out


def _manifest_info(lib: Path) -> tuple[str | None, int | None]:
    apps = lib / "steamapps"
    try:
        for mf in apps.glob("appmanifest_*.acf"):
            t = mf.read_text(encoding="utf-8", errors="replace")
            if re.search(r'"installdir"\s+"%s"' % re.escape(GAME_DIR_NAME), t):
                b = re.search(r'"buildid"\s+"(\d+)"', t)
                u = re.search(r'"LastUpdated"\s+"(\d+)"', t)
                return (b.group(1) if b else None, int(u.group(1)) if u else None)
    except OSError:
        pass
    return None, None


def find_install(roots: list[Path] | None = None, extra_game_dirs: list[Path] | None = None) -> LmuInstall:
    res = LmuInstall()
    candidates: list[tuple[Path, Path | None]] = [(d, None) for d in (extra_game_dirs or [])]
    env_dir = os.environ.get("LMU_GAME_DIR")
    if env_dir:
        candidates.append((Path(env_dir), None))
    for root in (roots if roots is not None else steam_roots()):
        for lib in steam_libraries(root):
            candidates.append((lib / "steamapps" / "common" / GAME_DIR_NAME, lib))
    for game, lib in candidates:
        res.searched.append(str(game))
        if game.is_dir():
            res.found = True
            res.game_dir = str(game)
            if lib is not None:
                res.steam_build_id, res.steam_last_updated = _manifest_info(lib)
            break
    if not res.found:
        res.notes.append("LMU installation directory not found (set LMU_GAME_DIR to override).")
        return res
    game = Path(res.game_dir)  # type: ignore[arg-type]
    ud = game / "UserData"
    if ud.is_dir():
        res.user_data = str(ud)
        tel = ud / "Telemetry"
        if tel.is_dir():
            res.telemetry_dir = str(tel)
            cfg = tel / "config.json"
            if cfg.is_file():
                res.telemetry_config = str(cfg)
            res.duckdb_files = [
                {"path": str(p), "size": p.stat().st_size, "mtime": p.stat().st_mtime}
                for p in sorted(tel.glob("*.duckdb"), key=lambda q: q.stat().st_mtime, reverse=True)]
        else:
            res.notes.append("UserData/Telemetry missing: no DuckDB telemetry recorded yet, or recording disabled.")
        res.plugin_setting_hints = scan_plugin_settings(ud)
    else:
        res.notes.append("UserData folder not found next to the game executable.")
    hdr = game / "Support" / "SharedMemoryInterface"
    if hdr.is_dir():
        res.shared_memory_header_dir = str(hdr)
    return res


def scan_plugin_settings(user_data: Path, max_files: int = 40) -> list[dict]:
    """Look for JSON settings keys that mention 'plugin'.

    The on-disk location of the *Enable Plugins* option is NOT verified. This is a best-effort,
    read-only hint; the authoritative check is whether the ``LMU_Data`` mapping exists while in game.
    """
    hits: list[dict] = []
    player = user_data / "player"
    files = list(player.glob("*.json"))[:max_files] + list(player.glob("*.JSON"))[:max_files] if player.is_dir() else []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        stack = [("", data)]
        while stack:
            path, node = stack.pop()
            if isinstance(node, dict):
                for k, v in node.items():
                    if "plugin" in str(k).lower() and not isinstance(v, (dict, list)):
                        hits.append({"file": str(f), "key": f"{path}/{k}", "value": v})
                    stack.append((f"{path}/{k}", v))
            elif isinstance(node, list):
                stack.extend((f"{path}[{i}]", v) for i, v in enumerate(node[:200]))
    return hits


def is_lmu_process_running() -> bool | None:
    """True/False if determinable, None if the platform gives no cheap answer."""
    hint = "le mans ultimate"
    try:
        if sys.platform == "win32":  # pragma: no cover
            import subprocess
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Le Mans Ultimate.exe", "/NH"],
                                 capture_output=True, text=True, timeout=5).stdout.lower()
            return hint in out
        for p in Path("/proc").iterdir():
            if p.name.isdigit():
                try:
                    cmd = (p / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace").lower()
                except OSError:
                    continue
                if hint in cmd and "race_engineer" not in cmd:
                    return True
        return False
    except Exception:
        return None
