import os
import stat
import time
from pathlib import Path

import pytest

from race_engineer.updater import apply as apply_mod
from race_engineer.updater import manager as mgr
from race_engineer.updater import source
from race_engineer.updater.manager import UpdateManager
from race_engineer.updater.source import Policy, UpdateError
from race_engineer.updater.versions import parse_loose, parse_stable

from .fake_github import REPO, FakeGithub, good_package, make_zip, release


@pytest.fixture
def gh():
    g = FakeGithub()
    yield g
    g.close()


def manager(catalog, gh, tmp_path, current="0.6.7", **kw):
    calls = []
    kw.setdefault("launcher", calls.append)
    m = UpdateManager(catalog, current, tmp_path / "work", policy=gh.policy, api_base=gh.base, platform="win32", frozen=True,
                      install_dir=tmp_path / "inst", timeout=3, **kw)
    (tmp_path / "inst").mkdir(parents=True, exist_ok=True)
    (tmp_path / "inst" / "RaceEngineerUpdater.exe").write_bytes(b"u")
    m.calls = calls
    return m


def wait_done(m, states=("error", "restarting"), t=20):
    t0 = time.time()
    while time.time() - t0 < t:
        if m.status()["state"] in states:
            return m.status()
        time.sleep(0.02)
    raise AssertionError(m.status())


# ------------------------------------------------------------------------------- versions / release selection
def test_only_plain_versions_are_stable():
    assert parse_stable("v0.7.0") == (0, 7, 0) and parse_stable("0.7.0") == (0, 7, 0)
    assert parse_stable("v0.6.7-rc1") is None and parse_stable("main") is None and parse_stable(None) is None
    assert parse_loose("0.6.7-rc1") == (0, 6, 7)


def test_latest_stable_ignores_prereleases_drafts_and_odd_tags():
    base = "http://x"
    raw = [release(base, "v0.9.0", prerelease=True), release(base, "v0.8.0", draft=True), release(base, "v0.7.5-rc1"),
           release(base, "v0.7.1"), release(base, "v0.7.2"), release(base, "nightly")]
    assert source.latest_stable(raw).tag == "v0.7.2"
    assert source.latest_stable([release(base, "v1.0.0", prerelease=True)]) is None


def test_checksum_file_parser():
    h = "a" * 64
    assert source.parse_sums(f"{h}  RaceEngineerAI-win32.zip\n{h} *other.exe\njunk") == {"RaceEngineerAI-win32.zip": h, "other.exe": h}


# ------------------------------------------------------------------------------- check
def test_no_update_when_up_to_date(catalog, tmp_path, gh):
    m = manager(catalog, gh, tmp_path, current="0.7.0")
    assert m.check()["state"] == "up_to_date"
    assert manager(catalog, gh, tmp_path, current="0.9.0").check()["state"] == "up_to_date"      # never a downgrade


def test_update_available_reports_versions_and_notes(catalog, tmp_path, gh):
    st = manager(catalog, gh, tmp_path).check()
    assert st["state"] == "available" and st["current"] == "0.6.7" and st["latest"] == "0.7.0" and "prova" in st["notes"] and st["can_install"]


def test_prerelease_only_repo_offers_nothing(catalog, tmp_path):
    g = FakeGithub()
    g.releases = [release(g.base, "v0.6.8-rc1", prerelease=True)]
    assert manager(catalog, g, tmp_path).check()["state"] == "up_to_date"
    g.close()


def test_offline_is_silent_and_never_raises(catalog, tmp_path, gh):
    m = manager(catalog, gh, tmp_path)
    gh.close()
    st = m.check()
    assert st["state"] == "offline" and "Internet" in st["error"]


def test_rate_limit_message(catalog, tmp_path):
    g = FakeGithub(status=403)
    st = manager(catalog, g, tmp_path).check()
    assert st["state"] == "error" and st["error_code"] == "rate_limited"
    g.close()


