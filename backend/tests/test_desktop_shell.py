"""Desktop shell helpers: second launch raises the running copy; opt-in «Avvia con Windows» (current user only)."""
import sys
import types

import pytest

from race_engineer.desktop import autostart


class FakeKey:
    def __enter__(self): return self
    def __exit__(self, *a): return False


def fake_winreg(store):
    def query(k, name):
        if name not in store:
            raise FileNotFoundError(name)
        return store[name], 1

    def delete(k, name):
        if name not in store:
            raise FileNotFoundError(name)
        del store[name]
    return types.SimpleNamespace(HKEY_CURRENT_USER=1, KEY_SET_VALUE=2, REG_SZ=1, OpenKey=lambda *a: FakeKey(), QueryValueEx=query,
                                 SetValueEx=lambda k, name, r, t, v: store.__setitem__(name, v), DeleteValue=delete)


@pytest.fixture
def frozen_windows(monkeypatch):
    store = {}
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Apps\Race Engineer\RaceEngineerAI.exe")
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg(store))
    return store


def test_autostart_toggle_writes_quoted_minimized_command(frozen_windows):
    assert autostart.is_enabled() is False
    assert autostart.set_enabled(True) is True
    assert frozen_windows[autostart.VALUE] == r'"C:\Apps\Race Engineer\RaceEngineerAI.exe" --start-minimized'   # quoted: the path has a space
    assert autostart.set_enabled(False) is False and autostart.VALUE not in frozen_windows
    assert autostart.set_enabled(False) is False                                   # removing twice is not an error


def test_autostart_entry_of_a_moved_exe_reads_as_off(frozen_windows):
    frozen_windows[autostart.VALUE] = r'"D:\old\RaceEngineerAI.exe" --start-minimized'
    assert autostart.is_enabled() is False


def test_autostart_not_offered_when_running_from_source(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert autostart.supported() is False and autostart.set_enabled(True) is False


def test_second_launch_asks_the_running_copy_to_show_its_window():
    pytest.importorskip("PySide6")
    import os
    import time
    from PySide6.QtCore import QCoreApplication
    from race_engineer.desktop import single_instance
    app = QCoreApplication.instance() or QCoreApplication([])
    name = f"race_engineer_ai_test_{os.getpid()}"
    assert single_instance.notify_running(name, 200) is False                      # nobody running
    shown = []
    srv = single_instance.listen(lambda: shown.append(1), name)
    assert srv is not None
    try:
        assert single_instance.notify_running(name) is True
        t0 = time.time()
        while not shown and time.time() - t0 < 5:
            app.processEvents()
        assert shown == [1]
    finally:
        srv.close()
