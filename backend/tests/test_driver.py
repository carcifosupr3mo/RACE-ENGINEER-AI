import pytest
from fastapi.testclient import TestClient

from race_engineer.analysis import driver as drv
from race_engineer.api.app import create_app
from race_engineer.lmu.discovery import LmuInstall
from race_engineer.storage.catalog import Catalog
from race_engineer.acquisition.engine import AcquisitionEngine
from race_engineer.synthetic.game import SyntheticGame


def seed(tmp_path, scenarios, laps=5):
    cat = Catalog(tmp_path / "c.sqlite")
    for sc in scenarios:
        g = SyntheticGame(sc, laps=laps)
        e = AcquisitionEngine(lambda: g.backend, catalog=cat, data_root=tmp_path, process_probe=lambda: True, open_retry_s=0)
        while g.step():
            e.poll_once()
        e.stop()
    return cat


def test_history_hides_synthetic_by_default_and_groups(tmp_path):
    cat = seed(tmp_path, ["constant", "slower"])
    assert drv.history(cat)["groups"] == []
    h = drv.history(cat, include_synthetic=True, period="day")
    g = h["groups"][0]
    assert len(g["sessions"]) == 2 and len(g["series"]) == 1 and g["series"][0]["sessions"] == 2
    assert g["series"][0]["best_time_s"] == pytest.approx(min(s["best_time_s"] for s in g["sessions"]))


def test_goal_evaluation_and_progress(tmp_path):
    cat = seed(tmp_path, ["slower"])
    base = min(r for r in [drv.session_stats(cat.list_sessions()[0])["summary"]["best_time_s"]])
    gid = cat.add_goal("[SYNTHETIC] Test Circuit", "", "best_lap_s", base - 1.0, baseline=base)
    ev = drv.evaluate_goal(cat, cat.list_goals()[0])
    assert ev["achieved"] is False and ev["current"] is None and ev["sessions_considered"] == 0   # only sessions AFTER creation count
    # a faster session (constant, ~0.9 s quicker than 'slower') -> partial progress, goal not reached
    gid2 = cat.add_goal("[SYNTHETIC] Test Circuit", "", "best_lap_s", base - 0.5, baseline=base)
    import time; time.sleep(0.01)
    cat2 = seed(tmp_path, ["constant"])
    ev = drv.evaluate_goal(cat2, cat2.list_goals()[0])
    ev = next(drv.evaluate_goal(cat2, g) for g in cat2.list_goals() if g["id"] == gid)
    assert 0.5 < ev["progress"] < 1.0 and not ev["achieved"]
    assert next(drv.evaluate_goal(cat2, g) for g in cat2.list_goals() if g["id"] == gid2)["achieved"]


def test_training_targets_the_corner_that_really_varies(tmp_path):
    cat = seed(tmp_path, ["mixed"], laps=5)
    sid = cat.list_sessions()[0]["id"]
    plan = drv.training_plan(cat, sid)
    assert plan["available"]
    corners = [i["facts"]["corner"] for i in plan["items"]]
    assert "P2" in corners and "P3" in corners                      # the corners perturbed in laps 2 and 3
    assert all(i["facts"]["laps_compared"] >= 2 for i in plan["items"])


def test_training_unavailable_with_few_laps(tmp_path):
    cat = seed(tmp_path, ["constant"], laps=2)
    assert drv.training_plan(cat, cat.list_sessions()[0]["id"])["available"] is False


def test_api_endpoints(tmp_path):
    cat = seed(tmp_path, ["mixed"], laps=5)
    e2 = AcquisitionEngine(lambda: None, catalog=cat, data_root=tmp_path, record=False)
    c = TestClient(create_app(e2, cat, install=LmuInstall()), base_url="http://127.0.0.1")
    sid = cat.list_sessions()[0]["id"]
    assert c.get("/api/driver/history?include_synthetic=true&period=month").json()["groups"]
    assert c.get("/api/driver/history?period=year").status_code == 422
    r = c.post("/api/driver/goals", params={"track": "[SYNTHETIC] Test Circuit", "metric": "lap_std_s", "target": 0.05}).json()
    assert r["baseline"] is not None
    assert c.post("/api/driver/goals", params={"track": "x", "metric": "bogus", "target": 1}).status_code == 422
    assert c.get("/api/driver/goals").json()[0]["metric"] == "lap_std_s"
    assert c.get(f"/api/sessions/{sid}/training").json()["available"]
    assert c.get(f"/api/sessions/{sid}/fuel?target_laps=10").json()["available"]
    assert c.get(f"/api/sessions/{sid}/tyres").json()["available"]
