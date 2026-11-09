"""Multi-provider AI layer with FAKE HTTP transports (no network, no keys)."""
import httpx
import pytest

from race_engineer.ai.providers import (AIRequest, AIRequestQueue, AllProvidersUnavailable, Priority, build_default_manager)
from race_engineer.ai.providers.adapters import GroqAdapter, NVIDIAAdapter
from race_engineer.ai.providers.credentials import key_status, redact, resolve_key

KEYS = {"nvidia": "nvapi-TESTKEY0123456789", "groq": "gsk_TESTKEY0123456789"}


class Fake:
    """Programmable provider backend keyed by host+model. script[(host, model)] = list of behaviours consumed in order (last repeats)."""
    def __init__(self):
        self.script, self.calls = {}, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        import json
        body = json.loads(request.content or b"{}")
        host, model = request.url.host, body.get("model", "")
        self.calls.append((host, model))
        seq = self.script.get((host, model)) or self.script.get((host, "*")) or ["ok"]
        beh = seq.pop(0) if len(seq) > 1 else seq[0]
        if beh == "ok":
            return httpx.Response(200, json={"choices": [{"message": {"content": f"<think>x</think>reply from {model}"}}],
                                             "usage": {"prompt_tokens": 100, "completion_tokens": 50}},
                                  headers={"x-ratelimit-remaining-requests": "900", "x-ratelimit-remaining-tokens": "5000"})
        if beh == "timeout":
            raise httpx.ReadTimeout("slow")
        if beh == "drop":
            raise httpx.ConnectError("connection dropped")
        if isinstance(beh, tuple):
            st, hdr = beh
            return httpx.Response(st, text=f"err {st} Bearer {KEYS['nvidia']}", headers=hdr)
        return httpx.Response(beh, text="err")


class Clock:
    def __init__(self): self.t = 1_000_000.0
    def __call__(self): return self.t
    def adv(self, s): self.t += s


def mk(tmp_path, fake=None, clock=None, cfg=None):
    fake = fake or Fake()
    clock = clock or Clock()
    m = build_default_manager(tmp_path / "q.sqlite", cfg, transport=httpx.MockTransport(fake), key_overrides=KEYS, clock=clock)
    return m, fake, clock


REQ = lambda **k: AIRequest(kind=k.pop("kind", "periodic_summary"), system="sys", user="usr", **k)  # noqa: E731
NV, GQ = "integrate.api.nvidia.com", "api.groq.com"
NVM, G1, G2 = "nvidia/nemotron-3.5-lightning-30b-a3b", "openai/gpt-oss-120b", "qwen/qwen3.8-27b"


def test_primary_nvidia_answers_and_think_is_stripped(tmp_path):
    m, f, _ = mk(tmp_path)
    r = m.complete(REQ())
    assert r.provider == "nvidia" and r.text == f"reply from {NVM}" and r.fallback_depth == 0
    assert f.calls == [(NV, NVM)]


def test_429_falls_back_to_groq_and_nvidia_is_blocked_for_retry_after(tmp_path):
    f = Fake(); f.script[(NV, NVM)] = [(429, {"retry-after": "90"})]
    m, f, c = mk(tmp_path, f)
    r = m.complete(REQ())
    assert r.provider == "groq" and r.model == G1 and r.fallback_depth == 1
    n = len(f.calls)
    m.complete(REQ())
    assert (NV, NVM) not in f.calls[n:]          # NVIDIA not hammered while blocked
    c.adv(100)
    f.script[(NV, NVM)] = ["ok"]
    assert m.complete(REQ()).provider == "nvidia"  # recovery after the cool-down (probe succeeds)
    assert m.health.snapshot()[f"nvidia:{NVM}"]["state"] == "ok"


@pytest.mark.parametrize("beh", [500, 503, "timeout", "drop"])
def test_transient_errors_fall_through_chain_to_qwen(tmp_path, beh):
    f = Fake(); f.script[(NV, NVM)] = [beh]; f.script[(GQ, G1)] = [beh]
    m, f, _ = mk(tmp_path, f)
    assert m.complete(REQ()).model == G2


def test_all_down_raises_so_caller_uses_local(tmp_path):
    f = Fake(); f.script[(NV, "*")] = [500]; f.script[(GQ, "*")] = [500]
    m, f, _ = mk(tmp_path, f)
    with pytest.raises(AllProvidersUnavailable):
        m.complete(REQ())
    assert m.stats.local_fallbacks == 1


def test_auth_error_stops_retrying_for_an_hour(tmp_path):
    f = Fake(); f.script[(NV, NVM)] = [401]
    m, f, c = mk(tmp_path, f)
    m.complete(REQ())
    c.adv(600)
    n = sum(1 for x in f.calls if x == (NV, NVM))
    m.complete(REQ())
    assert sum(1 for x in f.calls if x == (NV, NVM)) == n


