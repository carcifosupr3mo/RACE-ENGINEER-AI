import sqlite3

import pytest
from fastapi.testclient import TestClient

from race_engineer import sims
from race_engineer.api.app import create_app
from race_engineer.lmu.discovery import LmuInstall
from race_engineer.storage.catalog import MIGRATIONS, Catalog
from race_engineer.synthetic.game import SyntheticGame
from race_engineer.updater.manager import UpdateManager

from .conftest import make_engine
from .fake_github import FakeGithub


@pytest.fixture
def env(tmp_path, catalog):
    g = SyntheticGame("constant", laps=1)
    e = make_engine(g, tmp_path, catalog)
    yield g, e, tmp_path, catalog
    e.stop()


def client(e, catalog, **kw):
    return TestClient(create_app(e, catalog, install=LmuInstall(), **kw), base_url="http://127.0.0.1")


# ------------------------------------------------------------------ simulators
def test_first_start_has_no_selection_and_lists_all_ten(env):
    g, e, tmp, cat = env
    d = client(e, cat).get("/api/sims").json()
    assert d["first_run"] is True and d["selected"] is None and d["connection"] is None
    ids = [s["id"] for s in d["sims"]]
    assert ids == ["lmu", "acc", "ac", "ac_evo", "iracing", "rf2", "ams2", "r3e", "f1", "pcars2"]
    assert [s["id"] for s in d["sims"] if s["selectable"]] == ["lmu"]          # only what can really be read
    assert all(s["status_label"] and s["tech"] for s in d["sims"])


def test_selecting_lmu_is_saved_and_survives_restart(env):
    g, e, tmp, cat = env
    c = client(e, cat)
    r = c.put("/api/sims/selected", json={"id": "lmu"}).json()
    assert r["selected"] == "lmu" and r["first_run"] is False and r["connection"]["label"]
    cat.close()
    cat2 = Catalog(tmp / "catalog.sqlite")                                       # "app restart"
    c2 = client(e, cat2)
    assert c2.get("/api/sims").json()["selected"] == "lmu"
    assert c2.app.state.active_sim == "lmu"                                      # restored at start, nothing to choose again
    cat2.close()


def test_unsupported_and_unknown_sims_cannot_be_selected(env):
    g, e, tmp, cat = env
    c = client(e, cat)
    for sid in ("iracing", "acc", "ac_evo", "f1"):
        r = c.put("/api/sims/selected", json={"id": sid})
        assert r.status_code == 409 and "non è ancora supportato" in r.json()["detail"]
    assert c.put("/api/sims/selected", json={"id": "nope"}).status_code == 404
    assert c.get("/api/sims").json()["selected"] is None


def test_stored_choice_of_a_non_supported_sim_is_ignored(env):
    g, e, tmp, cat = env
    cat.put_setting(sims.SELECTED_KEY, "iracing")
    assert client(e, cat).get("/api/sims").json()["selected"] is None


def test_sessions_and_goals_are_separated_per_simulator(env):
    g, e, tmp, cat = env
    class Ctx: track_name = "Monza"; vehicle_name = "X"; vehicle_class = "H"; session_type = "P"; session_code = 1; game_version = 1; track_length_m = 5000.0
    a = cat.create_session(source="lmu_shm", is_synthetic=False, data_path="a", ctx=Ctx())
    b = cat.create_session(source="x", is_synthetic=False, data_path="b", ctx=Ctx(), sim="iracing")
    cat.add_goal("Monza", "X", "best_lap_s", 90.0)
    cat.add_goal("Monza", "X", "best_lap_s", 80.0, sim="iracing")
    c = client(e, cat)
    c.put("/api/sims/selected", json={"id": "lmu"})
    ids = {r["id"] for r in c.get("/api/sessions").json()}
    assert a in ids and b not in ids
    assert {r["id"] for r in c.get("/api/sessions?sim=iracing").json()} == {b}
    assert {r["id"] for r in c.get("/api/sessions?sim=all").json()} >= {a, b}
    assert [x["target"] for x in c.get("/api/driver/goals").json()] == [90.0]
    cat.put_sim_setting("lmu", "units", "metric"); cat.put_sim_setting("iracing", "units", "imperial")
    assert cat.get_sim_setting("lmu", "units") == "metric" and cat.get_sim_setting("iracing", "units") == "imperial"


def test_connection_text_is_plain_language(env):
    g, e, tmp, cat = env
    c = client(e, cat)
    r = c.put("/api/sims/selected", json={"id": "lmu"}).json()
    assert r["connection"]["state"] in ("ok", "waiting", "problem")
    for s in r["sims"]:
        if s["id"] != "lmu":
            assert s["connection"] is None


# ------------------------------------------------------------------ catalog migration keeps user data
def test_migration_to_v6_keeps_existing_rows_and_makes_a_backup(tmp_path):
    p = tmp_path / "old.sqlite"
    db = sqlite3.connect(p)
    db.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at REAL)")
    for ver, sql in MIGRATIONS:
        if ver <= 5:
            db.executescript("BEGIN;" + sql); db.execute("INSERT INTO schema_migrations VALUES (?,0)", (ver,))
    db.execute("INSERT INTO sessions(id,started_at,source,status,data_path,track) VALUES ('s1',1,'lmu_shm','complete','p','Monza')")
    db.execute("INSERT INTO goals(created_at,track,metric,target) VALUES (1,'Monza','best_lap_s',90)")
    db.execute("INSERT INTO settings VALUES ('keep','\"me\"')")
    db.commit(); db.close()
    cat = Catalog(p)
    assert cat.schema_version() == 6
    assert cat.get_session("s1")["sim"] == "lmu" and cat.list_goals()[0]["sim"] == "lmu" and cat.get_setting("keep") == "me"
    assert (tmp_path / "old.sqlite.before-v6.bak").exists()
    cat.close()


# ------------------------------------------------------------------ update API
def test_update_api_flow(env, tmp_path):
    g, e, tmp, cat = env
    gh = FakeGithub()
    calls = []
    inst = tmp_path / "inst"; inst.mkdir(); (inst / "RaceEngineerUpdater.exe").write_bytes(b"u")
    um = UpdateManager(cat, "0.6.7", tmp_path / "w", policy=gh.policy, api_base=gh.base, platform="win32", frozen=True, install_dir=inst, launcher=calls.append)
    c = client(e, cat, updater=um)
    assert c.get("/api/update/status").json()["state"] == "idle"
    assert c.put("/api/update/auto", json={"enabled": True}).json()["auto"] is True
    assert c.put("/api/update/auto", json={"enabled": False}).json()["auto"] is False
    st = c.post("/api/update/check").json()
    assert st["state"] == "available" and st["latest"] == "0.7.0" and st["current"] == "0.6.7"
    assert c.post("/api/update/skip").json()["dismissed"] is True
    assert c.post("/api/update/start").json()["state"] in ("downloading", "verifying", "installing", "restarting")
    import time
    t0 = time.time()
    while not calls and time.time() - t0 < 20:
        time.sleep(0.05)
    assert calls
    gh.close()


def test_update_start_without_available_release_is_a_clear_409(env):
    g, e, tmp, cat = env
    r = client(e, cat).post("/api/update/start")
    assert r.status_code == 409 and r.json()["detail"]
