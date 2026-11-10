"""Automatic session adaptation: the SAME engine, different priorities (weights) per recognised session type.

The mode only re-weights what the suggestion arbiter prefers; it never switches engine, data path or UI.
An unrecognised session type uses the neutral ``generic`` weights.
"""
from __future__ import annotations

# finding/alert groups used by the arbiter
GROUP_OF = {
    "early_braking": "pace", "inefficient_late_braking": "pace", "braking_too_long": "pace", "abrupt_release": "pace",
    "delayed_acceleration": "pace", "insufficient_min_speed": "pace", "inefficient_line": "pace",
    "entry_loss": "pace", "mid_loss": "pace", "exit_loss": "pace",
    "inconsistent": "consistency", "fuel": "resources", "tyres": "resources",
}

PROFILES = {
    "practice": {"label": "Prove libere", "focus": ["scoperta del circuito", "riferimento personale", "tutte le perdite di tempo"],
                 "weights": {"pace": 1.0, "consistency": 0.9, "resources": 0.6}},
    "qualifying": {"label": "Qualifica", "focus": ["giro veloce", "perdite di tempo per curva"],
                   "weights": {"pace": 1.3, "consistency": 0.5, "resources": 0.3}},
    "race": {"label": "Gara", "focus": ["passo sostenibile", "costanza", "gomme", "carburante"],
             "weights": {"pace": 0.9, "consistency": 1.3, "resources": 1.2}},
    "endurance": {"label": "Endurance", "focus": ["stint", "degrado", "consumi", "pit stop"],
                  "weights": {"pace": 0.7, "consistency": 1.3, "resources": 1.5}},
    "test": {"label": "Test personali", "focus": ["riferimento personale", "tutte le perdite di tempo"],
             "weights": {"pace": 1.0, "consistency": 1.0, "resources": 0.5}},
    "generic": {"label": "Sessione non riconosciuta (modalità generica)", "focus": ["perdite di tempo per curva"],
                "weights": {"pace": 1.0, "consistency": 1.0, "resources": 1.0}},
}

ENDURANCE_MIN_ELAPSED_S = 3600.0     # heuristic: a race running longer than this (or with >= 3 stints) is treated as an endurance race
ENDURANCE_MIN_STINTS = 3


def classify(session_type: str | None, elapsed_s: float | None = None, stints: int = 1) -> dict:
    """session_type = the LMU-derived name from ``model.sample.session_type_name`` (test|practice|qualifying|warmup|race|unknown)."""
    st = (session_type or "unknown").lower()
    reason = f"tipo di sessione LMU: {st}"
    if st == "race":
        if (elapsed_s or 0) >= ENDURANCE_MIN_ELAPSED_S or stints >= ENDURANCE_MIN_STINTS:
            mode, reason = "endurance", f"gara con {int((elapsed_s or 0) // 60)} min trascorsi e {stints} stint (euristica: ≥ 60 min o ≥ 3 stint)"
        else:
            mode = "race"
    elif st in ("practice", "warmup"):
        mode = "practice"
    elif st in ("qualifying", "test"):
        mode = st
    else:
        mode, reason = "generic", "tipo di sessione non riconosciuto"
    p = PROFILES[mode]
    return {"mode": mode, "label": p["label"], "recognized": mode != "generic", "base_type": st, "reason": reason,
            "focus": p["focus"], "weights": p["weights"]}


def weight(mode_info: dict, group: str) -> float:
    return float(mode_info["weights"].get(group, 1.0))
