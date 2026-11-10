"""Live verification checklist: ONE report built from the shared state (no new measurements, no second pipeline).

Every step is ``ok`` / ``missing`` / ``unverified`` with the evidence it is based on, and the whole report states whether the data
are REAL (LMU shared memory) or SYNTHETIC. A synthetic run can never produce a "real" verdict. Personal data (driver name, paths,
credentials) are never included.
"""
from __future__ import annotations

from typing import Any

STEPS = ["lmu_process", "shared_memory", "session", "track", "samples", "map", "braking_points", "acceleration_points",
         "corner_analysis", "delta", "dual_display"]
TITLES_IT = {
    "lmu_process": "LMU in esecuzione", "shared_memory": "Shared Memory LMU_Data acquisita", "session": "Sessione riconosciuta",
    "track": "Circuito riconosciuto", "samples": "Campioni acquisiti (frequenza, perdite)", "map": "Mappa costruita da posizioni reali",
    "braking_points": "Punti di frenata identificati", "acceleration_points": "Punti di accelerazione identificati",
    "corner_analysis": "Analisi delle curve", "delta": "Delta vs riferimento aggiornato", "dual_display": "Dashboard e Driving Display simultanei",
}


def _st(ok: bool | None, evidence: str) -> dict:
    return {"status": "ok" if ok else ("unverified" if ok is None else "missing"), "evidence": evidence}


def build(*, snapshot: dict, map_payload: dict, engine_diag: dict, lmu_process: bool | None, live_status: dict, clients: int | None = None,
          app_version: str = "") -> dict:
    synthetic = bool(snapshot.get("synthetic") or engine_diag.get("synthetic"))
    sess, ref, delta, mp = snapshot.get("session") or {}, snapshot.get("reference") or {}, snapshot.get("delta") or {}, map_payload or {}
    zones = mp.get("zones") or []
    n_by = lambda k: sum(1 for z in zones if z.get("type") == k)
    corners = mp.get("corners") or []
    samples = engine_diag.get("samples_received", 0)
    last = snapshot.get("last_lap")
    steps: dict[str, Any] = {}
    if synthetic:
        steps["lmu_process"] = _st(None, "dati SINTETICI: LMU non coinvolto")
        steps["shared_memory"] = _st(None, "dati SINTETICI: nessuna Shared Memory letta")
    else:
        steps["lmu_process"] = _st(lmu_process, "processo LMU rilevato" if lmu_process else ("non rilevato" if lmu_process is False else "non determinabile su questo sistema"))
        m = engine_diag.get("mapping") or {}
        steps["shared_memory"] = _st(bool(m.get("size")) and engine_diag.get("state") == "acquiring",
                                     f"stato={engine_diag.get('state')}, mapping={m.get('size')} B (atteso {m.get('expected_size')} B)" + (f", errore={m.get('error')}" if m.get("error") else ""))
    steps["session"] = _st(bool(sess.get("id")) and sess.get("type") not in (None, "", "unknown"),
                           f"id={sess.get('id')}, tipo={sess.get('type')}, modalità={(sess.get('mode') or {}).get('label') if isinstance(sess.get('mode'), dict) else sess.get('mode')}")
    steps["track"] = _st(bool(sess.get("track")), f"circuito='{sess.get('track')}', lunghezza={sess.get('track_length_m')} m, vettura='{sess.get('vehicle')}'")
    hz = engine_diag.get("effective_hz") or 0
    steps["samples"] = _st(samples > 100 and hz > 5, f"{samples} campioni, {hz} Hz effettivi, persi={engine_diag.get('samples_lost')}, lacune={engine_diag.get('gap_events')}")
    steps["map"] = _st(bool(mp.get("available")), f"{len(mp.get('points') or [])} punti, sorgente={mp.get('source')}, curve={len(corners)}"
                       if mp.get("available") else f"non disponibile: {mp.get('reason')}")
    steps["braking_points"] = _st(n_by("brake") > 0, f"{n_by('brake')} zone di frenata dal giro di riferimento")
    steps["acceleration_points"] = _st(n_by("accel") > 0, f"{n_by('accel')} zone di accelerazione, {n_by('release')} di rilascio")
    ana = bool(last)
    steps["corner_analysis"] = _st(ana, f"ultimo giro analizzato: giro {last['lap']} vs {last['ref_lap']}, {len(last['findings'])} rilievi" if last
                                   else f"nessun giro analizzato (giri di riferimento: {ref.get('laps')}/2 necessari)")
    steps["delta"] = _st(bool(delta.get("available")), f"delta={delta.get('to_ref_s')} s vs giro {delta.get('ref_lap')}" if delta.get("available") else "delta non disponibile (serve un giro di riferimento)")
    steps["dual_display"] = _st(None if clients is None else clients >= 2,
                                "apri dashboard e /driving-display e confronta modalità, delta e suggerimento: devono coincidere (stesso stato, seq=%s)" % snapshot.get("seq")
                                if clients is None else f"{clients} client WebSocket connessi")
    verdict = "SYNTHETIC_NOT_REAL" if synthetic else ("REAL_ALL_AUTOMATIC_STEPS_OK" if all(steps[k]["status"] == "ok" for k in STEPS if k != "dual_display") else "REAL_INCOMPLETE")
    return {"kind": "live_check", "app_version": app_version, "data_provenance": "synthetic" if synthetic else "lmu_shared_memory",
            "verdict": verdict, "titles": TITLES_IT, "steps": steps, "order": STEPS,
            "reference": {"laps": ref.get("laps"), "reliability": (ref.get("reliability") or {}).get("level"), "version": ref.get("version")},
            "engine": {k: engine_diag.get(k) for k in ("state", "samples_received", "samples_lost", "gap_events", "effective_hz", "reconnects", "session_restarts", "recording", "errors")},
            "live_engineer": {"counters": live_status.get("counters"), "errors": live_status.get("errors")},
            "suggestion": (snapshot.get("suggestion") or {}).get("state"),
            "notes": ["Il verdetto REAL_ALL_AUTOMATIC_STEPS_OK NON sostituisce il confronto con il HUD di LMU (velocità, giro, delta) né il controllo visivo del secondo monitor.",
                      "Orientamento della mappa: assi di gioco, non verificati su LMU reale.",
                      "Nessun nome pilota, percorso utente o credenziale è incluso in questo report."]}


def to_markdown(r: dict) -> str:
    icon = {"ok": "OK", "missing": "MANCA", "unverified": "NON VERIFICABILE"}
    out = ["# Verifica live Race Engineer AI", "", f"- Dati: **{'SINTETICI (non valgono come prova LMU)' if r['data_provenance'] == 'synthetic' else 'REALI (LMU Shared Memory)'}**",
           f"- Verdetto: **{r['verdict']}**", f"- Versione: {r.get('app_version') or '?'}", "", "| Passo | Esito | Evidenza |", "|---|---|---|"]
    for k in r["order"]:
        s = r["steps"][k]
        out.append(f"| {r['titles'][k]} | {icon[s['status']]} | {s['evidence']} |")
    out += ["", *[f"- {n}" for n in r["notes"]], ""]
    return "\n".join(out)
