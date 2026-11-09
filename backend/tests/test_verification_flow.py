"""Preflight / verify (source check) / HUD comparison / summary - all offline, no LMU, SYNTHETIC inputs only."""
import json
import sys
import time
from pathlib import Path

import duckdb
import pytest

from race_engineer.__main__ import main
from race_engineer.lmu import hud, summary
from race_engineer.synthetic.game import SyntheticGame
from race_engineer.synthetic.lmu_duckdb_fixture import build


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("RACE_ENGINEER_DATA", str(tmp_path / "data"))
    game = tmp_path / "game" / "Le Mans Ultimate"
    (game / "UserData" / "Telemetry").mkdir(parents=True)
    (game / "UserData" / "player" / "Settings").mkdir(parents=True)
    monkeypatch.setenv("LMU_GAME_DIR", str(game))
    return tmp_path, game


def _shm_file(tmp_path) -> Path:
    g = SyntheticGame("constant", laps=2)
    for _ in range(300):
        g.step()
    p = tmp_path / "fake_lmu_data.bin"
    p.write_bytes(bytes(g.buf))
    return p


def test_preflight_reports_missing_things_and_never_requires_keys(env, capsys):
    tmp_path, game = env
    assert main(["preflight", "--shm-path", str(tmp_path / "nonexistent.bin")]) == 0
    r = json.loads(capsys.readouterr().out)
    assert r["data_dir"]["writable"] and r["reports_dir"]["writable"]
    assert r["lmu_install"]["found"] and r["mapping"]["present"] is False
    assert any(x.startswith("lmu_data_mapping") for x in r["missing"])
    assert r["duckdb_files"] == [] and r["setup_files"] == []
    assert "api" not in json.dumps(r).lower().replace("api key", "")  # no AI/key concept in the preflight


def test_preflight_finds_duckdb_and_setups_newest_first(env, capsys):
    tmp_path, game = env
    a = build(game / "UserData" / "Telemetry" / "old.duckdb", "constant", laps=1)
    time.sleep(0.05)
    b = build(game / "UserData" / "Telemetry" / "new.duckdb", "constant", laps=1)
    s1 = game / "UserData" / "player" / "Settings" / "a.svm"; s1.write_text("[GENERAL]\nNotes=x\n")
    assert main(["preflight", "--shm-path", str(_shm_file(tmp_path))]) == 0
    r = json.loads(capsys.readouterr().out)
    assert r["mapping"]["present"] and r["mapping"]["size"] > 300000
    assert [Path(f["path"]).name for f in r["duckdb_files"]] == ["new.duckdb", "old.duckdb"]
    assert [Path(p).name for p in r["setup_files"]] == ["a.svm"]


def test_file_override_is_never_a_real_lmu_verification_even_on_windows(env, monkeypatch):
    """A file/bridge source on 'Windows' with flowing samples must NOT yield the REAL verdict."""
    tmp_path, _ = env
    from race_engineer.lmu import verify
    monkeypatch.setattr(verify.sys, "platform", "win32")
    monkeypatch.setattr(verify, "is_lmu_process_running", lambda: True)
    rep, md = verify.run(seconds=2, out_dir=tmp_path / "rep", shm_path=str(_shm_file(tmp_path)), say=lambda *_: None)
    assert not rep["verdict"].startswith("REAL LMU VERIFIED")
    ids = {c["id"]: c["ok"] for c in rep["checks"]}
    assert ids.get("real_data_source") is False
    assert "NOT real" in rep["data_source"] or "NOT REAL" in rep["data_source"].upper()
    assert rep["recording"]["run_name"] and rep["app"]["version"]


