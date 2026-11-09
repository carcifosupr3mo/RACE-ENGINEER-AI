# AI gratuita multi-provider
Ordine: 1 NVIDIA `nvidia/nemotron-3.5-lightning-30b-a3b` → 2 alternativa NVIDIA (solo se configurata con `alternative_confirmed_free: true`) → 3 Groq `openai/gpt-oss-120b` → 4 Groq `qwen/qwen3.8-27b` → analisi locale.
Endpoint: `https://integrate.api.nvidia.com/v1`, `https://api.groq.com/openai/v1` (OpenAI-compatibili).

Componenti (`backend/race_engineer/ai/providers/`): `adapters` (NVIDIAAdapter, GroqAdapter, classificazione errori 401/402/404/429/5xx/timeout/rete), `quota` (AIQuotaManager: RPM/RPD/TPM/TPD persistiti in SQLite, riserva 80%, header Groq), `health` (AIHealthMonitor: circuit breaker con backoff esponenziale max 120 s, auth 1 h, sonde di recupero), `manager` (AIProviderManager), `request_queue` (AIRequestQueue: priorità Critical/High/Normal/Low, dedup/supersede, cooldown, TTL anti-stale, tetto orario, persistenza e recupero dopo crash), `credentials` (env var → `keyring`/Gestione credenziali; chiavi mai in chiaro, mai al frontend, redazione nei log), `selftest`.
Sicurezza "solo gratis": un modello è chiamabile solo se in `allowed_models`; i limiti locali bloccano le richieste prima dell'invio; nessun modello a pagamento è configurato.
Limiti NVIDIA: **non verificati** (default prudente 30 RPM); i limiti Groq sono quelli free pubblicati il 2026-11-09 e vanno riverificati.
Le risposte AI dell'endurance sono accettate solo se ogni numero compare nei dati inviati (`ungrounded_numbers`); altrimenti restano come `rejected_ungrounded` e vale il testo locale.

# Endurance (24 h)
`endurance/`: `EventDetector` (giri, carburante, pit/stint, gomme, motore, danni a fronte, pioggia con isteresi), `RaceMemory` (SQLite locale, indipendente dal provider), `EndurancePipeline` (riepilogo ogni 5 min, fine stint, pit stop, eventi critici, report finale; testo locale salvato SEMPRE per primo; l'AI riceve solo aggregati), `EnduranceService` (collegamento al motore di acquisizione; le sessioni sintetiche non consumano quota). Stato dello detector persistito: dopo un riavvio non si ripetono eventi.
Simulazione: `python -m race_engineer endurance-sim --hours 24` (provider finti con interruzioni programmate, 2 riavvii).
