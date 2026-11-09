# ANALYSIS-METHODS  (progetto — NON ancora implementato, Fase 3)
Principi vincolanti: allineamento dei giri per **distanza percorsa** (`lap_dist_m`) con interpolazione e controllo qualità
(buchi, monotonia, lunghezza giro); mai confronto di campioni per timestamp. Ogni osservazione = numeri + provenienza.
Giri: *completo* / *incompleto* / *invalido* (`lap_invalidated`, pit in/out, copertura distanza) — non cancellare mai i dati.
Curve: segmenti provvisori numerati finché il circuito non è mappato; nessun numero di curva inventato; editor manuale.
Validazione: scenari sintetici già disponibili (`synthetic/track.py`) con differenze note (+40 m frenata, +35 m gas, ecc.).
