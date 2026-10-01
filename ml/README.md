# ML pipeline — data-first, cloud-ready

This directory contains every ML-specific executable. `scripts/` at repository
root is reserved for application/static-data tooling; UrbanEV acquisition, data
preparation, feature construction, training and Markov post-processing all live
under `ml/src/`. A notebook is useful for EDA, charts and explaining an
experiment, but it must call these scripts rather than becoming the source of
truth for preprocessing or training.

## Current state

No occupancy model is trained or deployed. `UrbanEV` is a historical dataset
from Shenzhen, China, used only for pipeline validation and source-domain
benchmarking; it is not proof that a model will perform well for Vietnamese
stations. The backend intentionally remains on its safe persistence fallback
until an approved model release exists.

For the current delivery order—deterministic frontend Queue Lab first, then
Monte Carlo DES, then ACN-Data/RDM—read
[`docs/QUEUE_LAB_DES_ROADMAP.md`](docs/QUEUE_LAB_DES_ROADMAP.md). It also records why the
current UrbanEV residual-XGBoost result is exploratory and does not justify a
new LSTM run or deployment.

The feature profiles formalize the data-gap decision:

| Profile | Inputs | Can serve now? | Use |
|---|---|---:|---|
| `baseline` | validated occupancy history | Yes | lags-only XGBoost comparison |
| `seasonal` | occupancy + frozen station weekday/weekend 5-minute profile | Format only | deferred source experiment, after daily/weekly-naive benchmark |
| `temporal` | occupancy + region-matched calendar | Not yet | after the backend has a deployment-region calendar provider |
| `context` | occupancy + calendar + weather | No | after real-time, station-local weather and validation are in place |

Never train a deployable model with a profile that cannot be reproduced at API
inference time. The `data_gap_analysis.md` priorities therefore remain the
release gate for temporal/context models.

Before enabling any DL profile, read [`docs/DATA_HANDOFF.md`](docs/DATA_HANDOFF.md) and
review [`config/domain_schema.draft.json`](config/domain_schema.draft.json). The
draft is the explicit handoff surface for later agents: it lists candidate
domains/features, their join keys and why LSTM, Transformer and foundation
fine-tuning are disabled today.

## Commands

Run from the repository root. These commands write artifacts only when told to;
none starts model training by default.

```powershell
# Phase 03 is already available, but can be regenerated from raw source.
.\.venv\Scripts\python.exe ml\src\acquire_urbanev.py
.\.venv\Scripts\python.exe ml\src\validate_urbanev_source.py
.\.venv\Scripts\python.exe ml\src\preprocess_urbanev.py

# Run the one occupancy benchmark harness. It writes no serving model bundle.
.\.venv\Scripts\python.exe ml\src\benchmark_occupancy.py --execute

# Inspect contract/provenance/null/split checks.
.\.venv\Scripts\python.exe ml\src\validate_ml_inputs.py

# Print a training plan only. This does not train.
.\.venv\Scripts\python.exe ml\src\train_occupancy.py

# The legacy trainer remains for artifact-format work; do not promote an UrbanEV
# result to backend serving.
.\.venv\Scripts\python.exe ml\src\train_occupancy.py --prediction-mode residual_to_persistence

# Phase 05A Hybrid LSTM occupancy experiment: plan only until data gates are approved.
.\.venv\Scripts\python.exe ml\src\train_lstm_markov.py

# Transformer and foundation-model review plans; neither trains by default.
.\.venv\Scripts\python.exe ml\src\train_transformer.py
.\.venv\Scripts\python.exe ml\src\train_foundation.py --provider chronos
.\.venv\Scripts\python.exe ml\src\train_residual_duration.py
```

For a local smoke run after approval, add `--max-train-rows 100000`. Do not use
that thinned run as the comparison metric or deploy it.

To create a temporal feature dataset aligned to UrbanEV's Chinese history:

```powershell
.\.venv\Scripts\python.exe ml\src\build_feature_dataset.py `
  --profile temporal `
  --calendar ml\data\derived\calendar\calendar_features_germany.parquet `
  --output ml\data\features\occupancy_features_temporal.parquet
```

The script records `serving_ready=false`; this is deliberate until the API can
provide equivalent calendar features for the deployment region. `context` also
requires the weather artifact and remains blocked by a real-time weather source.

## Layout and experiment records

```text
ml/
  data/processed/urbanev/   # canonical processed source data and split provenance
  data/derived/             # reproducible calendar and weather inputs
  data/features/            # generated supervised feature datasets (local/generated)
  artifacts/                # serving model bundle only; ignored by Git
  results/                  # immutable benchmark/training reports and run manifests
  docs/                     # design, handoff, roadmap and cloud-run documentation
