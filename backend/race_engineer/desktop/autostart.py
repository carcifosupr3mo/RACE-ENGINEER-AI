"""«Avvia con Windows»: an opt-in entry in the CURRENT USER's Run key (no admin rights, nothing system-wide).
Only offered by the installed/portable exe on Windows; started that way the app stays in the tray."""
from __future__ import annotations

import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "RaceEngineerAI"


def supported() -> bool:
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def command(exe: str | None = None) -> str:
    return f'"{exe or sys.executable}" --start-minimized'


def is_enabled() -> bool:
    """True only if the entry points at THIS exe (a moved portable folder reads as off, so ticking it again repairs the path)."""
    if not supported():
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return winreg.QueryValueEx(k, VALUE)[0] == command()
    except OSError:
        return False


def set_enabled(on: bool) -> bool:
    """Write or remove the entry; returns the resulting state. Raises OSError if the registry refuses."""
    if not supported():
        return False
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, VALUE, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(k, VALUE)
            except FileNotFoundError:
                pass
    return is_enabled()
