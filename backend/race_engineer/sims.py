"""Registry of the racing simulators shown in the app, and the persistent choice of the user.

HONESTY RULE: a simulator is ``supported`` ONLY when this app contains code that really reads its telemetry (today: Le Mans
Ultimate). The telemetry facts of the other games below come from the games' own public documentation / community SDKs as known when
this was written; NONE of them has been tested in this app. They are shown as ``planned`` or ``evaluating`` and cannot be selected.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

SUPPORTED, PLANNED, EVALUATING = "supported", "planned", "evaluating"
STATUS_LABEL_IT = {SUPPORTED: "Supportato", PLANNED: "In arrivo", EVALUATING: "Da verificare"}
DEFAULT_SIM = "lmu"


@dataclass(frozen=True)
class Sim:
    id: str
    name: str
    short: str                    # 2-4 letters shown in the badge (no trademarked logo is bundled)
    color: str
    status: str
    description: str              # one plain sentence for the card
    how: str                      # how the data would reach the app, in plain words
    steps: tuple[str, ...] = ()   # what the user must do to connect (only meaningful for supported sims)
    tech: dict = field(default_factory=dict)   # advanced details: mechanism, data, limits (shown in an expandable section)

    def to_json(self) -> dict:
        d = asdict(self)
        d["steps"] = list(self.steps)
        d["status_label"] = STATUS_LABEL_IT[self.status]
        d["selectable"] = self.status == SUPPORTED
        return d


SIMS: tuple[Sim, ...] = (
    Sim("lmu", "Le Mans Ultimate", "LMU", "#e11d48", SUPPORTED,
        "Endurance e Hypercar. È il simulatore già collegato all'app.",
        "Memoria condivisa del gioco (sola lettura, nessun programma da installare).",
        ("Apri Le Mans Ultimate.", "Nel gioco vai in Impostazioni → Gameplay e attiva «Enable Plugins», poi riavvia il gioco.",
         "Entra in pista (anche in prova libera): l'app inizia da sola a raccogliere i dati."),
        {"mechanism": "Shared Memory «LMU_Data» (nativa del gioco) + file DuckDB nativi importabili",
         "realtime": "sì, ~250 letture al secondo", "data": "velocità, giri motore, marcia, pedali, sterzo, gomme, carburante, posizione in pista, giri e settori",
         "limits": "Il layout della memoria è stato trascritto da fonti pubbliche e non è ancora stato verificato con il gioco reale (vedi docs/LMU-INTEGRATION.md).",
         "setup": "«Enable Plugins» attivo nel gioco"}),
    Sim("acc", "Assetto Corsa Competizione", "ACC", "#2563eb", PLANNED,
        "GT World Challenge con regole e auto reali.",
        "Memoria condivisa del gioco (già attiva di serie).", (),
        {"mechanism": "Shared Memory (physics / graphics / static) + Broadcasting API via UDP",
         "realtime": "sì (fisica ~333 Hz, grafica ~60 Hz)", "data": "fisica dell'auto, gomme, freni, carburante, giri, meteo, posizione",
         "limits": "Non ancora letto da questa app. Pochi dati sugli avversari senza la Broadcasting API.", "setup": "nessuna"}),
    Sim("ac", "Assetto Corsa", "AC", "#0d9488", PLANNED,
        "Il classico, con tantissime auto e circuiti aggiunti dalla community.",
        "Memoria condivisa del gioco (già attiva di serie).", (),
        {"mechanism": "Shared Memory (acpmf_physics / graphics / static) + UDP Remote Telemetry",
         "realtime": "sì", "data": "fisica dell'auto, gomme, freni, carburante, giri, posizione",
         "limits": "Non ancora letto da questa app. Alcuni campi variano con le mod.", "setup": "nessuna"}),
    Sim("ac_evo", "Assetto Corsa EVO", "EVO", "#7c3aed", EVALUATING,
        "Il nuovo capitolo della serie (accesso anticipato).",
        "Non sappiamo ancora se e come il gioco offra i dati.", (),
        {"mechanism": "Da verificare: nessuna interfaccia dati documentata in modo affidabile", "realtime": "sconosciuto",
         "data": "sconosciuti", "limits": "Gioco ancora in sviluppo: l'interfaccia dati può cambiare o non esistere.", "setup": "sconosciuta"}),
    Sim("iracing", "iRacing", "iR", "#dc2626", PLANNED,
        "Simulatore online con licenze e gare organizzate.",
        "Memoria condivisa del gioco (SDK ufficiale), già attiva di serie.", (),
        {"mechanism": "iRacing SDK (irsdk) via memory-mapped file, 60 Hz; file .ibt a fine sessione",
         "realtime": "sì (60 Hz)", "data": "oltre 200 canali: auto, gomme, carburante, giri, avversari",
         "limits": "Non ancora letto da questa app. Alcuni dati sono limitati dal servizio online.", "setup": "nessuna"}),
    Sim("rf2", "rFactor 2", "rF2", "#ea580c", PLANNED,
        "Fisica molto dettagliata, base tecnica di Le Mans Ultimate.",
        "Serve installare un plugin gratuito della community nel gioco.", (),
        {"mechanism": "rFactor 2 Shared Memory Map Plugin (da installare e attivare nel gioco)", "realtime": "sì",
         "data": "telemetria completa, gomme, danni, avversari", "limits": "Richiede un plugin esterno; non ancora letto da questa app.",
         "setup": "installare e attivare il plugin"}),
    Sim("ams2", "Automobilista 2", "AMS2", "#ca8a04", PLANNED,
        "Auto brasiliane e internazionali, meteo dinamico.",
        "Memoria condivisa del gioco, da attivare nelle opzioni.", (),
        {"mechanism": "Shared Memory in formato Project CARS 2 (da attivare nelle opzioni) + UDP", "realtime": "sì",
         "data": "fisica dell'auto, gomme, carburante, giri, avversari", "limits": "Non ancora letto da questa app.",
         "setup": "attivare «Shared Memory» nelle opzioni di sistema"}),
    Sim("r3e", "RaceRoom Racing Experience", "R3E", "#0891b2", PLANNED,
        "Gare online e auto GT/DTM.",
        "Memoria condivisa del gioco (già attiva di serie).", (),
        {"mechanism": "Shared Memory «$R3E» (SDK del gioco)", "realtime": "sì", "data": "auto, gomme, carburante, giri, posizione, avversari",
         "limits": "Non ancora letto da questa app.", "setup": "nessuna"}),
    Sim("f1", "F1 (serie recente)", "F1", "#b91c1c", PLANNED,
        "Il videogioco ufficiale della Formula 1.",
        "Il gioco invia i dati in rete (UDP) al PC: va attivato nelle opzioni.", (),
        {"mechanism": "UDP Telemetry (porta 20777 di default)", "realtime": "sì (fino a 60 Hz)",
         "data": "auto, gomme, danni, carburante, ERS, giri, avversari", "limits": "Il formato cambia ogni anno; non ancora letto da questa app.",
         "setup": "attivare «UDP Telemetry» nelle opzioni del gioco"}),
    Sim("pcars2", "Project CARS 2", "pC2", "#4b5563", PLANNED,
        "Simulatore con meteo e ciclo giorno/notte.",
        "Memoria condivisa del gioco, da attivare nelle opzioni.", (),
        {"mechanism": "Shared Memory (da attivare nelle opzioni) + UDP", "realtime": "sì",
         "data": "auto, gomme, carburante, giri, avversari", "limits": "Gioco non più aggiornato; non ancora letto da questa app.",
         "setup": "attivare «Shared Memory» nelle opzioni"}),
)
BY_ID = {s.id: s for s in SIMS}
SELECTED_KEY = "app.selected_sim"


class UnknownSim(ValueError):
    pass


class NotSupportedSim(ValueError):
    pass


def get(sim_id: str) -> Sim:
    try:
        return BY_ID[sim_id]
    except KeyError:
        raise UnknownSim(f"Simulatore sconosciuto: {sim_id}") from None


def selected(catalog) -> str | None:
    """The last chosen simulator, or None on first start. A stored id that is unknown/not supported (e.g. after a downgrade) counts as none."""
    sid = catalog.get_setting(SELECTED_KEY)
    return sid if sid in BY_ID and BY_ID[sid].status == SUPPORTED else None


def select(catalog, sim_id: str) -> Sim:
    sim = get(sim_id)
    if sim.status != SUPPORTED:
        raise NotSupportedSim(f"{sim.name} non è ancora supportato: l'app non sa ancora leggere i suoi dati. Scegli un simulatore con l'etichetta «Supportato».")
    catalog.put_setting(SELECTED_KEY, sim.id)
    return sim
