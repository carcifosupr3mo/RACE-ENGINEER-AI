"""Rule-based race engineer: structured, fully grounded answers. Works with no AI provider at all."""
from __future__ import annotations

import re
from collections import Counter, defaultdict

import numpy as np

from .facts import Fact

INTENTS = [
    ("progress", r"settimana|mese|migliorat|progress|improv|week|month|rispetto a"),
    ("repeated_errors", r"errori|ripeto|ripet|repeat|mistake"),
    ("best_sector", r"settore|sector"),
    ("consistency", r"costant|consisten|regolar"),
    ("braking", r"frenat|frena|brak"),
    ("throttle", r"accelera|gas|throttle|uscita|tardi"),
    ("worst_corner", r"curva peggior|peggior|worst"),
    ("race_pace", r"passo gara|race pace|passo|stint|carburante|fuel|gomme|pneumatic|usura"),
    ("time_loss", r"perd|lent|slow|loss|dove|perch|miglior|veloc"),
]


def classify(q: str) -> str:
    ql = q.lower()
    for name, rx in INTENTS:
        if re.search(rx, ql):
            return name
    return "unknown"


def _level(n_laps: int, meta: dict) -> tuple[str, str]:
    if n_laps < 3:
        lvl, why = "bassa", f"solo {n_laps} giri validi a confronto"
    elif n_laps < 6:
        lvl, why = "media", f"{n_laps} giri validi"
    else:
        lvl, why = "alta", f"{n_laps} giri validi"
    if meta.get("corners_provisional") and lvl == "alta":
        lvl, why = "media", why + "; curve con numerazione provvisoria"
    if not meta.get("alignment_ok", True):
        lvl, why = "bassa", why + "; qualità di allineamento insufficiente"
    if meta.get("provenance") and "synthetic" in meta["provenance"]:
        why += "; dati SINTETICI"
    return lvl, why


