# AI-GROUNDING  (progetto — NON ancora implementato, Fase 4)
1. L'AI non vede telemetria grezza: riceve solo **fatti calcolati** dal motore d'analisi, ciascuno con id, valore, unità, provenienza, giri/curve di riferimento.
2. Risposta strutturata: osservazione misurata · interpretazione · suggerimento · confidenza · dati usati (id dei fatti).
3. Validatore post-risposta: ogni numero nel testo deve corrispondere a un fatto fornito; altrimenti la risposta viene respinta/riformulata.
4. Dato mancante ⇒ dichiararlo. Correlazione ≠ causalità. Nessun valore di setup fuori dai limiti verificati per la vettura.
5. Interfaccia provider-agnostic (locale/API), timeout, fallback, budget costi; analisi e telemetria funzionano senza AI.
