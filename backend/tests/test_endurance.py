"""Endurance layer: detector, memory, pipeline, grounding guard, accelerated simulation (all SYNTHETIC)."""
import httpx

from race_engineer.ai.providers import AIRequestQueue, build_default_manager
from race_engineer.endurance import EndurancePipeline, EventDetector, RaceMemory, ungrounded_numbers
from race_engineer.synthetic.endurance_sim import KEYS, Car, FakeProviders, SimClock, run


def sample(t, **k):
    v = {"session_time_s": t, "lap_number": 1, "last_lap_time_s": 0.0, "fuel_l": 80.0, "in_pits": False, "rain": 0.0,
         "damage_dent_max": 0, "water_temp_c": 90.0, "oil_temp_c": 100.0}
    for w in ("fl", "fr", "rl", "rr"):
        v[f"tyre_{w}_temp_center_c"] = 90.0
        v[f"tyre_{w}_wear"] = 0.9
    v.update(k)
    return v


def kinds(evs):
    return [e.kind for e in evs]


def test_lap_completion_and_fuel_per_lap():
    d = EventDetector()
    d.feed(sample(0, fuel_l=100))
    evs = d.feed(sample(100, lap_number=2, last_lap_time_s=100.2, fuel_l=92.5))
    lap = [e for e in evs if e.kind == "lap_completed"][0]
    assert lap.data["time_s"] == 100.2 and lap.data["fuel_used_l"] == 7.5 and lap.data["valid"]
    assert d.fuel_per_lap() == 7.5 and d.best == 100.2


def test_fuel_low_and_critical_priorities():
    d = EventDetector()
    d.fuel_hist.extend([7.5, 7.5])
    assert "fuel_low" in kinds(d.feed(sample(0, fuel_l=20.0)))            # 2.7 laps
    assert "fuel_critical" in kinds(d.feed(sample(200, fuel_l=8.0)))       # 1.07 laps


def test_damage_is_edge_triggered_not_a_flood():
    d = EventDetector()
    n = 0
    for i in range(500):
        n += kinds(d.feed(sample(i * 0.5, damage_dent_max=1, in_pits=(i > 100)))).count("damage")
    assert n == 1
    assert kinds(d.feed(sample(300, damage_dent_max=2))).count("damage") == 1    # worse damage re-triggers
    d.feed(sample(301, damage_dent_max=0))
    assert kinds(d.feed(sample(302, damage_dent_max=1))).count("damage") == 1   # repaired then damaged again


def test_pit_in_out_creates_stint_end_and_new_stint():
    d = EventDetector()
    d.feed(sample(0))
    out = d.feed(sample(50, in_pits=True))
    assert "pit_in" in kinds(out) and "stint_end" in kinds(out)
    out = d.feed(sample(110, in_pits=False))
    assert "pit_out" in kinds(out) and d.stint == 2


def test_rain_hysteresis():
    d = EventDetector()
    assert "rain_start" in kinds(d.feed(sample(0, rain=0.3)))
    assert kinds(d.feed(sample(10, rain=0.1))) == []
    assert "rain_stop" in kinds(d.feed(sample(20, rain=0.02)))


def test_detector_state_roundtrip_prevents_refiring():
    d = EventDetector()
    d.feed(sample(0, damage_dent_max=1))
    d2 = EventDetector()
    d2.import_state(d.export_state())
    assert "damage" not in kinds(d2.feed(sample(5, damage_dent_max=1)))


def test_grounding_guard():
    p = {"state": {"lap": 12, "fuel_l": 43.2, "best_lap_s": 215.482}}
    assert ungrounded_numbers("Giro 12, carburante 43,2 L, migliore 3:35.482", p) == []
    assert ungrounded_numbers("Giro 12, gap 17.3 s", p) == ["17.3"]


def _pipe(tmp_path, fake=None):
    clock = SimClock()
    fake = fake or FakeProviders(clock)
    mgr = build_default_manager(tmp_path / "s.sqlite", transport=httpx.MockTransport(fake), key_overrides=KEYS, clock=clock)
    q = AIRequestQueue(tmp_path / "q.sqlite", mgr, clock=clock)
    mem = RaceMemory(tmp_path / "m.sqlite", clock=clock)
    return EndurancePipeline(mem, q, "S1", summary_interval_s=300), q, mem, clock, fake


def test_pipeline_local_memory_fills_even_when_every_provider_is_down(tmp_path):
    clock = SimClock()

    class Down(FakeProviders):
        def __call__(self, request):
            raise httpx.ConnectError("no internet")
    pipe, q, mem, clock, fake = _pipe(tmp_path, Down(clock))
    pipe.mgr = None
    car, rng_t = Car(__import__("random").Random(1)), 0.0
    for i in range(int(3000 / 0.1)):
        clock.t += 0.1
        pipe.on_sample(car.step(0.1, clock.race() / 3600))
        if i % 10 == 0:
            q.pump()
    assert mem.lap_count("S1") >= 25                       # laps still recorded
    srcs = {s["source"] for s in mem.summaries("S1", limit=1000)}
    assert srcs == {"local"}                               # race continues with local analysis only
    assert q.pending() >= 1                                # AI requests wait (and will go stale) instead of blocking anything


def test_ungrounded_ai_text_is_rejected_and_local_kept(tmp_path):
    class Liar(FakeProviders):
        def __call__(self, request):
            return httpx.Response(200, json={"choices": [{"message": {"content": "Distacco di 777.7 secondi dal leader."}}],
                                             "usage": {"prompt_tokens": 10, "completion_tokens": 10}})
    clock = SimClock()
    pipe, q, mem, clock, _ = _pipe(tmp_path, Liar(clock))
    car = Car(__import__("random").Random(2))
    for i in range(int(700 / 0.1)):
        clock.t += 0.1
        pipe.on_sample(car.step(0.1, clock.race() / 3600))
        if i % 10 == 0:
            q.pump()
    st = {(s["source"].split(":")[0], s["status"]) for s in mem.summaries("S1", limit=1000)}
    assert ("ai", "rejected_ungrounded") in st and ("ai", "ok") not in st and ("local", "ok") in st


def test_accelerated_simulation_short_run(tmp_path):
    rep = run(hours=4, out_dir=tmp_path, restarts_at_h=(2.5,), say=lambda *_: None)
    assert all(v in (True, None) for v in rep["checks"].values()), rep["checks"]
    assert rep["restarts"][0]["memory_identical"]
    assert rep["ai"]["accepted"] > 20 and rep["samples_generated"] == 4 * 36000


def test_service_wires_engine_to_memory_with_synthetic_game(tmp_path):
    from race_engineer.acquisition.engine import AcquisitionEngine
    from race_engineer.endurance.service import EnduranceService
    from race_engineer.storage.catalog import Catalog
    from race_engineer.synthetic.game import SyntheticGame
    cat = Catalog(tmp_path / "c.sqlite")
    g = SyntheticGame("constant", laps=3)
    e = AcquisitionEngine(lambda: g.backend, catalog=cat, data_root=tmp_path, process_probe=lambda: True, open_retry_s=0)
    svc = EnduranceService(e, cat, tmp_path)
    while g.step():
        e.poll_once()
    e.stop()
    st = svc.status()
    assert st["memory"]["laps"] >= 2 and st["memory"]["summaries"] >= 1
    assert st["ai_queue"] is None                       # synthetic sessions / AI disabled: local only, no quota spent
    assert not [x for x in e.stats.errors if "listener" in x["msg"]]
