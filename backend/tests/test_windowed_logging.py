"""Regression: the windowed Windows exe has sys.stdout/sys.stderr = None; uvicorn's default log config then fails with
"Unable to configure formatter 'default'" and the backend never starts."""
import sys
import pytest

uvicorn = pytest.importorskip("uvicorn")


def _cfg(**kw):
    async def app(scope, receive, send): ...
    c = uvicorn.Config(app, log_level="warning", **kw)
    c.load()


def test_default_log_config_breaks_without_streams(monkeypatch):
    monkeypatch.setattr(sys, "stdout", None); monkeypatch.setattr(sys, "stderr", None)
    with pytest.raises(Exception):
        _cfg()


def test_log_config_none_works_without_streams(monkeypatch):
    monkeypatch.setattr(sys, "stdout", None); monkeypatch.setattr(sys, "stderr", None)
    _cfg(log_config=None)