def test_quota_is_checked_before_calling(tmp_path):
    cfg = {"nvidia": {"limits": {NVM: {"rpm": 2, "reserve": 1.0}}}}
    m, f, c = mk(tmp_path, cfg=cfg)
    for _ in range(2):
        assert m.complete(REQ()).provider == "nvidia"
    assert m.complete(REQ()).provider == "groq"     # 3rd request within the minute goes to Groq without touching NVIDIA
    assert [x for x in f.calls if x[0] == NV] == [(NV, NVM)] * 2
    c.adv(61)
    assert m.complete(REQ()).provider == "nvidia"


def test_provider_header_zero_remaining_blocks_route(tmp_path):
    class F2(Fake):
        def __call__(self, request):
            r = super().__call__(request)
            return httpx.Response(200, json=r.json(), headers={"x-ratelimit-remaining-requests": "0"})
    m, _, _ = mk(tmp_path, F2())
    m.complete(REQ())
    assert m.complete(REQ()).provider == "groq"


def test_never_calls_a_model_outside_allowed_list(tmp_path):
    cfg = {"nvidia": {"model": "nvidia/some-paid-model", "allowed_models": [NVM]}}
    m, f, _ = mk(tmp_path, cfg=cfg)
    r = m.complete(REQ())
    assert not any(c[1] == "nvidia/some-paid-model" for c in f.calls)
    assert r.provider == "groq"


def test_nvidia_alternative_requires_free_confirmation(tmp_path):
    m, _, _ = mk(tmp_path, cfg={"nvidia": {"alternative_model": "nvidia/other"}})
    assert [r.key for r in m.routes][:2] == [f"nvidia:{NVM}", f"groq:{G1}"]
    m2, _, _ = mk(tmp_path / "x" if False else tmp_path, cfg={"nvidia": {"alternative_model": "nvidia/other", "alternative_confirmed_free": True}})
    assert [r.key for r in m2.routes][:3] == [f"nvidia:{NVM}", "nvidia:nvidia/other", f"groq:{G1}"]