def _recording(tmp_path):
    """A SYNTHETIC recording shaped like a verify run: samples with wall_time."""
    run = tmp_path / "data" / "verify_runs" / "20260101_000000"
    run.mkdir(parents=True)
    con = duckdb.connect(str(run / "rec.duckdb"))
    con.execute("create table samples(wall_time double, speed_kmh double, rpm double, throttle double, brake double, gear int, lap_number int)")
    t0 = 1_700_000_000.0
    for i in range(600):                                    # 60 s at 10 Hz, accelerating 0 -> 200 km/h, gear 3, lap 2
        t = t0 + i / 10
        con.execute("insert into samples values (?,?,?,?,?,?,?)", [t, i / 3.0, 3000 + i * 8, 1.0, 0.0, 3, 2])
    con.close()
    vr = tmp_path / "verify.json"
    vr.write_text(json.dumps({"recording": {"run_name": "20260101_000000", "data_file": "rec.duckdb"}, "data_source": "SYNTHETIC test",
                              "checks": [], "verdict": "NOT VERIFIED", "app": {"version": "0.1.0"}}))
    return t0, vr


def test_hud_compare_tolerates_latency_and_rounding(tmp_path, monkeypatch):
    t0, vr = _recording(tmp_path)
    monkeypatch.setenv("RACE_ENGINEER_DATA", str(tmp_path / "data"))
    ann = [{"epoch": t0 + s + 0.4, "speed_kmh": round(s * 10 / 3.0 + 2), "rpm": round(3000 + s * 80 - 60), "gear": 3, "lap": 2,
            "throttle_pct": 98, "brake_pct": 0} for s in (10, 20, 30, 40)]   # HUD slightly off in time/rounding
    f = tmp_path / "ann.json"; f.write_text(json.dumps(ann))
    rep, md = hud.run(f, vr, out_dir=tmp_path / "out")
    assert rep["verdict"] == "HUD COMPARISON PASSED", rep["reasons"]
    assert md.is_file() and (tmp_path / "out").glob("hud_comparison_*.json")


def test_hud_compare_detects_wrong_channel_and_needs_motion(tmp_path, monkeypatch):
    t0, vr = _recording(tmp_path)
    monkeypatch.setenv("RACE_ENGINEER_DATA", str(tmp_path / "data"))
    bad = [{"epoch": t0 + s, "speed_kmh": 20, "gear": 5} for s in (10, 20, 30)]      # HUD says 20 km/h, gear 5: recording says otherwise
    f = tmp_path / "bad.json"; f.write_text(json.dumps(bad))
    rep, _ = hud.run(f, vr, out_dir=tmp_path / "out")
    assert rep["verdict"] == "HUD COMPARISON NOT PASSED" and any("below" in r for r in rep["reasons"])
    still = [{"epoch": t0 + 0.2 * k, "speed_kmh": 0, "gear": 3} for k in range(3)]
    f2 = tmp_path / "still.json"; f2.write_text(json.dumps(still))
    rep2, _ = hud.run(f2, vr, out_dir=tmp_path / "out")
    assert any("while moving" in r for r in rep2["reasons"])


def test_hud_constant_lap_offset_is_flagged_as_convention_not_hidden(tmp_path, monkeypatch):
    t0, vr = _recording(tmp_path)
    monkeypatch.setenv("RACE_ENGINEER_DATA", str(tmp_path / "data"))
    ann = [{"epoch": t0 + s, "speed_kmh": round(s * 10 / 3.0), "lap": 3} for s in (10, 20, 30)]   # HUD lap = recorded + 1
    f = tmp_path / "a.json"; f.write_text(json.dumps(ann))
    rep, _ = hud.run(f, vr, out_dir=tmp_path / "out")
    assert rep["verdict"] == "HUD COMPARISON NOT PASSED" and any("+1" in n for n in rep["notes"])


