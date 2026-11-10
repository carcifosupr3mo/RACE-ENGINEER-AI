"""Coaching instructions: turns ONE measured finding into what / where / how / why / goal, in Italian, text only.

Pure function of the finding (no state, no LLM, no network): it works offline. Rules:
* every number in the text is taken from the finding's own evidence - nothing is invented;
* distances in metres are written only when the confidence is not "bassa" (otherwise the wording is qualitative);
* the causes that the telemetry cannot prove (traffic, understeer/oversteer, wheelspin) are listed under ``missing``, never asserted;
* corner numbers are the software's provisional ids (P1, P2, ...) unless the user named the corners: this is said, not hidden.
"""
from __future__ import annotations

MISSING_ALWAYS = ["traffico e avversari: non rilevabili con i canali acquisiti"]
MISSING_BY_TYPE = {
    "inefficient_line": ["sottosterzo/sovrasterzo: non stimati (una sola misura non basta)"],
    "mid_loss": ["causa della perdita a centro curva non dimostrata dalla sola telemetria"],
    "entry_loss": ["causa della perdita in ingresso non dimostrata dalla sola telemetria"],
    "exit_loss": ["causa della perdita in uscita non dimostrata dalla sola telemetria"],
    "aggressive_throttle": ["perdita di trazione/pattinamento: non misurato (nessun canale di slittamento)"],
    "gear_choice": ["la marcia del riferimento non è provata come ottimale: è solo il tuo giro di confronto"],
    "insufficient_min_speed": ["sottosterzo/sovrasterzo: non stimati"],
}


def corner_label(cid: str, provisional: bool = True) -> str:
    n = cid[1:] if cid[:1] == "P" and cid[1:].isdigit() else None
    return f"CURVA {cid}" if n is None or not provisional else f"CURVA P{n}"


def _m(ev: dict, key: str, precise: bool) -> str:
    v = ev.get(key)
    if v is None:
        return "poco"
    return f"circa {abs(v):.0f} m" if precise else "un po'"


def _s(imp) -> str:
    return "" if imp is None else f" Tempo in gioco in questa fase: {abs(imp):.2f} s."


