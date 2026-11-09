# TELEMETRY-FORMAT

Ogni struttura qui sotto riporta **provenienza** e **stato di verifica**. Legenda:
`[T3]` = trascritta da documentazione/codice pubblico di terze parti, **non** confrontata con un'installazione LMU reale;
`[IMPL]` = definita da questo progetto; `[SINT]` = solo dati sintetici.

## 1. Shared Memory nativa `LMU_Data` — [T3], NON verificata su LMU reale
- Fonte: `TinyPedal/pyLMUSharedMemory` (branch master, letto il 2026-11-09), che mappa gli header S397
  `InternalsPlugin.hpp` / `SharedMemoryInterface.hpp` (cartella `Support\SharedMemoryInterface` del gioco).
- Mapping Windows chiamato `LMU_Data`; `#pragma pack(4)`; 104 veicoli max (`MAX_MAPPED_VEHICLES`).
- Radice `SharedMemoryObjectOut` = `generic | paths | scoring | telemetry`.
- Dimensione attesa calcolata dal codice: **324 820 byte**. Tabella completa degli offset (generata da
  `python -m race_engineer layout`): [`layout-offsets.txt`](layout-offsets.txt).
- Implementazione: `backend/race_engineer/lmu/layout.py` (ogni offset è calcolato da ctypes, nessuno scritto a mano).
- **Cosa non è noto** senza LMU: se la versione installata ha la stessa dimensione/ordine; la frequenza di
  aggiornamento (si misura a runtime: `effective_hz`); il significato esatto dei segni di `mLocalAccel`;
  l'unità di `mWind`; se `mDeltaTime` coincide con l'intervallo dei campioni nel mapping.
- Controlli automatici a runtime: confronto dimensione reale del mapping (`VirtualQuery`) con 324 820 B, e — se
  presenti gli header installati — controllo dei *nomi* dei campi (`header_field_drift`; non verifica offset).
- Letture: il motore copia solo i dati del giocatore (~3 KB: scoring info + slot scoring + slot telemetria) e rilegge
  `mElapsedTime` dopo la copia per scartare letture "strappate".

### Convenzioni LMU rilevanti (dall'header, [T3])
| Campo | Significato |
|---|---|
| `mWheels[0..3]` | FL, FR, RL, RR |
| `mWheel.mTemperature[3]` | Kelvin; **sinistra/centro/destra**, non interno/centro/esterno |
| `mWheel.mWear` | 0..1 frazione del massimo |
| `mWheel.mBrakeTemp` | °C |
| `mUnfiltered*` / `mFiltered*` | input pilota grezzo / filtrato; sterzo −1..1 (sinistra→destra) |
| `VehicleScoring.mSector` | 0 = settore 3, 1 = settore 1, 2 = settore 2 |
| `ScoringInfo.mSession` | 0 test, 1-4 practice, 5-8 qualifica, 9 warmup, 10-13 gara |
| `ScoringInfo.mGamePhase` | 5 verde … 8 sessione finita |

## 2. Telemetria nativa DuckDB (`UserData\Telemetry\*.duckdb`) — [T3], NON verificata su file reali
Fonti pubbliche: `emilecarpentier/licor` (`docs/lmu_duckdb_format.md`), `lamerman/telemetry-visualizer-for-lmu`
(`TELEMETRY_DATA_DICTIONARY.txt`), `hockeylagu/LMULapTime` (`docs/TELEMETRY_FORMAT.md`), tutte del 2026, su file reali.
- 101 tabelle in un file osservato: `metadata(key,value)`, `channelsList(channelName,frequency,unit)`,
  `eventsList(eventName,unit)` + una tabella per canale/evento.
- Canali a frequenza fissa (es. `Ground Speed` 100 Hz): **senza timestamp**, colonna `value` oppure `value1..4`
  (ordine FL,FR,RL,RR *dedotto*, non dichiarato). Tempo = indice / frequenza (offset assoluto non noto dalla tabella).