def answer(question: str, facts: list[Fact], meta: dict) -> dict:
    by_id = {f.id: f for f in facts}
    intent = classify(question)
    obs: list[dict] = []
    interp: list[str] = []
    sugg: list[str] = []
    missing: list[str] = []
    used: set[str] = set()

    def add(fs: list[Fact]):
        for f in fs:
            obs.append({"text": f.text, "facts": [f.id]}); used.add(f.id)

    kind = lambda k: [f for f in facts if f.kind == k]
    findings = kind("finding")
    n_cmp = max(0, meta["n_valid"] - 1)
    if meta["n_valid"] < 2 and intent not in ("progress", "best_sector"):
        add([by_id["S1"]] + ([by_id["S2"]] if "S2" in by_id else []))
        missing.append("servono almeno 2 giri validi per confrontare curve e punti di frenata")
        intent_note = intent
    elif intent in ("time_loss", "worst_corner"):
        loss = sorted(kind("corner_loss"), key=lambda f: -f.values["mean_zone_delta_s"])
        loss = [f for f in loss if f.values["mean_zone_delta_s"] > 0.005]
        if not loss:
            add([f for f in kind("lap_delta")][:3] or [by_id["S2"]])
            interp.append("Nessuna curva mostra una variazione media di tempo di zona oltre 0,005 s rispetto al tuo giro migliore.")
        else:
            add(loss[:1] if intent == "worst_corner" else loss[:3])
            for f in loss[: (1 if intent == "worst_corner" else 3)]:
                fs = [x for x in findings if x.values["corner"] == f.values["corner"]]
                add(fs[:3])
                types = Counter(x.values["type"] for x in fs)
                if types:
                    t, c = types.most_common(1)[0]
                    interp.append(f"Nella curva {f.values['corner']} la differenza più ricorrente è «{t}» ({c} giri): è compatibile con la perdita di tempo osservata, ma la correlazione non prova la causa.")
                    sugg.append(_advice(t, f.values["corner"]))
    elif intent == "braking":
        fs = [f for f in findings if f.values["type"] in ("early_braking", "late_braking", "brake_peak_higher", "early_brake_release")]
        add(fs[:6] or [f for f in kind("corner")][:3])
        add([f for f in kind("consistency")][:4])
        if not fs:
            interp.append("Nessuna differenza di frenata oltre soglia (±15 m sul punto di frenata) rispetto al giro migliore.")
        for t in sorted({f.values["type"] for f in fs}):
            sugg.append(_advice(t, None))
    elif intent == "throttle":
        fs = [f for f in findings if f.values["type"] in ("late_throttle", "slow_exit")]
        add(fs[:6])
        if not fs:
            interp.append("Nessuna ripresa del gas tardiva (≥15 m) né uscita più lenta (≥3 km/h) rispetto al giro migliore.")
        for t in sorted({f.values["type"] for f in fs}):
            sugg.append(_advice(t, None))
    elif intent == "consistency":
        add([by_id["S2"]] if "S2" in by_id else [])
        ks = sorted(kind("consistency"), key=lambda f: -(f.values.get("brake_start_std_m") or 0))
        add(ks[:4])
        if not ks:
            missing.append("la costanza per curva richiede almeno 3 giri validi")
    elif intent == "best_sector":
        secs = kind("sector")
        add(secs)
        if not secs:
            missing.append("tempi di settore non disponibili (cur_sector1/2 assenti o giri non validi)")
    elif intent == "progress":
        h = by_id.get("HIST")
        if h:
            add([h])
        else:
            missing.append("storico insufficiente: servono almeno due settimane con sessioni valide sulla stessa pista e vettura")
    elif intent == "repeated_errors":
        cnt: dict = defaultdict(list)
        for f in findings:
            cnt[(f.values["corner"], f.values["type"])].append(f)
        rep = sorted(((k, v) for k, v in cnt.items() if len(v) >= 2), key=lambda kv: -len(kv[1]))
        if rep:
            for (c, t), v in rep[:5]:
                add(v[:1])
                interp.append(f"«{t}» in curva {c} compare in {len(v)} giri su {n_cmp} confrontati.")
                sugg.append(_advice(t, c))
        else:
            interp.append("Nessuna differenza si ripete in almeno 2 giri sulla stessa curva.")
            add(kind("lap_delta")[:3])
    elif intent == "race_pace":
        add([by_id["S2"]] if "S2" in by_id else [])
        add([by_id[k] for k in ("FUEL", "TYRE") if k in by_id])
        if "PACE" in by_id:
            add([by_id["PACE"]])
        else:
            missing.append("per la tendenza del passo servono almeno 4 giri validi")
        if "FUEL" not in by_id:
            missing.append("consumo carburante non stimabile (servono ≥2 giri puliti con carburante registrato)")
        if "TYRE" not in by_id:
            missing.append("tendenza usura gomme non disponibile")
    else:
        add([by_id["S1"]])
        interp.append("Non ho riconosciuto la domanda. Posso rispondere su: dove perdo tempo, curva peggiore, frenata, accelerazione, costanza, migliori settori, progressi, errori ricorrenti, passo gara/carburante/gomme.")
    if "MISS" in by_id:
        missing.append(by_id["MISS"].text)
    if not obs:
        missing.append("nessun dato misurato utile per questa domanda")
    lvl, why = _level(n_cmp + 1 if meta["n_valid"] else 0, meta)
    if not obs or (obs and not used):
        lvl = "bassa"
    return {"intent": intent, "observed": obs, "interpretation": interp, "suggestion": list(dict.fromkeys(sugg)),
            "confidence": {"level": lvl, "reason": why}, "data_used": sorted(used), "missing": missing, "generated_by": "rules"}


def _advice(t: str, corner: str | None) -> str:
    where = f" in curva {corner}" if corner else ""
    return {
        "early_braking": f"Prova a spostare gradualmente il punto di frenata{where} verso quello del tuo giro migliore, verificando che la velocità minima non cali.",
        "late_braking": f"Frenare più tardi{where} rispetto al giro migliore: controlla che la velocità minima e l'uscita non peggiorino.",
        "late_throttle": f"Anticipa la ripresa del gas{where} dopo l'apice, in modo progressivo.",
        "slow_exit": f"Lavora sull'uscita{where}: apice e ripresa del gas per aumentare la velocità in uscita.",
        "low_min_speed": f"Cerca di portare più velocità all'apice{where}, senza compromettere l'uscita.",
        "early_brake_release": f"Mantieni il freno più a lungo{where} nella fase di rilascio, valutando l'effetto sull'inserimento.",
        "brake_peak_higher": f"Modula il picco di pressione sul freno{where}.",
    }.get(t, f"Rivedi il comportamento «{t}»{where}.")
