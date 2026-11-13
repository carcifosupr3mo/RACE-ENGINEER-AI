"""scripts/sign_windows.py: the parts that can be checked on any OS (the real signing is exercised on Windows by CI)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import sign_windows  # noqa: E402


def test_credentials_are_removed_from_the_environment_children_inherit():
    env = {"PATH": "x", sign_windows.ENV_PFX: "QUJD", sign_windows.ENV_PASSWORD: "pw", sign_windows.ENV_TIMESTAMP: ""}
    creds = sign_windows.take_credentials(env)
    assert creds == {sign_windows.ENV_PFX: "QUJD", sign_windows.ENV_PASSWORD: "pw"}
    assert sign_windows.ENV_PFX not in env and sign_windows.ENV_PASSWORD not in env and env["PATH"] == "x"


def test_without_a_certificate_nothing_is_signed_and_it_is_said(capsys):
    assert sign_windows.sign(["a.exe"], {}) is False
    out = capsys.readouterr().out
    assert "UNSIGNED" in out and "a.exe" in out


def test_sign_command_uses_sha256_and_a_timestamp():
    cmd = sign_windows.sign_command("signtool.exe", "c.pfx", "pw", "http://ts.example", ["a.exe", "b.exe"])
    assert cmd[:2] == ["signtool.exe", "sign"] and cmd[-2:] == ["a.exe", "b.exe"]
    assert cmd[cmd.index("/fd") + 1] == "SHA256" and cmd[cmd.index("/td") + 1] == "SHA256" and cmd[cmd.index("/tr") + 1] == "http://ts.example"


@pytest.mark.skipif(sys.platform == "win32", reason="on Windows the real signing path is used")
def test_signing_with_a_certificate_refuses_to_pretend_off_windows():
    with pytest.raises(RuntimeError):
        sign_windows.sign(["a.exe"], {sign_windows.ENV_PFX: "QUJD"})


def test_windows_powershell_child_does_not_inherit_powershell7_module_path(monkeypatch):
    """CI regression: started from PowerShell 7, the inherited PSModulePath made Windows PowerShell 5.1 lose its Cert: drive."""
    monkeypatch.setenv("PSModulePath", r"C:\Program Files\PowerShell\7\Modules")
    env = sign_windows.ps_env(RE_X="1")
    assert not any(k.upper() == "PSMODULEPATH" for k in env) and env["RE_X"] == "1"