- Eventi (`Lap`, `Gear`, `Lap Time`, `Current Sector`…): `ts DOUBLE` (secondi di sessione) + `value`/`value1..4`.
- `GPS Time` è usato da terzi come linea temporale master a 100 Hz.
- `metadata` osservati: Version, DriverName, SteamID, RecordingTime, SessionTime, SessionType, TrackName,
  TrackLayout, CarName, CarClass, WeatherConditions, e (in un file) `CarSetup` (JSON del setup, utile per la Fase 5).
- **Anomalia segnalata da terzi, da verificare**: i nomi `G Force Lat`/`G Force Long` sarebbero scambiati rispetto
  al contenuto. Questo progetto NON importa i canali G finché non è verificato su un file reale.
- Il reader (`importers/lmu_duckdb.py`) scopre tutto dal file stesso, apre in sola lettura (opzione copia scratch) e
  *segnala* canali core mancanti, tabelle non dichiarate e durate incoerenti invece di assumerli.
- Test con file **sintetici** costruiti secondo la struttura documentata (`synthetic/lmu_duckdb_fixture.py`).

## 3. Modello normalizzato — [IMPL]
Unità fisse: pedali 0..1, sterzo −1..1, °C, kPa, km/h, m, s. Provenienza per canale: `direct` / `computed`
(la conversione di unità è considerata `direct`). Il campione porta anche la provenienza *di sessione*
(`lmu_shm`, `duckdb_import`, `synthetic`, `manual`, `unavailable`); i canali `computed` e i valori `None` sono marcati.

