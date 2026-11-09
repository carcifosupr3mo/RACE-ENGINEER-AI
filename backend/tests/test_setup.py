import hashlib
import json

import pytest

from race_engineer.setup import advisor
from race_engineer.storage.catalog import Catalog
from race_engineer.importers.lmu_duckdb import LmuDuckdb
from race_engineer.synthetic.lmu_duckdb_fixture import build

# TEST FIXTURE ONLY: invented structure to exercise the generic parser. Real LMU setup format is unverified.
RAW = {"Chassis": {"BrakeBias": {"label": "Brake bias", "value": 55.0, "min": 50.0, "max": 60.0, "step": 0.5},
                   "RearDiff": {"label": "Diff power", "Value": 40, "Min": 0, "Max": 100, "Step": 5},
                   "FrontSpring": {"value": 100.0}},          # no limits => never proposable
       "Name": "test setup"}
FIND = lambda t, c="P2": {"type": t, "corner": c, "lap": 2, "evidence": {"diff_m": -40.0}}


@pytest.fixture
def cat(tmp_path):
    return Catalog(tmp_path / "c.sqlite")


def test_flatten_requires_verified_limits():
    params, loose = advisor.flatten(RAW)
    assert {p.path for p in params} == {"Chassis/BrakeBias", "Chassis/RearDiff"}
    assert any(l["path"] == "Chassis/FrontSpring/value" for l in loose)


def test_proposal_within_limits_one_step_and_not_applied(cat):
    sid = advisor.import_setup(cat, RAW, "test")["id"]
    out = advisor.advise(cat, sid, [FIND("early_braking")])
    p = out["proposals"][0]
    assert p["parameter"] == "Chassis/BrakeBias" and p["current"] == 55.0 and p["proposed"] == 54.5
    assert p["limits_verified"] == [50.0, 60.0] and p["auto_apply"] is False and p["confidence"] == "bassa"
    assert advisor.get_setup(cat, sid)["raw"] == RAW                  # stored verbatim, nothing modified


def test_clamped_at_limit(cat):
    raw = json.loads(json.dumps(RAW)); raw["Chassis"]["BrakeBias"]["value"] = 50.0
    sid = advisor.import_setup(cat, raw, "test")["id"]
    assert advisor.advise(cat, sid, [FIND("early_braking")])["proposals"] == []      # already at min: no out-of-range proposal


def test_no_numeric_proposal_without_limits_or_match(cat):
    sid = advisor.import_setup(cat, {"Chassis": {"BrakeBias": {"value": 55.0}}}, "test")
    assert "cannot propose" in sid["warning"]
    out = advisor.advise(cat, sid["id"], [FIND("early_braking"), FIND("late_throttle", "P3")])
    assert out["proposals"] == [] and all("none:" in h["proposal"] for h in out["hypotheses"])
    assert all(h["basis"] == "generic_knowledge" and "COMPATIBLE" in h["note"] for h in out["hypotheses"])


def test_unknown_finding_types_produce_nothing(cat):
    sid = advisor.import_setup(cat, RAW, "test")["id"]
    assert advisor.advise(cat, sid, [FIND("low_min_speed")])["hypotheses"] == []


def test_import_from_duckdb_metadata_keeps_original_untouched(cat, tmp_path):
    p = build(tmp_path / "lmu.duckdb")
    import duckdb
    con = duckdb.connect(str(p)); con.execute("INSERT INTO metadata VALUES ('CarSetup', ?)", [json.dumps(RAW)]); con.close()
    h = hashlib.sha256(p.read_bytes()).hexdigest()
    r = advisor.import_from_duckdb_metadata(cat, str(p))
    assert r["parameters_with_limits"] == 2 and hashlib.sha256(p.read_bytes()).hexdigest() == h
    q = build(tmp_path / "nosetup.duckdb")
    with pytest.raises(ValueError):
        advisor.import_from_duckdb_metadata(cat, str(q))


def test_api_setup_import_and_advice(tmp_path):
    from fastapi.testclient import TestClient
    from race_engineer.acquisition.engine import AcquisitionEngine
    from race_engineer.api.app import create_app
    from race_engineer.lmu.discovery import LmuInstall
    from race_engineer.synthetic.game import SyntheticGame
    cat = Catalog(tmp_path / "c.sqlite")
    g = SyntheticGame("mixed", laps=4)
    e = AcquisitionEngine(lambda: g.backend, catalog=cat, data_root=tmp_path, process_probe=lambda: True, open_retry_s=0)
    while g.step():
        e.poll_once()
    e.stop()
    sid = cat.list_sessions()[0]["id"]
    c = TestClient(create_app(AcquisitionEngine(lambda: None, catalog=cat, record=False), cat, install=LmuInstall()), base_url="http://127.0.0.1")
    r = c.post("/api/setups/import", json={"raw": RAW}).json()
    assert r["parameters_with_limits"] == 2
    a = c.get(f"/api/setups/{r['id']}/advice", params={"session_id": sid, "lap": 2}).json()
    assert any(p["parameter"] == "Chassis/BrakeBias" and p["proposed"] == 54.5 for p in a["proposals"])   # early braking in lap 2 (P2)
    assert c.post("/api/setups/import", json={}).status_code == 422
    assert c.get("/api/setups/nope/advice", params={"session_id": sid, "lap": 2}).status_code == 404
