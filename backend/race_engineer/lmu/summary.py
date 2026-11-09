"""One summary document for the real-LMU verification, assembled ONLY from the reports the tools produced.

Nothing is invented: a missing input is reported as "not run". Real and synthetic/file data are labelled separately,
and Phase 1 is NEVER reported as complete by this tool: it can only say whether the acceptance criteria are met.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .verify import sanitize, sanitize_obj


def _load(p) -> dict | None:
    if not p:
        return None
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def build(verify=None, preflight=None, duckdb=None, setup=None, hud=None, originals=None) -> dict:
    v, pf, dk, st, hd, og = (_load(x) for x in (verify, preflight, duckdb, setup, hud, originals))
    s: dict = {"tool": "race_engineer verification-summary", "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "inputs": {k: (Path(x).name if x else None) for k, x in
                          (("verify", verify), ("preflight", preflight), ("duckdb", duckdb), ("setup", setup), ("hud", hud), ("originals", originals))}}
    app = (v or pf or {}).get("app") or {}
    s["app"] = {"version": app.get("version"), "commit": app.get("commit"), "commit_source": app.get("commit_source"), "built_utc": app.get("built_utc")}
    inst = (v or {}).get("install") or (pf or {}).get("lmu_install") or {}
    s["lmu"] = {"installed": inst.get("found", None) if "found" in inst else None, "steam_build_id": inst.get("steam_build_id"),
                "game_version_in_mapping": (v or {}).get("game_version"),
                "application_state": (v or {}).get("application_state"),
                "process_running_at_preflight": (pf or {}).get("lmu_process_running")}
    if v is None:
        s["verify"] = {"run": False}
        s["data_origin"] = "NO RECORDING"
    else:
        checks = {c["id"]: c for c in v["checks"]}
        mp = v.get("mapping")
        hv = v.get("header_layout_check") or {}
        d = (v.get("acquisition") or {}).get("diagnostics") or {}
        q = v.get("recording_quality") or {}
        prov = q.get("provenance_counts") or {}
        real = checks.get("real_data_source", {}).get("ok")
        s["data_origin"] = ("REAL (every sample lmu_shm from the OS mapping)" if real is True else
                            "NOT REAL: " + (v.get("data_source") or "") + f" provenance={prov}" if prov else "NO RECORDING")
        s["verify"] = {
            "run": True, "verdict": v["verdict"], "on_windows": checks.get("windows", {}).get("ok"),
            "mapping_found": mp is not None, "mapping_size": (mp or {}).get("size"), "expected_min_size": (mp or {}).get("expected_min"),
            "offsets": {"state": checks.get("header_offsets", {}).get("ok"),
                        "meaning": "True = our struct offsets equal those computed from the installed LMU headers; None = headers not found, NOT verified",
                        "structs_matching": sum(1 for x in hv.get("structs", []) if x.get("status") == "match"),
                        "structs_compared": len(hv.get("structs", []))},
            "effective_hz": d.get("effective_hz"), "samples_received": d.get("samples_received"), "samples_lost": d.get("samples_lost"),
            "reconnects": d.get("reconnects"), "states_seen": (v.get("acquisition") or {}).get("states_seen"),
            "errors": (v.get("acquisition") or {}).get("errors", []),
            "failed_checks": [c["id"] for c in v["checks"] if c["ok"] is False],
            "unknown_checks": [c["id"] for c in v["checks"] if c["ok"] is None],
            "fields_available": sorted(c for c, x in (q.get("channel_stats") or {}).items()
                                       if x["non_null"] and not x["constant"]),
            "fields_constant_unverified": q.get("channels_constant", []),
            "fields_missing_all_null": q.get("channels_all_null", []),
            "data_quality": {k: q.get(k) for k in ("rows", "mean_hz", "expected_hz", "elapsed_time_going_backwards", "provenance_counts")},
        }
    s["duckdb"] = ({"run": False, "files_found": len((pf or {}).get("duckdb_files", []))} if dk is None else
                   {"run": True, "layout_ok": dk.get("ok"), "problems": dk.get("problems"), "channels": len(dk.get("channels", [])),
                    "events": len(dk.get("events", [])), "g_force_verdict": (dk.get("g_force_analysis") or {}).get("verdict"),
                    "original_modified": dk.get("original_modified"), "missing_core_channels": dk.get("missing_core_channels"),
                    "data_origin": "REAL file written by LMU (assumed: the tool cannot tell a synthetic file from a real one by itself)"})
    s["setup"] = ({"run": False, "files_found": len((pf or {}).get("setup_files", []))} if st is None else
                  {"run": True, "format": st.get("format"), "sha256_prefix": (st.get("file") or {}).get("sha256", "")[:16],
                   "verbatim_copy_identical": st.get("verbatim_copy_identical"),
                   "limits_known": st.get("limits_known", None)})
    s["hud"] = ({"run": False} if hd is None else {"run": True, "verdict": hd["verdict"], "reasons": hd["reasons"], "per_field": hd["per_field"], "notes": hd.get("notes")})
    s["originals_integrity"] = og if og is not None else {"checked": False}
    s["preflight_missing"] = (pf or {}).get("missing", [])
    # ---- acceptance: NEVER "complete" from here
    v_ok = bool(v) and v["verdict"].startswith("REAL LMU VERIFIED")
    h_ok = bool(hd) and hd["verdict"] == "HUD COMPARISON PASSED"
    o_ok = og is None or og.get("all_unchanged", True)
    missing = []
    if not v_ok:
        missing.append("automatic verification with REAL LMU (verify-lmu verdict 'REAL LMU VERIFIED')")
    if not h_ok:
        missing.append("HUD comparison passed")
    if not o_ok:
        missing.append("originals unchanged (a protected original file CHANGED - investigate)")
    s["phase1"] = {"declared_complete": False,
                   "status": ("ACCEPTANCE CRITERIA MET on real data - final acceptance is the user's decision, not this tool's"
                              if not missing else "PHASE 1 NOT COMPLETE - missing: " + "; ".join(missing)),
                   "missing": missing}
    return s


def to_markdown(s: dict) -> str:
    a, ver = s["app"], s["verify"]
    m = ["# Race Engineer AI - real LMU verification summary", f"*{s['utc']}*", "",
         f"## **{s['phase1']['status']}**", "", f"Data origin: **{s['data_origin']}**", "",
         "## Application", f"- version {a['version']}, commit {a['commit'] or 'unknown'} ({a['commit_source']})", "",
         "## LMU", f"- installed: {s['lmu']['installed']}, Steam build id: {s['lmu']['steam_build_id']}, gameVersion in mapping: {s['lmu']['game_version_in_mapping']}"]
    if ver.get("run"):
        o = ver["offsets"]
        m += ["", "## Shared memory", f"- verdict: {ver['verdict']}", f"- mapping found: {ver['mapping_found']}, size {ver['mapping_size']} (expected >= {ver['expected_min_size']})",
              f"- offsets vs installed headers: {o['state']} ({o['structs_matching']}/{o['structs_compared']} structs) - {o['meaning']}",
              f"- effective {ver['effective_hz']} Hz, samples {ver['samples_received']}, lost {ver['samples_lost']}, reconnects {ver['reconnects']}",
              f"- failed checks: {ver['failed_checks']}; unknown: {ver['unknown_checks']}", f"- errors: {ver['errors'] or 'none'}",
              f"- fields available (vary): {len(ver['fields_available'])}; constant (unverified): {ver['fields_constant_unverified']}; missing (all null): {ver['fields_missing_all_null']}",
              f"- data quality: {ver['data_quality']}"]
    else:
        m += ["", "## Shared memory", "- verification NOT run"]
    d, st, h, og = s["duckdb"], s["setup"], s["hud"], s["originals_integrity"]
    m += ["", "## DuckDB", f"- {d}", "", "## Setup", f"- {st}", "", "## HUD comparison", f"- {h.get('verdict', 'NOT run')} {h.get('reasons', '')}",
          "", "## Originals integrity", f"- {og}", "", "## Missing before preflight", f"- {s['preflight_missing'] or 'nothing'}",
          "", "Local report: nothing was uploaded. Synthetic or file-override data are never evidence of LMU integration."]
    return sanitize("\n".join(m))


def run(out_dir: Path | None = None, **inputs) -> tuple[dict, Path]:
    from ..storage.paths import data_dir
    s = build(**inputs)
    out = Path(out_dir) if out_dir else Path(data_dir()) / "reports"
    out.mkdir(parents=True, exist_ok=True)
    from ..storage.paths import unique_stem
    stem = unique_stem(out, "verification_summary_")
    (out / f"{stem}.json").write_text(json.dumps(sanitize_obj(s), indent=2, default=str), encoding="utf-8")
    md = out / f"{stem}.md"
    md.write_text(to_markdown(s), encoding="utf-8")
    return s, md
