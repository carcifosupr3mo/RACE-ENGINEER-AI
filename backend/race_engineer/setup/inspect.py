"""Setup file inspection / import (Phase 4 validation tooling).

FORMAT STATUS: LMU is built on the rFactor 2 engine, whose setups are ``.svm`` INI-style text files
(``[SECTION]`` / ``Key=value//display comment``). That is background knowledge, NOT verified on a real LMU
install here. This module therefore (a) detects the format from the file itself, (b) keeps a byte-faithful copy of
the original, (c) reports what it can and cannot interpret. The ``.svm`` value is usually an INDEX into a list of
discrete steps, not a physical value; limits/units are NOT in the file, so no numeric proposal can be made
from it (the advisor refuses). Nothing is ever written to the original or to the game folder.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from ..storage.paths import data_dir

_SECTION = re.compile(r"^\s*\[([^\]]+)\]\s*$")
_KV = re.compile(r"^\s*([^=\s][^=]*?)\s*=\s*(.*?)\s*$")


def detect_format(text: str) -> str:
    t = text.lstrip("﻿ \r\n\t")
    if t[:1] in "{[":
        try:
            json.loads(t)
            return "json"
        except ValueError:
            pass
    if any(_SECTION.match(l) for l in text.splitlines()[:200]) and "=" in text:
        return "svm"
    return "other"


def parse_svm(text: str) -> dict:
    """{'sections': {name: [{'key','raw','display'}]}, 'preamble': [...]}; values kept as text, comment after '//' is the game's display value."""
    sections: dict[str, list[dict]] = {}
    cur, pre = None, []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith(("//", ";", "#")):
            continue
        m = _SECTION.match(line)
        if m:
            cur = m.group(1)
            sections.setdefault(cur, [])
            continue
        m = _KV.match(line)
        if not m:
            continue
        key, rest = m.group(1), m.group(2)
        val, _, comment = rest.partition("//")
        item = {"key": key, "raw": val.strip(), "display": comment.strip() or None}
        (sections[cur] if cur is not None else pre).append(item)
    return {"sections": sections, "preamble": pre}


def analyse_text(text: str) -> dict:
    fmt = detect_format(text)
    rep: dict = {"format": fmt, "bytes": len(text.encode("utf-8"))}
    if fmt == "svm":
        t = parse_svm(text)
        items = [i for v in t["sections"].values() for i in v] + t["preamble"]
        numeric = [i for i in items if re.fullmatch(r"-?\d+(\.\d+)?", i["raw"])]
        rep.update(sections={k: len(v) for k, v in t["sections"].items()}, keys=len(items), numeric_keys=len(numeric),
                   with_display_comment=sum(1 for i in items if i["display"]),
                   units_in_display=sorted({m.group(1) for i in items if i["display"]
                                            for m in [re.search(r"\d\s*([a-zA-Z%°/]+)\s*$", i["display"])] if m}),
                   limits_in_file=False,
                   interpretation=("values are discrete setting indexes; the display comment shows the physical value when the "
                                   "game wrote one. min/max/step are NOT in the file => no numeric proposals possible."),
                   sample=[{"section": s, **i} for s, v in list(t["sections"].items())[:4] for i in v[:3]])
    elif fmt == "json":
        from .advisor import flatten
        params, loose = flatten(json.loads(text.lstrip("﻿")))
        rep.update(parameters_with_limits=len(params), other_values=len(loose), limits_in_file=bool(params),
                   sample=[p.to_json() for p in params[:5]])
    else:
        rep["interpretation"] = "unrecognised format: stored verbatim only; nothing is interpreted."
    return rep


def find_setup_files(user_data: str | Path, limit: int = 200) -> list[str]:
    """Read-only scan of UserData/player/Settings for .svm files (where rF2-engine games keep setups; location UNVERIFIED for LMU)."""
    base = Path(user_data) / "player" / "Settings"
    return [str(p) for p in sorted(base.rglob("*.svm"))[:limit]] if base.is_dir() else []


def inspect_file(path: str | Path, out_dir: Path | None = None, keep_copy: bool = True) -> tuple[dict, Path]:
    p = Path(path)
    data = p.read_bytes()
    text = data.decode("utf-8", errors="replace")
    sha = hashlib.sha256(data).hexdigest()
    rep = {"tool": "race_engineer setup-inspect", "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "file": {"name": p.name, "sha256": sha, "size_bytes": len(data)}, **analyse_text(text), "original_modified": False}
    root = data_dir()
    if keep_copy:
        raw_dir = root / "setups_raw"
        raw_dir.mkdir(exist_ok=True)
        dest = raw_dir / f"{sha[:16]}_{p.name}"
        if not dest.exists():
            dest.write_bytes(data)
        rep["verbatim_copy"] = dest.name
        rep["verbatim_copy_identical"] = hashlib.sha256(dest.read_bytes()).hexdigest() == sha
    out = Path(out_dir) if out_dir else root / "reports"
    out.mkdir(parents=True, exist_ok=True)
    from ..storage.paths import unique_stem
    stem = unique_stem(out, "setup_report_")
    from ..lmu.verify import sanitize, sanitize_obj
    (out / f"{stem}.json").write_text(json.dumps(sanitize_obj(rep), indent=2), encoding="utf-8")
    md = out / f"{stem}.md"
    md.write_text(sanitize("# Setup inspection\n\n```json\n" + json.dumps(sanitize_obj(rep), indent=2) + "\n```\n\nLocal report; the original was only read.\n"), encoding="utf-8")
    return rep, md