def _t(type_: str, ev: dict, precise: bool, imp) -> tuple[str, str, str, str, str]:
    """-> (headline, what, how, why, goal)"""
    g = ev.get
    if type_ == "early_braking":
        return ("FRENA UN PO' PIÙ TARDI", "Inizi a frenare prima del tuo giro di riferimento.",
                f"Sposta in avanti il punto di frenata di {_m(ev, 'diff_m', precise)}, con la stessa pressione.",
                f"Hai frenato {_m(ev, 'diff_m', precise)} prima del riferimento senza guadagnare velocità minima.",
                "Recuperare tempo all'ingresso mantenendo la stessa uscita." + _s(imp))
    if type_ == "inefficient_late_braking":
        return ("ANTICIPA LA FRENATA", "Freni più tardi del riferimento, ma questo ti costa dopo l'ingresso.",
                f"Anticipa la frenata di {_m(ev, 'diff_m', precise)}: l'ingresso sarà un po' più lento, la curva nel suo insieme più veloce.",
                f"Frenando {_m(ev, 'diff_m', precise)} dopo il riferimento perdi velocità minima o uscita"
                + (f" (minima {g('min_speed_diff_kmh'):+.0f} km/h)" if g("min_speed_diff_kmh") is not None else "") + ".",
                "Migliorare percorrenza e uscita, anche a costo di un ingresso meno estremo." + _s(imp))
    if type_ == "braking_too_long":
        return ("RILASCIA IL FRENO PRIMA", "Resti sul freno più a lungo del riferimento.",
                f"Inizia a rilasciare il freno circa {abs((g('lap_len_m') or 0) - (g('ref_len_m') or 0)):.0f} m prima, in modo graduale." if precise
                else "Inizia a rilasciare il freno un po' prima, in modo graduale.",
                "La frenata dura più del tuo riferimento e il rilascio arriva più avanti.",
                "Arrivare all'inserimento con la vettura più libera." + _s(imp))
    if type_ == "abrupt_release":
        return ("RILASCIA IL FRENO GRADUALMENTE", "Il rilascio del freno è più brusco del riferimento.",
                "Tieni una pressione iniziale controllata e allenta il freno in modo progressivo durante l'inserimento.",
                "La pressione cade su una distanza molto più corta di quella del riferimento e il centro curva perde tempo.",
                "Migliorare la percorrenza senza compromettere l'uscita." + _s(imp))
    if type_ == "delayed_acceleration":
        d = g("diff_m")
        if d is None and g("lap_throttle_on_m") is not None and g("ref_throttle_on_m") is not None:
            d = g("lap_throttle_on_m") - g("ref_throttle_on_m")
        return ("RIAPRI IL GAS PRIMA", "Riparti con l'acceleratore più tardi del riferimento.",
                f"Cerca di riaprire il gas circa {abs(d):.0f} m prima, appena la vettura è stabile." if (precise and d is not None)
                else "Cerca di riaprire il gas prima, appena la vettura è stabile.",
                "Il punto in cui torni sul gas è dopo quello del riferimento.",
                "Uscire dalla curva con più velocità." + _s(imp))
    if type_ == "insufficient_min_speed":
        return ("PORTA PIÙ VELOCITÀ AL CENTRO CURVA", "La velocità minima è inferiore al riferimento.",
                f"Entra con un filo di velocità in più o rilascia il freno prima, per tenere circa {abs(g('diff_kmh') or 0):.0f} km/h in più all'apice." if precise
                else "Cerca di non rallentare troppo all'apice.",
                f"Velocità minima {g('lap_min_kmh')} km/h contro {g('ref_min_kmh')} km/h del riferimento.",
                "Aumentare la velocità di percorrenza senza perdere l'uscita." + _s(imp))
    if type_ == "inefficient_line":
        return ("PULISCI LA TRAIETTORIA", "Usi più sterzo del riferimento attorno all'apice.",
                "Cerca una traiettoria più larga all'ingresso e un punto di corda che ti permetta di sterzare meno e accelerare prima.",
                f"Sterzo medio {g('ratio') or 0:.2f}× quello del riferimento, con minima più bassa.",
                "Ridurre le correzioni e iniziare ad accelerare prima." + _s(imp))
    if type_ == "insufficient_trail_braking":
        return ("MANTIENI UN PO' DI FRENO IN INSERIMENTO", "Lasci il freno troppo presto mentre inizi a sterzare.",
                "Dopo il picco rilascia il freno gradualmente mentre giri, invece di staccarlo del tutto prima dello sterzo.",
                f"Freno attivo mentre sterzi per {g('lap_trail_m'):.0f} m contro {g('ref_trail_m'):.0f} m del riferimento." if precise
                else "Il tratto in cui freni e sterzi insieme è molto più corto del riferimento.",
                "Aiutare l'inserimento e migliorare la percorrenza." + _s(imp))
    if type_ == "excess_trail_braking":
        return ("LASCIA IL FRENO PRIMA DELL'APICE", "Resti sul freno troppo a lungo mentre sei già in curva.",
                "Termina il rilascio del freno prima del punto di corda, così la vettura è libera di ripartire.",
                f"Freno attivo mentre sterzi per {g('lap_trail_m'):.0f} m contro {g('ref_trail_m'):.0f} m del riferimento." if precise
                else "Il tratto in cui freni e sterzi insieme è molto più lungo del riferimento.",
                "Recuperare velocità a centro curva e in uscita." + _s(imp))
    if type_ == "aggressive_throttle":
        return ("APRI IL GAS PIÙ PROGRESSIVAMENTE", "Dai gas più bruscamente del riferimento e l'uscita perde tempo.",
                "Apri l'acceleratore in modo graduale mentre raddrizzi lo sterzo, senza saltare subito a fondo.",
                f"Il gas passa dal 10% al 90% in {g('lap_ramp_m'):.0f} m contro {g('ref_ramp_m'):.0f} m del riferimento, con uscita più lenta." if precise
                else "Il gas sale molto più in fretta che nel riferimento e l'uscita è più lenta.",
                "Uscire più veloce con una vettura più stabile." + _s(imp))
    if type_ == "gear_choice":
        return (f"PROVA LA MARCIA {g('ref_gear'):.0f} ALL'APICE", "Usi una marcia diversa dal giro di riferimento.",
                f"Il riferimento usa la marcia {g('ref_gear'):.0f} all'apice, tu la {g('lap_gear'):.0f}: prova a farla combaciare.",
                "La curva è più lenta con la marcia diversa; non è provato che sia la causa.",
                "Verificare se la marcia del riferimento ti dà una uscita migliore." + _s(imp))
    if type_ in ("entry_loss", "mid_loss", "exit_loss"):
        ph = {"entry_loss": "all'ingresso", "mid_loss": "a centro curva", "exit_loss": "in uscita"}[type_]
        return (f"STAI PERDENDO TEMPO {ph.upper()}", f"Perdi tempo {ph} rispetto al riferimento.",
                "Concentrati su questa fase al prossimo passaggio; la telemetria non indica da sola la causa precisa.",
                f"La differenza di tempo in questa fase è {abs(g('phase_delta_s') or 0):.2f} s rispetto al riferimento.",
                "Capire cosa cambia in questa fase al prossimo giro." + _s(None))
    if type_ == "inconsistent":
        return ("FRENA SEMPRE NELLO STESSO PUNTO", "Il punto di frenata cambia da giro a giro.",
                f"Scegli un riferimento visivo e frena sempre lì: oggi varia di ±{g('brake_std_m'):.0f} m." if precise
                else "Scegli un riferimento visivo e frena sempre lì.",
                f"Dispersione del punto di frenata su {g('laps')} giri.",
                "Rendere la curva ripetibile prima di cercare il limite.")
    return (type_.upper().replace("_", " "), "Differenza rispetto al riferimento.", "", "", "")


