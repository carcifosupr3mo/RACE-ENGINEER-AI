import json

import httpx
import pytest
from fastapi.testclient import TestClient

from race_engineer.acquisition.engine import AcquisitionEngine
from race_engineer.ai import chat as ai_chat, engineer, validator
from race_engineer.ai.facts import build_facts
from race_engineer.ai.provider import (AnthropicProvider, Budget, LLMError, LLMResult, OpenAICompatProvider, ProviderChain)
from race_engineer.api.app import create_app
from race_engineer.lmu.discovery import LmuInstall
from race_engineer.storage.catalog import Catalog
from race_engineer.synthetic.game import SyntheticGame


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    d = tmp_path_factory.mktemp("ai")
    cat = Catalog(d / "c.sqlite")
    ids = {}
    for sc, laps in (("mixed", 5), ("constant", 2)):
        g = SyntheticGame(sc, laps=laps)
        e = AcquisitionEngine(lambda: g.backend, catalog=cat, data_root=d, process_probe=lambda: True, open_retry_s=0)
        while g.step():
            e.poll_once()
        e.stop()
        ids[sc] = cat.list_sessions()[0]["id"]
    return cat, ids


class Fake:
    name = "fake"
    def __init__(self, reply): self.reply, self.calls = reply, 0
    def complete(self, system, user, timeout_s):
        self.calls += 1
        r = self.reply(user) if callable(self.reply) else self.reply
        if isinstance(r, Exception):
            raise r
        return LLMResult(r, 100, 50)


def chain(p, **kw): return ProviderChain([p], Budget(**kw))


def test_rules_answer_time_loss_is_grounded_in_known_scenario(env):
    cat, ids = env
    a = ai_chat.ask(cat, ids["mixed"], "Dove perdo tempo?", chain=ProviderChain([]))
    assert a["generated_by"] == "rules" and a["intent"] == "time_loss"
    joined = " ".join(o["text"] for o in a["observed"])
    assert "P2" in joined and "early_braking" in joined          # perturbation injected in lap 2
    assert all(f in a["facts"] for f in a["data_used"]) and a["confidence"]["level"] in ("bassa", "media", "alta")
    assert any("non prova la causa" in x for x in a["interpretation"])          # correlation != causation
    assert "SINTETICI" in a["confidence"]["reason"]


def test_every_number_in_rules_answers_exists_in_facts(env):
    cat, ids = env
    facts, meta = build_facts(cat, ids["mixed"])
    for q in ["Dove perdo tempo?", "Qual è la curva peggiore?", "Come posso migliorare la frenata?", "Sto accelerando troppo tardi?",
              "Sono costante?", "Qual è il mio miglior settore?", "Quali errori ripeto?", "Come posso migliorare il mio passo gara?",
              "Come sono migliorato rispetto alla settimana precedente?"]:
        a = engineer.answer(q, facts, meta)
        probs = validator.validate({**a, "observed": a["observed"]}, facts)
        assert probs == [], (q, probs)


def test_missing_data_is_declared_not_invented(env):
    cat, ids = env
    a = ai_chat.ask(cat, ids["constant"], "Come sono migliorato rispetto alla settimana precedente?", chain=ProviderChain([]))
    assert a["observed"] == [] and any("storico insufficiente" in m for m in a["missing"]) and a["confidence"]["level"] == "bassa"
    b = ai_chat.ask(cat, ids["constant"], "Dove perdo tempo?", chain=ProviderChain([]))      # 1 valid lap only
    assert any("almeno 2 giri" in m for m in b["missing"])


def test_best_sector_and_consistency_answers(env):
    cat, ids = env
    a = ai_chat.ask(cat, ids["mixed"], "Qual è il mio miglior settore?", chain=ProviderChain([]))
    assert len(a["observed"]) == 3 and a["observed"][0]["facts"] == ["SEC1"]
    c = ai_chat.ask(cat, ids["mixed"], "Sono costante?", chain=ProviderChain([]))
    assert any("deviazione standard" in o["text"] or "variabilità" in o["text"] for o in c["observed"])


def good_reply(user):
    d = json.loads(user)
    f = d["facts"][0]
    return json.dumps({"observed": [{"text": f["text"], "facts": [f["id"]]}], "interpretation": ["Compatibile con quanto misurato."],
                       "suggestion": ["Ripeti il punto di frenata."], "confidence": {"level": "alta", "reason": "x"}, "data_used": [f["id"]], "missing": []})


def test_valid_llm_answer_is_accepted_but_confidence_is_capped(env):
    cat, ids = env
    p = Fake(good_reply)
    a = ai_chat.ask(cat, ids["mixed"], "Dove perdo tempo?", chain=chain(p))
    assert a["generated_by"] == "llm" and a["llm"]["used"] and p.calls == 1
    assert a["confidence"]["level"] != "alta"                    # LLM said 'alta'; data only supports media/bassa


