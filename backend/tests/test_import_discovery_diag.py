import hashlib
import json
from pathlib import Path

import duckdb
import pytest

from race_engineer.importers.lmu_duckdb import LmuDuckdb
from race_engineer.lmu import layout as L
from race_engineer.lmu.diagnostics import build_report, header_field_drift
from race_engineer.lmu.discovery import LmuInstall, find_install, scan_plugin_settings
from race_engineer.synthetic.lmu_duckdb_fixture import build


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def test_import_inspect_and_original_untouched(tmp_path):
    p = build(tmp_path / "a.duckdb")
    before = sha(p)
    with LmuDuckdb(p) as d:
        r = d.inspect()
        assert r.ok and not r.problems and r.metadata["TrackName"].startswith("[SYNTHETIC]")
        speed = d.read_channel("Ground Speed")
        assert speed["unit"] == "km/h" and speed["t_rel_s"][1] == pytest.approx(0.01)
        assert speed["provenance"] == "duckdb_import"
        with pytest.raises(duckdb.Error):
            d.con.execute('INSERT INTO "Lap" VALUES (1.0, 1)')       # read-only enforced
        ev = d.read_events("Lap")
        assert [row[1] for row in ev["rows"]][:2] == [1, 2]
    assert sha(p) == before


def test_missing_channels_are_reported_not_invented(tmp_path):
    p = build(tmp_path / "b.duckdb", drop_channels=("Brake Pos", "Lap Dist"))
    with LmuDuckdb(p) as d:
        r = d.inspect()
    assert set(r.missing_core_channels) == {"Brake Pos", "Lap Dist"}
    assert any("core channels missing" in x for x in r.problems)


def test_truncated_channel_flagged_as_inconsistent(tmp_path):
    p = build(tmp_path / "c.duckdb", truncate=("Ground Speed", 2000))
    with LmuDuckdb(p) as d:
        r = d.inspect()
    assert any(x.startswith("Ground Speed") for x in r.duration_inconsistency)


def test_foreign_duckdb_is_rejected_gracefully(tmp_path):
    p = tmp_path / "foreign.duckdb"
    con = duckdb.connect(str(p)); con.execute("create table t(a int)"); con.close()
    with LmuDuckdb(p) as d:
        r = d.inspect()
    assert r.ok is False and any("catalog table" in x for x in r.problems)


def test_copy_first_leaves_no_residue(tmp_path):
    p = build(tmp_path / "d.duckdb")
    d = LmuDuckdb(p, copy_first=True); tmpdir = d._tmp.parent
    assert tmpdir.exists(); d.close(); assert not tmpdir.exists()


def make_fake_steam(root: Path, with_telemetry=True):
    lib = root / "Steam"
    game = lib / "steamapps" / "common" / "Le Mans Ultimate"
    (game / "UserData" / "player").mkdir(parents=True)
    (game / "Support" / "SharedMemoryInterface").mkdir(parents=True)
    (lib / "steamapps" / "appmanifest_1.acf").write_text('"AppState"\n{\n "installdir" "Le Mans Ultimate"\n "buildid" "12345"\n "LastUpdated" "1700000000"\n}')
    (game / "UserData" / "player" / "Settings.JSON").write_text(json.dumps({"Game Options": {"Enable Plugins": 1, "Other": 3}}))
    if with_telemetry:
        tel = game / "UserData" / "Telemetry"; tel.mkdir()
        (tel / "config.json").write_text("{}")
        build(tel / "Spa_P_2026-01-01T00_00_00Z.duckdb")
    return lib, game


def test_discovery_finds_everything(tmp_path):
    lib, game = make_fake_steam(tmp_path)
    inst = find_install(roots=[lib])
    assert inst.found and inst.game_dir == str(game) and inst.steam_build_id == "12345"
    assert inst.telemetry_dir.endswith("Telemetry") and inst.telemetry_config and len(inst.duckdb_files) == 1
    assert inst.shared_memory_header_dir
    assert inst.plugin_setting_hints and inst.plugin_setting_hints[0]["key"].endswith("Enable Plugins")


def test_discovery_not_found_has_clear_note(tmp_path, monkeypatch):
    monkeypatch.delenv("LMU_GAME_DIR", raising=False)
    inst = find_install(roots=[tmp_path / "nothing"])
    assert not inst.found and any("not found" in n for n in inst.notes)


def test_discovery_reads_second_steam_library(tmp_path):
    root = tmp_path / "Steam"; (root / "steamapps").mkdir(parents=True)
    other = tmp_path / "Games"; game = other / "steamapps" / "common" / "Le Mans Ultimate"; game.mkdir(parents=True)
    (root / "steamapps" / "libraryfolders.vdf").write_text('"libraryfolders"{"0"{"path" "%s"}}' % str(other).replace("\\", "\\\\"))
    assert find_install(roots=[root]).game_dir == str(game)


def test_report_tells_user_how_to_enable_plugins_when_mapping_missing():
    rep = build_report(LmuInstall(), True, None, "OpenFileMappingW failed", None, "win32")
    m = next(c for c in rep.checks if c.id == "mapping")
    assert m.ok is False and "Enable Plugins" in m.fix and "restart" in m.fix.lower()
    assert "never changes game settings" in m.fix


def test_report_flags_size_mismatch_and_synthetic():
    rep = build_report(LmuInstall(), True, L.MAPPING_SIZE - 1000, None, 1, "win32")
    assert next(c for c in rep.checks if c.id == "mapping_size").ok is False
    syn = build_report(LmuInstall(), None, L.MAPPING_SIZE, None, 0, "linux", synthetic=True)
    assert next(c for c in syn.checks if c.id == "mapping").ok is None and "SYNTHETIC" in syn.verdict


def test_header_drift_detects_renamed_fields(tmp_path):
    names = set()
    for cls in (L.Wheel, L.VehicleTelemetry, L.VehicleScoring, L.ScoringInfo, L.AppState, L.Generic, L.TelemetryData, L.ScoringData):
        names |= {n for n, _ in cls._fields_}
    (tmp_path / "InternalsPlugin.hpp").write_text(" ".join(sorted(names - {"mUnfilteredThrottle"})))
    d = header_field_drift(tmp_path)
    assert d["checked"] and d["missing_in_header"] == ["mUnfilteredThrottle"]
