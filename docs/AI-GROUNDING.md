# AI-GROUNDING  (Fase 4 — implementato; validato con dati sintetici e provider FINTI)

Codice: `backend/race_engineer/ai/{facts,engineer,provider,validator,chat}.py`.

## Pipeline
1. **Base fatti** (`facts.py`): per la sessione si calcolano fatti `Fact(id, kind, text, values, provenance)`: riepilogo (S1,S2), tempi giro (L*),
   miglior settore (SEC*), curve del giro migliore (C*), delta per giro (D*), osservazioni (F*), perdita per curva (LOSS.*), costanza (K.*), passo (PACE),
   carburante (FUEL), gomme (TYRE), storico (HIST), canali mancanti (MISS). Nessuna cifra esiste fuori dai fatti.
2. **Ingegnere a regole** (`engineer.py`): classifica la domanda (IT/EN) e produce sempre una risposta strutturata:
   *osservazioni misurate* (con id dei fatti) · *interpretazione tecnica* (linguaggio «compatibile con», mai causale) · *suggerimento* ·
   *confidenza* (bassa <3 giri, media 3–5 o curve provvisorie, alta ≥6; ridotta se allineamento scarso; segnala i dati sintetici) ·
   *dati utilizzati* · *dati mancanti*. Funziona senza alcuna AI esterna.
3. **LLM opzionale** (`provider.py`, `chat.py`): interfaccia `LLMProvider` (OpenAI-compatibile → OpenAI/Ollama/LM Studio/llama.cpp; Anthropic),
   catena con **fallback**, **timeout**, **budget giornaliero di token** e contabilità dei costi. Le chiavi si leggono SOLO da variabili d'ambiente
   (`api_key_env`); l'API rifiuta impostazioni che contengono segreti. All'LLM vengono inviati solo i fatti pertinenti (nessuna telemetria grezza).
4. **Validatore** (`validator.py`): la risposta dell'LLM è accettata solo se è JSON con tutti i campi, ogni osservazione cita id di fatti esistenti,
   e **ogni numero** nel testo è presente nei fatti (arrotondamenti ammessi). Altrimenti viene scartata e si usa la risposta a regole
   (`llm.rejected` riporta i motivi). La confidenza finale è il minimo tra LLM e regole.
5. Conversazioni salvate in SQLite (`messages`).

## Verifiche
Ogni risposta a regole per le 9 domande tipiche passa lo stesso validatore (ha già individuato e fatto correggere un numero non tracciato: il trend del passo).
Test: numeri inventati, id inesistenti, osservazioni senza fatti, JSON malformato → respinti; errore/timeout/budget → fallback; HTTP con trasporto simulato.
**Non testato** con un LLM reale (nessuna chiave/rete a disposizione): prompt e formato JSON potrebbero richiedere taratura.