def test_summary_never_declares_phase1_complete_and_labels_missing(tmp_path):
    s = summary.build(verify=None)
    assert s["phase1"]["declared_complete"] is False and "NOT COMPLETE" in s["phase1"]["status"]
    assert s["data_origin"] == "NO RECORDING" and s["verify"] == {"run": False}
    # even with every criterion met the tool only says 'criteria met', never 'complete'
    v = tmp_path / "v.json"
    v.write_text(json.dumps({"verdict": "REAL LMU VERIFIED (automatic checks) - manual HUD comparison still required",
                             "checks": [{"id": "real_data_source", "ok": True, "title": "t", "detail": ""}], "app": {"version": "1"}}))
    h = tmp_path / "h.json"; h.write_text(json.dumps({"verdict": "HUD COMPARISON PASSED", "reasons": [], "per_field": {}}))
    s2 = summary.build(verify=v, hud=h)
    assert s2["phase1"]["declared_complete"] is False and s2["phase1"]["status"].startswith("ACCEPTANCE CRITERIA MET")
    o = tmp_path / "o.json"; o.write_text(json.dumps({"checked": True, "all_unchanged": False}))
    assert "NOT COMPLETE" in summary.build(verify=v, hud=h, originals=o)["phase1"]["status"]


def test_summary_cli_writes_reports(env, capsys):
    tmp_path, _ = env
    assert main(["verification-summary", "--out", str(tmp_path / "o")]) == 0
    out = list((tmp_path / "o").glob("verification_summary_*.md"))
    assert out and "NOT COMPLETE" in out[0].read_text(encoding="utf-8")


def test_unreachable_mapping_exit_code_is_not_success(env, capsys):
    tmp_path, _ = env
    rc = main(["verify-lmu", "--seconds", "1", "--shm-path", str(tmp_path / "missing.bin"), "--out", str(tmp_path / "o")])
    assert rc == 3 and "NOT VERIFIED" in capsys.readouterr().out


def test_reports_are_never_overwritten(tmp_path):
    from race_engineer.storage.paths import unique_stem
    (tmp_path / "x_20260101_000000.md").write_text("old")
    import time
    t = time.strftime("%Y%m%d_%H%M%S")
    (tmp_path / f"x_{t}.md").write_text("old2")
    s = unique_stem(tmp_path, "x_")
    assert s != f"x_{t}" and not list(tmp_path.glob(s + ".*"))


def test_reports_never_contain_the_user_name(tmp_path, monkeypatch):
    """Windows-style user paths in every report (md AND json, including JSON-escaped backslashes) are shortened."""
    base = tmp_path / "Users" / "SomeDriver42" / "AppData"
    base.mkdir(parents=True)
    monkeypatch.setenv("RACE_ENGINEER_DATA", str(base / "data"))
    game = base / "Le Mans Ultimate"
    (game / "UserData" / "Telemetry").mkdir(parents=True)
    (game / "UserData" / "player" / "Settings").mkdir(parents=True)
    monkeypatch.setenv("LMU_GAME_DIR", str(game))
    db = build(game / "UserData" / "Telemetry" / "s.duckdb", "constant", laps=1)
    svm = game / "UserData" / "player" / "Settings" / "t.svm"; svm.write_text("[GENERAL]\nNotes=x\n")
    out = base / "data" / "reports"
    shm = _shm_file(base)
    assert main(["preflight", "--shm-path", str(shm), "--save", str(out / "pf.json")]) == 0
    main(["verify-lmu", "--seconds", "1", "--shm-path", str(shm), "--out", str(out)])
    main(["duckdb-report", str(db), "--out", str(out)])
    main(["setup-inspect", str(svm), "--out", str(out)])
    v = sorted(out.glob("lmu_verification_*.json"))[0]
    main(["verification-summary", "--out", str(out), "--verify", str(v), "--preflight", str(out / "pf.json")])
    texts = {p.name: p.read_text(encoding="utf-8") for p in out.iterdir() if p.is_file()}
    assert len(texts) >= 9
    assert [n for n, t in texts.items() if "SomeDriver42" in t] == []
    assert main(["preflight", "--save", str(out / "pf.json")]) == 2          # never overwrites