def test_incompatible_release_is_not_installable_in_app(catalog, tmp_path):
    g = FakeGithub()
    g.releases = [release(g.base, "v0.9.0", "Nuova base.\nmin-update-from: 0.8.0")]
    m = manager(catalog, g, tmp_path)
    st = m.check()
    assert st["state"] == "available" and st["blocked"] == "incompatible" and not st["can_install"] and "0.8.0" in st["message"]
    with pytest.raises(UpdateError):
        m.start_install()
    g.close()


def test_release_without_package_or_checksum_is_not_installable(catalog, tmp_path):
    g = FakeGithub()
    g.releases = [release(g.base, "v0.9.0", assets=False)]
    st = manager(catalog, g, tmp_path).check()
    assert st["blocked"] == "no_package" and not st["can_install"]
    g.close()


def test_source_checkout_cannot_self_install(catalog, tmp_path, gh):
    m = UpdateManager(catalog, "0.6.7", tmp_path / "w", policy=gh.policy, api_base=gh.base, platform="linux", frozen=False)
    st = m.check()
    assert st["state"] == "available" and not st["can_install"] and st["manual_reason"]


def test_untrusted_hosts_are_refused(catalog, tmp_path, gh):
    pol = Policy(schemes=("http",), hosts=("example.org",), repo=REPO)
    m = UpdateManager(catalog, "0.6.7", tmp_path / "w", policy=pol, api_base=gh.base, platform="win32", frozen=True)
    assert m.check()["error_code"] == "untrusted_source"
    with pytest.raises(UpdateError):
        Policy().check("https://evil.example.com/RaceEngineerAI-win32.zip")
    with pytest.raises(UpdateError):
        Policy().check("http://github.com/x")                                  # not https
    with pytest.raises(UpdateError):
        Policy().check("https://github.com/someone/else/releases/download/v1/a.zip", asset=True)      # not this project's releases
    Policy().check(f"https://github.com/{REPO}/releases/download/v1/a.zip", asset=True)


# ------------------------------------------------------------------------------- install
def test_install_flow_has_real_progress_and_hands_over(catalog, tmp_path, gh):
    m = manager(catalog, gh, tmp_path)
    quit_called = []
    m.quit_cb = lambda: quit_called.append(1)
    m.check()
    seen = []
    m.start_install()
    t0 = time.time()
    while m.status()["state"] != "restarting" and time.time() - t0 < 20:
        st = m.status()
        seen.append((st["state"], st["progress"]))
        time.sleep(0.001)
    t0 = time.time()
    while not quit_called and time.time() - t0 < 5:
        time.sleep(0.02)
    st = m.status()
    assert st["state"] == "restarting" and quit_called
    assert {s for s, _ in seen} <= {"downloading", "verifying", "installing", "restarting"}
    call = m.calls[0]
    assert (call["staging"] / "RaceEngineerAI.exe").is_file() and (call["staging"] / "_internal" / "lib.dll").is_file()
    assert call["from"] == "0.6.7" and call["to"] == "0.7.0" and call["exe"] == "RaceEngineerAI.exe"
    assert not (call["staging"].parent / "RaceEngineerAI-win32.zip").exists()
    assert all(p is None or 0 <= p <= 1 for _, p in seen)


def test_corrupted_download_is_rejected_and_nothing_is_installed(catalog, tmp_path):
    g = FakeGithub(tamper=True)
    m = manager(catalog, g, tmp_path)
    m.check(); m.start_install()
    st = wait_done(m)
    assert st["state"] == "error" and st["error_code"] == "bad_checksum" and not m.calls
    assert not list((tmp_path / "work").rglob("staging"))
    g.close()


def test_missing_checksum_entry_is_refused(catalog, tmp_path):
    g = FakeGithub(sums="")
    m = manager(catalog, g, tmp_path)
    m.check(); m.start_install()
    assert wait_done(m)["error_code"] == "no_checksum" and not m.calls
    g.close()