```

The current source-domain benchmark is recorded in
[`results/occupancy/exploratory/`](results/occupancy/exploratory/). Its manifest
must record the Kaggle notebook version, input dataset version and code commit;
missing platform versions are explicitly marked rather than guessed.

## Colab and Kaggle

Use the same scripts, with paths mounted/uploaded in the notebook environment.
The notebook should contain only setup, calls to scripts, artifact download, and
visualization. Keep raw data and generated model files outside Git.

```bash
pip install -r ml/requirements.txt
python ml/src/build_feature_dataset.py --profile baseline
python ml/src/validate_ml_inputs.py
python ml/src/train_occupancy.py --execute --artifact-dir /content/model-release
```

For Kaggle, replace `/content/model-release` with `/kaggle/working/model-release`.
Download the three release files together:

```text
occupancy_model.joblib
occupancy_preprocessor.joblib
occupancy_model_meta.json
```

Place them in `ml/artifacts/` locally (or override the three `MODEL_*_PATH`
variables in `.env`) and restart the backend. It validates the feature contract,
all twelve `+5…+60` horizons, and artifact consistency before enabling model inference.
An invalid/incomplete release cannot affect recommendations; `/model/status` and
the frontend will show the fallback state.

## Retraining policy when real data is ready

1. Ingest raw station observations append-only, with source, station ID,
   observed timestamp, ingestion timestamp and schema validation.
2. Build versioned features from only data available at the prediction time.
3. For UrbanEV, run `benchmark_occupancy.py` as an **exploratory source-domain
   benchmark**. Its test window has informed prior decisions and is not an
   untouched final holdout. Compare persistence, target-time daily/weekly naive
   and gated residual XGBoost per horizon using MAE, median absolute error,
   RMSE and regression calibration. Only a newly held-out data window or a
   pre-defined rolling-origin protocol can support a future strict experiment.
4. Record data version, metrics and limitations in the release metadata.
5. Manually approve/canary the bundle; retain the previous release for rollback.

This prevents accidental online learning, leakage and poisoned observations.

## ML source map

| Module | Responsibility | Phase/status |
|---|---|---|
| `acquire_urbanev.py` | download, fingerprint and manifest immutable raw source | Phase 01 |
| `validate_urbanev_source.py` | verify external archive checksum and ZIP integrity | Phase 01 |
| `preprocess_urbanev.py` | station-level canonical dataset and temporal split | Phase 03 |
| `collect_weather.py`, `generate_calendar.py` | reproducible external/derived features | data-gap preparation |
| `feature_contract.py`, `build_feature_dataset.py`, `validate_ml_inputs.py` | feature profiles, leakage-safe supervised rows and gates | Phase 04 |
| `benchmark_occupancy.py` | exploratory persistence/daily/weekly/gated-residual benchmark | source-domain only; opt-in |
| `train_occupancy.py` | legacy direct/residual XGBoost artifact-format trainer | not eligible for UrbanEV serving |
| `markov_wait.py` | probability transition → wait distribution mathematics | Phase 05B; transition model pending |
| `train_lstm_markov.py` | Hybrid LSTM occupancy regression using the frozen seasonal dataset | Phase 05A; opt-in |
| `train_transformer.py` | generic multi-domain Transformer, driven by reviewed schema | Phase 3; disabled draft |
| `train_foundation.py` | Chronos/TimesFM data/licence/GPU gate and provider handoff | Phase 4; research-only |
| `train_residual_duration.py` | session-duration data gate for future DES residual-duration model | telemetry-gated; disabled draft |

`ml/notebooks/` intentionally contains notebook guidance rather than duplicated
code. Add notebook outputs there only when they call these modules.

For the DES/RDM backend contract, reliability limits, and the final
recommendation output assembled from all model layers, read
[`docs/DES_RDM_INTEGRATION.md`](docs/DES_RDM_INTEGRATION.md).

The immutable UrbanEV source archive lives under `ml/data/external/urbanev/`,
outside backend runtime data. Verify it with
`ml/src/validate_urbanev_source.py`. For the correct source-to-Vietnam transfer
protocol, read [`docs/TRANSFER_LEARNING_URBANEV_TO_VIETNAM.md`](docs/TRANSFER_LEARNING_URBANEV_TO_VIETNAM.md).
The LSTM/Markov boundary and required evaluation are in
[`docs/MARKOV_PHASE_PLAN.md`](docs/MARKOV_PHASE_PLAN.md); the reproducible cloud run is
documented in [`docs/KAGGLE_TRAINING_GUIDE.md`](docs/KAGGLE_TRAINING_GUIDE.md).

## Keys and external services

- The existing historical weather collector uses Open-Meteo's archive endpoint
  and has no key field in this repository. Check the provider's current usage
  policy before scheduling production traffic.
- `GOONG_API_KEY` is only for the current Goong routing/geocoding integration;
  create it in Goong's developer console, restrict it to the APIs/IPs used, and
  place it in root `.env`, never in `VITE_*` or Git.
- Kaggle/Colab credentials are needed only to access private datasets, Drive or
  Kaggle uploads. Keep them in the platform's Secrets manager rather than in a
  notebook or repository.
