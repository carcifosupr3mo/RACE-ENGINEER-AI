"""Setup Advisor (Phase 5) — deliberately conservative.

* The real LMU setup file format is NOT verified here. Third parties report a `CarSetup` JSON blob in the DuckDB
  `metadata` table "describing setup values, ranges and labels"; its exact structure is unknown to this project.
* Therefore parsing is generic: a "parameter" is any JSON object that carries a numeric current value AND numeric
  limits (min/max). Anything else is kept verbatim and listed as 'no verified limits'.
* NO numeric change is ever proposed unless the parameter has verified limits in that very setup, the proposal stays inside
  them and is at most one `step` (if the file declares one). Nothing is written back; originals are never modified.
* Links between observed driving problems and setup areas are generic engineering knowledge, labelled as such (not measurements).
"""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, asdict

from ..storage.catalog import Catalog

VALUE_KEYS = ("value", "current", "val", "selected")
MIN_KEYS = ("min", "minimum", "lower")
MAX_KEYS = ("max", "maximum", "upper")
STEP_KEYS = ("step", "increment", "stepsize")


@dataclass
class Param:
    path: str
    value: float
    min: float
    max: float
    step: float | None
    label: str | None = None

    def to_json(self):
        return asdict(self)


def _pick(d: dict, keys):
    for k, v in d.items():
        if k.lower() in keys and isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return None


def flatten(raw, prefix="") -> tuple[list[Param], list[dict]]:
    """Returns (parameters with verified limits, other leaves without limits)."""
    params, loose = [], []

    def walk(o, path):
        if isinstance(o, dict):
            v, lo, hi = _pick(o, VALUE_KEYS), _pick(o, MIN_KEYS), _pick(o, MAX_KEYS)
            if v is not None and lo is not None and hi is not None and lo <= hi:
                label = next((x for k, x in o.items() if k.lower() in ("label", "name", "title") and isinstance(x, str)), None)
                params.append(Param(path, v, lo, hi, _pick(o, STEP_KEYS), label)); return
            for k, x in o.items():
                walk(x, f"{path}/{k}" if path else str(k))
        elif isinstance(o, list):
            for i, x in enumerate(o):
                walk(x, f"{path}[{i}]")
        elif isinstance(o, (int, float, str)) and not isinstance(o, bool):
            loose.append({"path": path, "value": o})
    walk(raw, prefix)
    return params, loose


def import_setup(catalog: Catalog, raw: dict | str, source: str, name: str | None = None, session_id: str | None = None,
                 original_path: str | None = None) -> dict:
    """JSON setups are parsed; INI-style (.svm) text is kept byte-faithful in raw_text and parsed into sections. Anything else: 422."""
    import hashlib
    from .inspect import detect_format, parse_svm
    raw_text, fmt = None, "json"
    if isinstance(raw, str):
        fmt = detect_format(raw)
        if fmt == "json":
            raw_text, raw = raw, json.loads(raw.lstrip("\ufeff"))
        elif fmt == "svm":
            raw_text, raw = raw, {"format": "svm", **parse_svm(raw)}
        else:
            raise ValueError("unrecognised setup format (expected JSON or rFactor-style .svm text)")
    sid = uuid.uuid4().hex
    sha = hashlib.sha256(raw_text.encode("utf-8")).hexdigest() if raw_text else None
    with catalog.db:
        catalog.db.execute("INSERT INTO setups(id,imported_at,session_id,source,original_path,name,raw_json,raw_text,sha256,fmt) VALUES (?,?,?,?,?,?,?,?,?,?)",
                           (sid, time.time(), session_id, source, original_path, name, json.dumps(raw), raw_text, sha, fmt))
    params, loose = flatten(raw)
    return {"id": sid, "parameters_with_limits": len(params), "other_values": len(loose),
            "warning": None if params else "no parameter with verified min/max limits found: the advisor cannot propose numeric changes for this setup"}


def import_from_duckdb_metadata(catalog: Catalog, duckdb_path: str, session_id: str | None = None) -> dict:
    from ..importers.lmu_duckdb import LmuDuckdb
    with LmuDuckdb(duckdb_path, copy_first=True) as d:
        row = d.con.execute("SELECT value FROM metadata WHERE key='CarSetup'").fetchone()
        meta = {k: v for k, v in d.con.execute("SELECT key, value FROM metadata").fetchall()}
    if not row:
        raise ValueError("no CarSetup entry in metadata")
    return import_setup(catalog, row[0], "duckdb_metadata", name=meta.get("CarName"), session_id=session_id, original_path=duckdb_path)


def get_setup(catalog: Catalog, setup_id: str) -> dict | None:
    r = catalog.db.execute("SELECT * FROM setups WHERE id=?", (setup_id,)).fetchone()
    return None if r is None else {**dict(r), "raw": json.loads(r["raw_json"])}


# finding type -> (generic area, regex over parameter paths/labels, generic effect, trade-off, direction)
KNOWLEDGE = {
    "early_braking": ("brake balance / stability under braking", r"brake.*(bias|balance|migration)|bias", "Brake bias further forward typically adds stability on entry.", "Rear brake bias lower can under-rotate the car and lengthen braking.", -1),
    "late_throttle": ("rear stability on exit (differential / traction control)", r"diff|traction|\btc\b|power", "Less rear instability on exit typically allows earlier throttle.", "More stability usually costs some rotation / tyre wear.", +1),
    "slow_exit": ("rear stability on exit (differential / traction control)", r"diff|traction|\btc\b|power", "Better traction can raise exit speed.", "Can induce understeer on exit.", +1),
}


def advise(catalog: Catalog, setup_id: str, findings: list[dict]) -> dict:
    s = get_setup(catalog, setup_id)
    if s is None:
        raise KeyError("unknown setup")
    params, loose = flatten(s["raw"])
    out = {"setup_id": setup_id, "parameters_with_limits": len(params), "hypotheses": [], "proposals": [],
           "rules": ["No change is ever applied automatically.", "Numeric proposals only for parameters with verified limits in this setup, at most one declared step, inside [min,max].",
                     "Area links are generic engineering knowledge, not measurements."]}
    seen = set()
    for f in findings:
        k = KNOWLEDGE.get(f["type"])
        if not k or (f["type"], f["corner"]) in seen:
            continue
        seen.add((f["type"], f["corner"]))
        area, rx, effect, trade, direction = k
        cand = [p for p in params if re.search(rx, (p.path + " " + (p.label or "")), re.I)]
        hyp = {"finding": f"{f['type']} @ {f['corner']} (lap {f['lap']})", "evidence": f["evidence"], "area": area, "basis": "generic_knowledge",
               "note": "Observed behaviour is COMPATIBLE with this area; the measured data do not prove a setup cause. Check car behaviour data before changing anything."}
        out["hypotheses"].append(hyp)
        if len(cand) == 1 and cand[0].step:
            p = cand[0]
            new = max(p.min, min(p.max, p.value + direction * p.step))
            if new != p.value:
                out["proposals"].append({"parameter": p.path, "label": p.label, "current": p.value, "proposed": new, "limits_verified": [p.min, p.max],
                                         "motivation": hyp["finding"], "expected_effect": effect, "trade_offs": trade, "confidence": "bassa",
                                         "basis": "generic_knowledge + file limits", "auto_apply": False})
        else:
            hyp["proposal"] = ("none: " + ("no parameter with verified limits matches this area" if not cand else
                                           "ambiguous or no declared step — refusing to invent a value"))
    return out