def test_no_keys_means_local_and_no_http(tmp_path, monkeypatch):
    for k in ("NVIDIA_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    f = Fake()
    m = build_default_manager(tmp_path / "q.sqlite", transport=httpx.MockTransport(f))
    with pytest.raises(AllProvidersUnavailable):
        m.complete(REQ())
    assert f.calls == []


def test_keys_never_appear_in_status_or_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", KEYS["nvidia"])
    s = key_status("nvidia")
    assert s == {"provider": "nvidia", "configured": True, "source": "env:NVIDIA_API_KEY", "keyring_available": s["keyring_available"]}
    assert resolve_key("nvidia")[0] == KEYS["nvidia"]
    assert KEYS["nvidia"] not in redact(f"failed with Bearer {KEYS['nvidia']} and {KEYS['nvidia']}")
    f = Fake(); f.script[(NV, NVM)] = [400]
    m, _, _ = mk(tmp_path, f)
    with pytest.raises(AllProvidersUnavailable) as e:
        m.complete(REQ())
    import json
    assert KEYS["nvidia"] not in str(e.value) + json.dumps(m.status(), default=str)


def test_bad_request_is_not_retried_on_other_providers(tmp_path):
    f = Fake(); f.script[(NV, NVM)] = [400]
    m, f, _ = mk(tmp_path, f)
    with pytest.raises(AllProvidersUnavailable):
        m.complete(REQ())
    assert all(c[0] == NV for c in f.calls)


def test_stale_request_is_never_sent(tmp_path):
    m, f, c = mk(tmp_path)
    r = REQ(ttl_s=10)
    r.created = c() - 60
    with pytest.raises(AllProvidersUnavailable):
        m.complete(r)
    assert f.calls == []


# ------------------------------------------------------------------ queue
def q(tmp_path, f=None, clock=None, **kw):
    m, f, c = mk(tmp_path, f, clock)
    return AIRequestQueue(tmp_path / "queue.sqlite", m, clock=c, **kw), m, f, c


def test_queue_priority_and_dedup_supersede(tmp_path):
    qu, m, f, c = q(tmp_path)
    qu.submit(REQ(kind="event", priority=Priority.LOW, dedup_key="a"))
    qu.submit(REQ(kind="event", priority=Priority.CRITICAL, dedup_key="b"))
    r3 = REQ(kind="event", priority=Priority.NORMAL, dedup_key="a")
    r3.user = "newer"
    qu.submit(r3)
    assert qu.counters["superseded"] == 1 and qu.pending() == 2
    got = []
    qu.on_result = lambda req, resp: got.append((req.dedup_key, req.user))
    while qu.pump() == "done":
        pass
    assert got == [("b", "usr"), ("a", "newer")]


def test_queue_cooldown_drops_repeats_but_not_critical(tmp_path):
    qu, m, f, c = q(tmp_path, cooldown_s={"event": 60})
    qu.submit(REQ(kind="event", dedup_key="k"))
    qu.pump()
    assert qu.submit(REQ(kind="event", dedup_key="k")) is None
    assert qu.submit(REQ(kind="event", dedup_key="k", priority=Priority.CRITICAL)) is not None
    c.adv(61)
    assert qu.submit(REQ(kind="event", dedup_key="k")) is not None


def test_queue_survives_restart_and_drops_stale_after_outage(tmp_path):
    f = Fake(); f.script[(NV, "*")] = [500]; f.script[(GQ, "*")] = [500]
    qu, m, f, c = q(tmp_path, f)
    qu.submit(REQ(kind="periodic_summary", ttl_s=600, dedup_key="s1"))
    qu.submit(REQ(kind="pit_stop", ttl_s=3600, dedup_key="p1", priority=Priority.HIGH))
    assert qu.pump() == "waiting"             # all providers down: request stays queued, race goes on
    qu.db.execute("UPDATE requests SET status='sending'")   # simulate a crash while sending
    qu.db.commit()
    qu.db.close()
    c.adv(1200)                                # long outage; then app restarts and connectivity returns
    f.script[(NV, "*")] = ["ok"]; f.script[(GQ, "*")] = ["ok"]
    m2 = build_default_manager(tmp_path / "q2.sqlite", transport=httpx.MockTransport(f), key_overrides=KEYS, clock=c)
    qu2 = AIRequestQueue(tmp_path / "queue.sqlite", m2, clock=c)
    assert qu2.status_counts().get("dropped_stale") == 1      # the 10-min summary is stale and is NOT sent
    n = len(f.calls)
    assert qu2.pump() == "done"                               # the pit-stop request (ttl 1h) still goes out
    assert len(f.calls) == n + 1


def test_queue_hourly_call_cap_spares_critical(tmp_path):
    qu, m, f, c = q(tmp_path, max_calls_per_hour=2)
    for i in range(4):
        qu.submit(REQ(kind=f"k{i}", dedup_key=f"x{i}"))
    assert [qu.pump() for _ in range(3)] == ["done", "done", "rate_capped"]
    qu.submit(REQ(kind="event", priority=Priority.CRITICAL, dedup_key="crit"))
    assert qu.pump() == "done"


def test_queue_overflow_drops_low_first(tmp_path):
    qu, *_ = q(tmp_path, max_pending=3)
    qu.submit(REQ(priority=Priority.CRITICAL, dedup_key="c"))
    for i in range(4):
        qu.submit(REQ(priority=Priority.LOW, dedup_key=f"l{i}"))
    assert qu.pending() == 3 and qu.counters["dropped_overflow"] == 2
    assert qu.db.execute("select count(*) from requests where status='pending' and priority=0").fetchone()[0] == 1


def test_selftest_without_keys_sends_nothing(tmp_path, monkeypatch):
    from race_engineer.ai.providers import selftest
    for k in ("NVIDIA_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("race_engineer.ai.providers.credentials._keyring", lambda: None)
    f = Fake()
    m = build_default_manager(tmp_path / "q.sqlite", transport=httpx.MockTransport(f))
    rep = selftest.run(m)
    assert f.calls == [] and rep["summary"].startswith("no key") and all("how_to" in r for r in rep["routes"])


def test_api_key_endpoint_never_echoes_key(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from race_engineer.acquisition.engine import AcquisitionEngine
    from race_engineer.api.app import create_app
    from race_engineer.storage.catalog import Catalog
    stored = {}
    monkeypatch.setattr("race_engineer.ai.providers.credentials.store_key", lambda p, k: stored.setdefault(p, k) and {"stored": True})
    cat = Catalog(tmp_path / "c.sqlite")
    eng = AcquisitionEngine(lambda: None, catalog=cat, data_root=tmp_path, record=False)
    c = TestClient(create_app(eng, cat), headers={"host": "testserver"}) if False else TestClient(create_app(eng, cat), base_url="http://127.0.0.1")
    r = c.put("/api/ai/providers/key", json={"provider": "groq", "key": "gsk_SECRETSECRET123"})
    assert r.status_code == 200 and "gsk_SECRET" not in r.text and stored["groq"] == "gsk_SECRETSECRET123"
    assert c.put("/api/ai/providers/key", json={"provider": "other", "key": "xxxxxxxxxx"}).status_code == 422
    r = c.put("/api/ai/settings", json={"enabled": True, "mode": "free_multi", "providers": [], "free_multi": {"api_key": "x"}})
    assert r.status_code == 422