def test_interrupted_download_resumes_with_range(catalog, tmp_path):
    g = FakeGithub(drop_after=1500, drop_times=1)
    m = manager(catalog, g, tmp_path)
    m.check(); m.start_install()
    st = wait_done(m)
    assert st["state"] == "restarting" and m.calls
    assert any(r for _, r in g.requests if r and r.startswith("bytes="))
    g.close()


def test_download_that_keeps_failing_gives_a_clear_error(catalog, tmp_path):
    g = FakeGithub(drop_after=500, drop_times=99)
    m = manager(catalog, g, tmp_path, retries=2)
    m.check(); m.start_install()
    st = wait_done(m)
    assert st["state"] == "error" and st["error_code"] == "interrupted" and "non è stata modificata" in st["error"] and not m.calls
    g.close()


def test_not_enough_disk_space(catalog, tmp_path, gh, monkeypatch):
    m = manager(catalog, gh, tmp_path)
    monkeypatch.setattr(mgr, "free_bytes", lambda p: 1000)
    m.check(); m.start_install()
    st = wait_done(m)
    assert st["error_code"] == "no_space" and "Spazio" in st["error"] and not m.calls


@pytest.mark.parametrize("files,code", [({"../evil.txt": b"x", "RaceEngineerAI.exe": b"a", "RaceEngineerUpdater.exe": b"u"}, "bad_package"),
                                        ({"readme.txt": b"x"}, "bad_package")])
def test_unsafe_or_wrong_package(catalog, tmp_path, files, code):
    g = FakeGithub(package=make_zip(files))
    m = manager(catalog, g, tmp_path)
    m.check(); m.start_install()
    assert wait_done(m)["error_code"] == code and not m.calls
    assert not (tmp_path / "evil.txt").exists() and not (tmp_path / "work" / "evil.txt").exists()
    g.close()


def test_not_a_zip(catalog, tmp_path):
    g = FakeGithub(package=b"this is not a zip" * 100)
    m = manager(catalog, g, tmp_path)
    m.check(); m.start_install()
    assert wait_done(m)["error_code"] == "bad_package"
    g.close()


def test_auto_setting_persists_and_defaults_off(catalog, tmp_path, gh):
    m = manager(catalog, gh, tmp_path)
    assert m.auto is False
    m.set_auto(True)
    assert manager(catalog, gh, tmp_path).auto is True


def test_auto_on_installs_without_asking_and_off_waits(catalog, tmp_path, gh):
    m = manager(catalog, gh, tmp_path)
    m.set_auto(True)
    m.check_in_background()
    wait_done(m)
    assert m.calls
    catalog.put_setting("updates.auto", False)
    m2 = manager(catalog, gh, tmp_path / "b")
    m2.check_in_background()
    time.sleep(1.0)
    assert m2.status()["state"] == "available" and not m2.calls


def test_skip_is_remembered_for_the_session(catalog, tmp_path, gh):
    m = manager(catalog, gh, tmp_path)
    m.check()
    assert m.status()["dismissed"] is False
    assert m.skip()["dismissed"] is True and m.status()["state"] == "available"


# ------------------------------------------------------------------------------- apply (the separate updater program)
def _tree(root: Path, ver: str, exe_body: str = "exit 0"):
    root.mkdir(parents=True, exist_ok=True)
    exe = root / "app.sh"
    exe.write_text(f"#!/bin/sh\n# {ver}\n{exe_body}\n")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    (root / "_internal").mkdir(exist_ok=True)
    (root / "_internal" / "ver.txt").write_text(ver)
    return root


def run_apply(tmp_path, new_body="exit 0", **kw):
    app = _tree(tmp_path / "RaceEngineerAI", "old", "sleep 30")
    (app / "mio_file_utente.txt").write_text("keep me")
    (app / "mydata").mkdir(); (app / "mydata" / "catalog.sqlite").write_text("DB")
    staging = _tree(tmp_path / "up" / "staging", "new", new_body)
    work = tmp_path / "work"; work.mkdir()
    r = apply_mod.run(app=app, staging=staging, exe_name="app.sh", pid=0, version_from="0.6.7", version_to="0.7.0", work=work, app_args=[], watch_s=3, wait_s=2, **kw)
    return app, tmp_path / "RaceEngineerAI.old-0.6.7", work, r