def build(c: dict, *, corner: dict | None = None, mode: dict | None = None, reference: dict | None = None, now: float | None = None) -> dict:
    """``c`` = Candidate.to_json(). Returns the instruction object shown on the Driving Display."""
    ev = c.get("evidence") or {}
    level = (c.get("confidence") or {}).get("level", "bassa")
    precise = level in ("alta", "media")
    head, what, how, why, goal = _t(c["type"], ev, precise, c.get("impact_s"))
    provisional = True if corner is None else bool(corner.get("provisional", True))
    label = corner_label(c["corner"], provisional)
    missing = list(MISSING_BY_TYPE.get(c["type"], [])) + MISSING_ALWAYS
    if provisional:
        missing.append("numerazione delle curve provvisoria (P1, P2, …): non è la numerazione ufficiale del circuito")
    if not precise:
        missing.append("confidenza bassa: distanze e valori numerici non indicati")
    measured = {k: v for k, v in ev.items() if k.startswith("lap_") or k.startswith("ref_")}
    computed = {k: v for k, v in ev.items() if k not in measured}
    return {
        "id": c["id"], "corner": c["corner"], "corner_label": label, "type": c["type"], "problem": c["label"], "phase": c["phase"],
        "headline": head, "what": what, "how": how, "why": why, "goal": goal, "text": f"{label} — {head}",
        "impact_s": c.get("impact_s"), "confidence": c["confidence"], "lap": c["lap"], "ref_lap": c.get("ref_lap"), "repeat": c.get("repeat", 1),
        "evidence": {"measured": measured, "computed": computed,
                     "interpretation": why, "missing": missing},
        "session_mode": None if mode is None else mode.get("label"),
        "reference_reliability": None if reference is None else (reference.get("level")),
        "timestamp": now, "provenance": "computed", "language": "it",
    }
