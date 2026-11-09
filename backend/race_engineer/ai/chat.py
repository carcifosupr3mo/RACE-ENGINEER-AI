"""Orchestration: facts -> rules answer (always) -> optional LLM rewrite, validated; fallback to rules."""
from __future__ import annotations

import json

from ..storage.catalog import Catalog
from . import engineer, validator
from .facts import Fact, build_facts
from .provider import LLMError, ProviderChain, from_settings

SYSTEM = """Sei l'ingegnere di pista di un pilota di Le Mans Ultimate. REGOLE ASSOLUTE:
- Usa SOLO i fatti forniti (id, testo, valori). Non inventare tempi, velocità, temperature, distanze, frenate, numeri di curva, setup.
- Ogni numero che scrivi deve comparire nei fatti. Ogni osservazione deve citare gli id dei fatti.
- Se un dato manca, dichiaralo in "missing". Una correlazione non è una causa: usa "compatibile con".
- Rispondi SOLO con un JSON: {"observed":[{"text":str,"facts":[id]}],"interpretation":[str],"suggestion":[str],
  "confidence":{"level":"bassa|media|alta","reason":str},"data_used":[id],"missing":[str]}.
- Scrivi in italiano, tecnico e conciso."""

ORDER = {"bassa": 0, "media": 1, "alta": 2}


def ask(catalog: Catalog, session_id: str, question: str, chain: ProviderChain | None = None, conversation: str = "default") -> dict:
    facts, meta = build_facts(catalog, session_id)
    base = engineer.answer(question, facts, meta)
    result = dict(base)
    result["llm"] = {"used": False}
    chain = chain if chain is not None else from_settings(catalog.get_setting("ai"))
    if chain and chain.providers and base["observed"]:
        payload = json.dumps({"question": question, "facts": [f.to_json() for f in facts if f.id in set(base["data_used"]) or f.kind in ("session", "missing")],
                              "rules_answer": {k: base[k] for k in ("observed", "interpretation", "suggestion", "confidence", "missing")}}, ensure_ascii=False)
        try:
            r, pname = chain.complete(SYSTEM, payload)
            ans = validator.parse_llm_json(r.text)
            problems = validator.validate(ans, facts)
            if problems:
                result["llm"] = {"used": False, "provider": pname, "rejected": problems[:5]}
            else:
                lvl = min((ans["confidence"]["level"], base["confidence"]["level"]), key=lambda x: ORDER[x])   # never more confident than the data allows
                result.update({"observed": ans["observed"], "interpretation": ans["interpretation"], "suggestion": ans["suggestion"],
                               "confidence": {"level": lvl, "reason": base["confidence"]["reason"]}, "data_used": sorted(set(ans["data_used"])),
                               "missing": list(dict.fromkeys(base["missing"] + list(ans.get("missing", []))))[:10], "generated_by": "llm"})
                result["llm"] = {"used": True, "provider": pname, "tokens": r.tokens_in + r.tokens_out}
        except (LLMError, ValueError, KeyError, TypeError) as e:
            result["llm"] = {"used": False, "error": str(e)[:200]}
    by_id = {f.id: f.to_json() for f in facts}
    result["facts"] = {i: by_id[i] for i in result["data_used"] if i in by_id}
    catalog.add_message(conversation, "user", {"question": question}, session_id)
    catalog.add_message(conversation, "assistant", {k: v for k, v in result.items() if k != "facts"}, session_id)
    return result