def test_apply_success_replaces_files_keeps_user_files_and_removes_backup(tmp_path):
    app, backup, work, r = run_apply(tmp_path)
    assert r["ok"] and (app / "_internal" / "ver.txt").read_text() == "new"
    assert (app / "mio_file_utente.txt").read_text() == "keep me" and (app / "mydata" / "catalog.sqlite").read_text() == "DB"
    assert not backup.exists() and (work / "update_result.json").exists() and "nuova versione avviata" in (work / "update.log").read_text()


def test_apply_rolls_back_when_the_new_version_crashes_at_start(tmp_path):
    app, backup, work, r = run_apply(tmp_path, new_body="exit 3")
    assert not r["ok"] and r["rolled_back"] and "ripristinata" in r["error"]
    assert (app / "_internal" / "ver.txt").read_text() == "old" and (app / "mio_file_utente.txt").exists() and not backup.exists()


def test_apply_restores_old_folder_when_replacement_fails(tmp_path, monkeypatch):
    real = os.replace
    def flaky(a, b, *x, **k):
        if Path(a).name == "staging":
            raise OSError("disco pieno")
        return real(a, b, *x, **k)
    monkeypatch.setattr(apply_mod.os, "replace", flaky)
    monkeypatch.setattr(apply_mod.shutil, "copytree", lambda *a, **k: (_ for _ in ()).throw(OSError("disco pieno")))
    app, backup, work, r = run_apply(tmp_path)
    assert not r["ok"] and r["rolled_back"]
    assert (app / "_internal" / "ver.txt").read_text() == "old" and not backup.exists()


def test_apply_does_nothing_if_package_has_no_program(tmp_path):
    app = _tree(tmp_path / "RaceEngineerAI", "old")
    staging = tmp_path / "up" / "staging"; staging.mkdir(parents=True)
    work = tmp_path / "work"; work.mkdir()
    r = apply_mod.run(app=app, staging=staging, exe_name="app.sh", pid=0, version_from="0.6.7", version_to="0.7.0", work=work, app_args=[], watch_s=1, wait_s=1)
    assert not r["ok"] and (app / "_internal" / "ver.txt").read_text() == "old"


def test_apply_gives_up_if_the_app_does_not_close(tmp_path):
    import subprocess
    p = subprocess.Popen(["sleep", "30"])
    try:
        app = _tree(tmp_path / "RaceEngineerAI", "old")
        staging = _tree(tmp_path / "up" / "staging", "new")
        work = tmp_path / "work"; work.mkdir()
        r = apply_mod.run(app=app, staging=staging, exe_name="app.sh", pid=p.pid, version_from="0.6.7", version_to="0.7.0", work=work, app_args=[], watch_s=1, wait_s=1)
        assert not r["ok"] and "non si è chiusa" in r["error"] and (app / "_internal" / "ver.txt").read_text() == "old"
    finally:
        p.kill(); p.wait()


def test_helper_command_line_parses_app_arguments_after_double_dash(tmp_path):
    seen = {}
    real = apply_mod.run
    apply_mod.run = lambda **k: seen.update(k) or {"ok": True}
    try:
        apply_mod.main(["--app", "a", "--staging", "s", "--exe", "e", "--pid", "1", "--from", "1", "--to", "2", "--work", "w", "--", "--display-auto", "--port", "8765"])
    finally:
        apply_mod.run = real
    assert seen["app_args"] == ["--display-auto", "--port", "8765"]


def test_result_of_a_finished_update_is_shown_once(catalog, tmp_path, gh):
    m = manager(catalog, gh, tmp_path)
    (tmp_path / "work").mkdir(exist_ok=True)
    (tmp_path / "work" / "update_result.json").write_text('{"ok": true, "from": "0.6.7", "to": "0.7.0"}')
    assert m.status()["last_result"]["ok"] is True
    m.ack_result()
    assert m.status()["last_result"] is None
