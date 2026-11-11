"""Regression: the windowed exe (no console) probes for the LMU process with `tasklist`. Without CREATE_NO_WINDOW Windows opens
a black cmd window for that console child every time the probe runs (at start and at every retry)."""
import subprocess
import sys
import types

from race_engineer.lmu import discovery

CREATE_NO_WINDOW = 0x08000000


def _probe(monkeypatch, stdout):
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(kw, cmd=cmd)
        return types.SimpleNamespace(stdout=stdout)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "run", fake_run)
    return discovery.is_lmu_process_running(), seen


def test_windows_process_probe_never_opens_a_console(monkeypatch):
    found, kw = _probe(monkeypatch, "Le Mans Ultimate.exe   1234 Console  1  2,000,000 K\n")
    assert found is True
    assert kw["creationflags"] & CREATE_NO_WINDOW
    assert kw["stdin"] is subprocess.DEVNULL          # the windowed exe has no valid stdin handle to inherit
    assert kw["cmd"][0].lower().endswith("tasklist.exe") and "\\" in kw["cmd"][0]   # absolute System32 path, not a PATH lookup


def test_windows_process_probe_not_running(monkeypatch):
    found, _ = _probe(monkeypatch, "INFO: No tasks are running which match the specified criteria.\n")
    assert found is False