| Channel | Type | Unit | Kind | Source (LMU field / formula) | Note |
|---|---|---|---|---|---|
| `session_time_s` | DOUBLE | s | direct | `telem.mElapsedTime` |  |
| `delta_time_s` | DOUBLE | s | direct | `telem.mDeltaTime` | time since last game update |
| `lap_number` | INTEGER |  | direct | `telem.mLapNumber` |  |
| `lap_time_s` | DOUBLE | s | computed | `telem.mElapsedTime - telem.mLapStartET` |  |
| `lap_dist_m` | DOUBLE | m | direct | `scoring[player].mLapDist` |  |
| `sector` | INTEGER |  | computed | `scoring[player].mSector remapped (1->1, 2->2, 0->3)` | LMU: 0=sector3, 1=sector1, 2=sector2 |
| `in_pits` | BOOLEAN |  | direct | `scoring[player].mInPits` |  |
| `lap_invalidated` | BOOLEAN |  | direct | `telem.mLapInvalidated` |  |
| `last_lap_time_s` | DOUBLE | s | direct | `scoring[player].mLastLapTime` | <=0 means none |
| `best_lap_time_s` | DOUBLE | s | direct | `scoring[player].mBestLapTime` | <=0 means none |
| `cur_sector1_s` | DOUBLE | s | direct | `scoring[player].mCurSector1` |  |
| `cur_sector2_s` | DOUBLE | s | direct | `scoring[player].mCurSector2` | cumulative (S1+S2) |
| `speed_kmh` | DOUBLE | km/h | computed | `3.6*|telem.mLocalVel|` | no native speed field |
| `rpm` | DOUBLE | rpm | direct | `telem.mEngineRPM` |  |
| `max_rpm` | DOUBLE | rpm | direct | `telem.mEngineMaxRPM` |  |
| `gear` | INTEGER |  | direct | `telem.mGear` | -1 reverse, 0 neutral |
| `water_temp_c` | DOUBLE | degC | direct | `telem.mEngineWaterTemp` |  |
| `oil_temp_c` | DOUBLE | degC | direct | `telem.mEngineOilTemp` |  |
| `fuel_l` | DOUBLE | L | direct | `telem.mFuel` |  |
| `fuel_capacity_l` | DOUBLE | L | direct | `telem.mFuelCapacity` |  |
| `brake_bias_rear` | DOUBLE |  | direct | `telem.mRearBrakeBias` | fraction on rear |
| `damage_dent_max` | INTEGER |  | computed | `max(telem.mDentSeverity[0..7])` | 0 none, 1 some, 2 more |
| `parts_detached` | BOOLEAN |  | direct | `telem.mDetached` |  |
| `overheating` | BOOLEAN |  | direct | `telem.mOverheating` |  |
| `throttle` | DOUBLE | 0..1 | direct | `telem.mUnfilteredThrottle` |  |
| `brake` | DOUBLE | 0..1 | direct | `telem.mUnfilteredBrake` |  |
| `clutch` | DOUBLE | 0..1 | direct | `telem.mUnfilteredClutch` |  |
| `steering` | DOUBLE | -1..1 | direct | `telem.mUnfilteredSteering` | LMU: left to right |
| `throttle_filtered` | DOUBLE | 0..1 | direct | `telem.mFilteredThrottle` |  |
| `brake_filtered` | DOUBLE | 0..1 | direct | `telem.mFilteredBrake` |  |
| `steering_filtered` | DOUBLE | -1..1 | direct | `telem.mFilteredSteering` |  |
| `local_accel_x_ms2` | DOUBLE | m/s2 | direct | `telem.mLocalAccel.x` |  |
| `local_accel_y_ms2` | DOUBLE | m/s2 | direct | `telem.mLocalAccel.y` |  |
| `local_accel_z_ms2` | DOUBLE | m/s2 | direct | `telem.mLocalAccel.z` |  |
| `pos_x_m` | DOUBLE | m | direct | `telem.mPos.x` | world frame, y = elevation |
| `pos_y_m` | DOUBLE | m | direct | `telem.mPos.y` |  |
| `pos_z_m` | DOUBLE | m | direct | `telem.mPos.z` |  |
| `ambient_temp_c` | DOUBLE | degC | direct | `scoring.mAmbientTemp` |  |
| `track_temp_c` | DOUBLE | degC | direct | `scoring.mTrackTemp` |  |
| `rain` | DOUBLE | 0..1 | direct | `scoring.mRaining` |  |
| `wind_ms` | DOUBLE | m/s | computed | `|scoring.mWind|` | unit of mWind not verified |
| `path_wetness_avg` | DOUBLE | 0..1 | direct | `scoring.mAvgPathWetness` |  |
| `session_code` | INTEGER |  | direct | `scoring.mSession` | 0 test day, 1-4 practice, 5-8 qualifying, 9 warmup, 10-13 race |
| `game_phase` | INTEGER |  | direct | `scoring.mGamePhase` |  |
| `in_realtime` | BOOLEAN |  | direct | `scoring.mInRealtime` |  |
| `tyre_fl_pressure_kpa` | DOUBLE | kPa | direct | `telem.mWheels[0].mPressure` |  |
| `tyre_fl_temp_left_c` | DOUBLE | degC | direct | `telem.mWheels[0].mTemperature[0] - 273.15 (Kelvin->degC)` | left/center/right = LMU wheel-relative, not inner/outer |
| `tyre_fl_temp_center_c` | DOUBLE | degC | direct | `telem.mWheels[0].mTemperature[1] - 273.15` | left/center/right = LMU wheel-relative, not inner/outer |
| `tyre_fl_temp_right_c` | DOUBLE | degC | direct | `telem.mWheels[0].mTemperature[2] - 273.15` | left/center/right = LMU wheel-relative, not inner/outer |
| `tyre_fl_carcass_temp_c` | DOUBLE | degC | direct | `telem.mWheels[0].mTireCarcassTemperature - 273.15` | left/center/right = LMU wheel-relative, not inner/outer |
| `tyre_fl_wear` | DOUBLE | 0..1 | direct | `telem.mWheels[0].mWear (fraction of max)` |  |
| `tyre_fl_brake_temp_c` | DOUBLE | degC | direct | `telem.mWheels[0].mBrakeTemp` | left/center/right = LMU wheel-relative, not inner/outer |
| `tyre_fr_pressure_kpa` | DOUBLE | kPa | direct | `telem.mWheels[1].mPressure` |  |
| `tyre_fr_temp_left_c` | DOUBLE | degC | direct | `telem.mWheels[1].mTemperature[0] - 273.15 (Kelvin->degC)` | left/center/right = LMU wheel-relative, not inner/outer |
| `tyre_fr_temp_center_c` | DOUBLE | degC | direct | `telem.mWheels[1].mTemperature[1] - 273.15` | left/center/right = LMU wheel-relative, not inner/outer |
| `tyre_fr_temp_right_c` | DOUBLE | degC | direct | `telem.mWheels[1].mTemperature[2] - 273.15` | left/center/right = LMU wheel-relative, not inner/outer |
| `tyre_fr_carcass_temp_c` | DOUBLE | degC | direct | `telem.mWheels[1].mTireCarcassTemperature - 273.15` | left/center/right = LMU wheel-relative, not inner/outer |
| `tyre_fr_wear` | DOUBLE | 0..1 | direct | `telem.mWheels[1].mWear (fraction of max)` |  |
| `tyre_fr_brake_temp_c` | DOUBLE | degC | direct | `telem.mWheels[1].mBrakeTemp` | left/center/right = LMU wheel-relative, not inner/outer |
| `tyre_rl_pressure_kpa` | DOUBLE | kPa | direct | `telem.mWheels[2].mPressure` |  |
| `tyre_rl_temp_left_c` | DOUBLE | degC | direct | `telem.mWheels[2].mTemperature[0] - 273.15 (Kelvin->degC)` | left/center/right = LMU wheel-relative, not inner/outer |
| `tyre_rl_temp_center_c` | DOUBLE | degC | direct | `telem.mWheels[2].mTemperature[1] - 273.15` | left/center/right = LMU wheel-relative, not inner/outer |
| `tyre_rl_temp_right_c` | DOUBLE | degC | direct | `telem.mWheels[2].mTemperature[2] - 273.15` | left/center/right = LMU wheel-relative, not inner/outer |
| `tyre_rl_carcass_temp_c` | DOUBLE | degC | direct | `telem.mWheels[2].mTireCarcassTemperature - 273.15` | left/center/right = LMU wheel-relative, not inner/outer |
| `tyre_rl_wear` | DOUBLE | 0..1 | direct | `telem.mWheels[2].mWear (fraction of max)` |  |
| `tyre_rl_brake_temp_c` | DOUBLE | degC | direct | `telem.mWheels[2].mBrakeTemp` | left/center/right = LMU wheel-relative, not inner/outer |
| `tyre_rr_pressure_kpa` | DOUBLE | kPa | direct | `telem.mWheels[3].mPressure` |  |
| `tyre_rr_temp_left_c` | DOUBLE | degC | direct | `telem.mWheels[3].mTemperature[0] - 273.15 (Kelvin->degC)` | left/center/right = LMU wheel-relative, not inner/outer |
| `tyre_rr_temp_center_c` | DOUBLE | degC | direct | `telem.mWheels[3].mTemperature[1] - 273.15` | left/center/right = LMU wheel-relative, not inner/outer |
| `tyre_rr_temp_right_c` | DOUBLE | degC | direct | `telem.mWheels[3].mTemperature[2] - 273.15` | left/center/right = LMU wheel-relative, not inner/outer |
| `tyre_rr_carcass_temp_c` | DOUBLE | degC | direct | `telem.mWheels[3].mTireCarcassTemperature - 273.15` | left/center/right = LMU wheel-relative, not inner/outer |
| `tyre_rr_wear` | DOUBLE | 0..1 | direct | `telem.mWheels[3].mWear (fraction of max)` |  |
| `tyre_rr_brake_temp_c` | DOUBLE | degC | direct | `telem.mWheels[3].mBrakeTemp` | left/center/right = LMU wheel-relative, not inner/outer |

Non ancora acquisiti (non verificati o non necessari alla Fase 1): angolo sterzo in gradi (`mVisualSteeringWheelRange`/
`mPhysicalSteeringWheelRange`: unità non verificata), accelerazioni in G (segni degli assi locali non verificati),
temperature interne/centro/esterno (LMU espone sinistra/centro/destra), consumo carburante (calcolato in Fase 6 su giri validi).

## 4. Stima campioni persi
`lost = round((ET_n − ET_{n−1}) / mDeltaTime) − 1` quando `gap > 1.5·mDeltaTime`. Euristica **non verificata** su LMU
(dipende dal significato reale di `mDeltaTime`); i test sintetici ne verificano il conteggio esatto sul layout simulato.
