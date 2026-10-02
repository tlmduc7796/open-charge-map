# ML data pipeline architecture

## Rule: adapt by source, build by prediction task, train by model

```text
UrbanEV / ACN export / OCPP operator export
                 │
                 ▼
        source-specific adapter
                 │
                 ▼
 canonical occupancy / sessions / telemetry / port-status tables
                 │
       ┌─────────┼──────────┐
       ▼         ▼          ▼
 occupancy   RDM dataset  connector-aware Markov state dataset
       │         │          │
 XGBoost/LSTM quantile RDM Markov transition table
```

Do **not** add one extractor per model.  A new data provider gets one adapter
which produces the same canonical tables.  Model builders therefore do not
need to know whether data came from UrbanEV, ACN or an operator.

## Canonical products

| Product | Grain | Required timing semantics | Consumers |
|---|---|---|---|
| `occupancy_history` | station snapshot | `observed_at` is when state was true; `received_at` is ingestion time | XGBoost, LSTM, aggregate Markov inputs |
| `sessions` | one plugged-in vehicle | `disconnect_at` is physical port release; `done_charging_at` is not | RDM labels, replay audit |
| `session_telemetry` | one observed session point | energy/power must only be what was known at `observed_at` | RDM XGBoost/LSTM |
| `port_status` | port snapshot/event | connector-specific state plus sequence/freshness | Markov and future live DES |

Every canonical row carries source/schema/quality/backfill metadata.  Raw
exports live outside Git under `ml/data/raw/<source>/`; canonical and model
datasets get a neighbouring manifest with source checksums.

## Commands

```powershell
# Existing UrbanEV processed parquet -> canonical history and temporal split.
.\.venv\Scripts\python.exe ml\src\prepare_occupancy_history.py `
  --input ml\data\processed\urbanev\urbanev_processed.parquet `
  --output ml\data\silver\urbanev\occupancy_history.parquet `
  --source urbanev `
  --train-end "2023-01-15T23:55:00+08:00" `
  --validation-end "2023-01-31T23:55:00+08:00"

# Downloaded ACN exports only; this command does not call ACN's protected API.
.\.venv\Scripts\python.exe ml\src\prepare_acn_data.py `
  --sessions C:\data\acn_sessions.json `
  --sessions-output ml\data\silver\acn\sessions.parquet `
  --telemetry C:\data\acn_telemetry.parquet `
  --telemetry-output ml\data\silver\acn\telemetry.parquet

# Build the actual RDM supervised rows, then train only against validation.
.\.venv\Scripts\python.exe ml\src\build_rdm_dataset.py `
  --sessions ml\data\silver\acn\sessions.parquet `
  --telemetry ml\data\silver\acn\telemetry.parquet `
  --output ml\data\gold\rdm\rdm_observations.parquet `
  --train-end "2024-06-30T23:59:59+00:00" `
  --validation-end "2024-07-31T23:59:59+00:00"

.\.venv\Scripts\python.exe ml\src\train_rdm_quantile.py --execute
```

`--evaluate-test` is intentionally a separate opt-in on model trainers.  It
marks the run exploratory until its protocol is frozen; model selection must
use validation only.

## Adding a future dataset

1. Keep the raw export immutable and record its provenance/terms outside Git.
2. Add `normalize_<source>_*` functions in `ml/src/data_pipeline/adapters.py`
   (or a dedicated adapter module once it is large).
3. Map source fields into canonical names; never use a source field as a model
   feature just because it has a convenient name.
4. Add fixture tests for timezone, source ordering, duplicates, censored
   sessions, connector semantics and physical capacity.
5. Reuse `prepare_occupancy_history`, `build_rdm_dataset`, or
   `build_markov_state_dataset`.  Only add a new dataset builder when the
   label/question is genuinely different.
