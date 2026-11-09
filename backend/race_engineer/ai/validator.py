"""Anti-hallucination validator for LLM answers: every number and every cited fact must exist in the fact base."""
from __future__ import annotations

import json
import re

from .facts import Fact

NUM = re.compile(r"(?<![A-Za-z_.])[-+]?\d+(?:[.,]\d+)?")
ID_TOKENS = re.compile(r"\b(?:[PTCFDLK]\d+(?:\.\w+)*|SEC\d|S\d)\b")
REQUIRED = ("observed", "interpretation", "suggestion", "confidence", "data_used")


def numeric_universe(facts: list[Fact]) -> set[float]:
    u: set[float] = set()

    def add(x: float):
        for d in range(0, 5):
            u.add(round(x, d)); u.add(round(abs(x), d))

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v)
        elif isinstance(o, (int, float)) and not isinstance(o, bool):
            add(float(o))
    for f in facts:
        walk(f.values)
        for m in NUM.findall(ID_TOKENS.sub(" ", f.text)):
            add(float(m.replace(",", ".")))
    return u


def _numbers(text: str) -> list[float]:
    return [float(m.replace(",", ".")) for m in NUM.findall(ID_TOKENS.sub(" ", text))]


def parse_llm_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in LLM output")
    return json.loads(m.group(0))


def validate(ans: dict, facts: list[Fact]) -> list[str]:
    """Return a list of violations (empty = acceptable)."""
    bad: list[str] = []
    ids = {f.id for f in facts}
    for k in REQUIRED:
        if k not in ans:
            bad.append(f"missing field {k}")
    if bad:
        return bad
    uni = numeric_universe(facts)
    texts = [o.get("text", "") for o in ans["observed"]] + list(ans["interpretation"]) + list(ans["suggestion"])
    for o in ans["observed"]:
        if not o.get("facts"):
            bad.append("observation without cited facts")
        for fid in o.get("facts", []):
            if fid not in ids:
                bad.append(f"unknown fact id {fid}")
    for fid in ans["data_used"]:
        if fid not in ids:
            bad.append(f"unknown data_used id {fid}")
    for t in texts:
        for n in _numbers(t):
            if n not in uni and round(n, 2) not in uni and round(n, 1) not in uni:
                bad.append(f"number {n} not present in facts: «{t[:60]}»")
    if not isinstance(ans["confidence"], dict) or ans["confidence"].get("level") not in ("bassa", "media", "alta"):
        bad.append("confidence.level must be bassa|media|alta")
    return bad