@pytest.mark.parametrize("bad", [
    lambda u: json.dumps({"observed": [{"text": "Hai frenato a 123 m", "facts": ["S1"]}], "interpretation": [], "suggestion": [], "confidence": {"level": "media", "reason": ""}, "data_used": ["S1"]}),
    lambda u: json.dumps({"observed": [{"text": "ok", "facts": ["NOPE"]}], "interpretation": [], "suggestion": [], "confidence": {"level": "media", "reason": ""}, "data_used": []}),
    lambda u: json.dumps({"observed": [{"text": "ok", "facts": []}], "interpretation": [], "suggestion": [], "confidence": {"level": "media", "reason": ""}, "data_used": []}),
    lambda u: json.dumps({"observed": []}),
    lambda u: "non è JSON",
])
def test_hallucinated_or_malformed_llm_answers_are_rejected(env, bad):
    cat, ids = env
    a = ai_chat.ask(cat, ids["mixed"], "Dove perdo tempo?", chain=chain(Fake(bad)))
    assert a["generated_by"] == "rules" and a["llm"]["used"] is False and ("rejected" in a["llm"] or "error" in a["llm"])
    assert all("123" not in o["text"] for o in a["observed"])


def test_provider_failure_budget_and_fallback_chain(env):
    cat, ids = env
    a = ai_chat.ask(cat, ids["mixed"], "Dove perdo tempo?", chain=chain(Fake(LLMError("timeout"))))
    assert a["generated_by"] == "rules" and "timeout" in a["llm"]["error"]
    ch = ProviderChain([Fake(LLMError("down")), Fake(good_reply)])
    assert ai_chat.ask(cat, ids["mixed"], "Dove perdo tempo?", chain=ch)["llm"]["provider"] == "fake"
    b = Budget(daily_token_limit=100)
    ch2 = ProviderChain([Fake(good_reply)], b)
    ai_chat.ask(cat, ids["mixed"], "Dove perdo tempo?", chain=ch2)           # consumes 150 tokens
    a3 = ai_chat.ask(cat, ids["mixed"], "Dove perdo tempo?", chain=ch2)
    assert a3["generated_by"] == "rules" and "budget" in a3["llm"]["error"]


def test_budget_cost_accounting():
    b = Budget(price_in_per_1k=2.0, price_out_per_1k=4.0)
    b.record(LLMResult("", 1000, 500))
    assert b.cost == pytest.approx(4.0) and b.tokens == 1500


def test_http_providers_with_mock_transport(monkeypatch):
    def handler(req: httpx.Request):
        if req.url.path.endswith("/chat/completions"):
            assert req.headers["authorization"] == "Bearer sekret"
            return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}], "usage": {"prompt_tokens": 3, "completion_tokens": 2}})
        assert req.headers["x-api-key"] == "sekret"
        return httpx.Response(200, json={"content": [{"type": "text", "text": "yo"}], "usage": {"input_tokens": 4, "output_tokens": 1}})
    t = httpx.MockTransport(handler)
    monkeypatch.setenv("K", "sekret")
    assert OpenAICompatProvider("http://x/v1", "m", "K", transport=t).complete("s", "u", 5).text == "hi"
    r = AnthropicProvider("m", "K", transport=t).complete("s", "u", 5)
    assert r.text == "yo" and r.tokens_in == 4
    monkeypatch.delenv("K")
    with pytest.raises(LLMError, match="not set"):
        OpenAICompatProvider("http://x/v1", "m", "K", transport=t).complete("s", "u", 5)
    bad = httpx.MockTransport(lambda req: httpx.Response(500))
    with pytest.raises(LLMError):
        OpenAICompatProvider("http://x/v1", "m", None, transport=bad).complete("s", "u", 5)


def test_api_chat_and_settings_never_store_secrets(env):
    cat, ids = env
    e = AcquisitionEngine(lambda: None, catalog=cat, data_root=None, record=False)
    c = TestClient(create_app(e, cat, install=LmuInstall()), base_url="http://127.0.0.1")
    r = c.post("/api/chat", json={"session_id": ids["mixed"], "question": "Dove perdo tempo?"}).json()
    assert r["generated_by"] == "rules" and r["facts"]
    assert len(c.get("/api/chat/history").json()) >= 2
    assert c.post("/api/chat", json={"question": "x"}).status_code == 422
    assert c.put("/api/ai/settings", json={"enabled": True, "providers": [{"type": "anthropic", "model": "m", "api_key": "sk-123"}]}).status_code == 422
    assert c.put("/api/ai/settings", json={"enabled": True, "providers": [{"type": "anthropic", "model": "m", "api_key_env": "ANTHROPIC_API_KEY"}]}).status_code == 200
    assert "sk-" not in json.dumps(c.get("/api/ai/settings").json())
    # enabled provider with no key configured => graceful fallback to rules
    r2 = c.post("/api/chat", json={"session_id": ids["mixed"], "question": "Dove perdo tempo?"}).json()
    assert r2["generated_by"] == "rules" and "not set" in r2["llm"]["error"]
