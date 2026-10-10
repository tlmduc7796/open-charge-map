# Occupancy model handoff to the backend

This document describes the artifact contract currently loaded by the API. It does not approve an experiment for production; model quality and deployment scope have separate release gates in [release_readiness_ml_data.md](release_readiness_ml_data.md).

## Current serving contract

The authoritative implementation is `backend/app/domain/model_artifacts.py` plus `backend/app/domain/model_contract.py`. Contract version `2.2` serves six direct horizons: 5, 10, 15, 20, 25 and 30 minutes. Input history is twelve five-minute occupancy ratios in chronological order, oldest first.

A release bundle contains:

| File | Required contents |
| --- | --- |
| `occupancy_model.joblib` | A dictionary with `format_version`, `prediction_mode`, `feature_names_by_horizon`, and `models`. The model map uses integer horizon keys and each estimator implements `predict(rows)`. |
| `occupancy_preprocessor.joblib` | A dictionary with the same `format_version`, `prediction_mode`, and `feature_names_by_horizon`; seasonal models also include the frozen `seasonal_profile`. |
| `occupancy_model_meta.json` | Matching contract version and per-horizon features, all six horizons, target `occupancy_ratio`, profile, metrics, a stable non-empty `model_version` (or legacy `release_id`), training provenance (`training_data_sha256s`, `training_data_max_timestamp`), a post-training `model_frozen_at`, the SHA-256 `evaluation_report_sha256`, and `serving_ready: true` only after the release gates pass. The serving loader canonicalizes `release_id` to `model_version`; the independent evaluator checks training provenance and freeze time. |
| `occupancy_evaluation_report.json` | The independent evaluator's passing HCMC holdout report. Its SHA-256 is pinned in metadata, and it binds the model/preprocessor artifact hashes to the evaluated candidate. |

The baseline feature list is exactly `lag_1` through `lag_12`; the adapter builds those values from the twelve-step history. The optional seasonal profile adds only the horizon-specific `seasonal_prior_t_plus_{horizon}m` feature. Calendar, weather, queue, wait, station ID, price, POI and other features are not part of the active serving contract.

## Reproduce the UrbanEV source dataset

The checked-in source manifest records the expected raw archive SHA-256. Install the small preprocessing environment and run:

```powershell
python -m pip install -r ml/requirements-preprocess.txt
python scripts/preprocess_urbanev.py --stations-count 50
```

The command verifies the archive checksum, processes the deterministic 50-station stratified sample, rejects missing occupancy values and gaps in the five-minute cadence, and writes a Parquet dataset plus split/provenance metadata under `data/ml/urbanev/processed/`. It does not fill gaps or create model weights. The timestamps are preserved as supplied because the source does not specify a timezone. The data is from Shenzhen and is not operational HCMC truth or approval to serve a model.

Use `--skip-source-check` only for isolated synthetic test archives. Production model training should consume the generated dataset with a separately reviewed temporal holdout and the six horizons in contract 2.2.

## Run the six-horizon exploratory benchmark

The benchmark uses the backend's supported horizons and exact twelve lag feature names. It trains direct residual XGBoost candidates, chooses its residual gate using validation only, and reports persistence, daily-naive, weekly-naive and candidate metrics. Preview the command first, then execute it explicitly:

```powershell
python -m pip install -r ml/requirements-benchmark.txt
python scripts/benchmark_urbanev.py
python scripts/benchmark_urbanev.py --execute --max-train-rows 200000
```

The report is marked `deployment_eligible: false`; its test window is already inspected and is not an independent release holdout. It also records the Phase 04 requirement of at least 5% test MAE improvement over persistence at every serving horizon. This command never exports or promotes model artifacts. Do not set backend model artifact paths from this experiment.

## Generate and validate an example

The generator writes an importable example bundle to a scratch directory. It is explicitly untrained and marked `serving_ready: false`, so the strict release validator is expected to reject it:

```powershell
python scripts/make_example_model_artifacts.py --out build/example_artifacts
python scripts/validate_model_artifacts.py --dir build/example_artifacts
```

The validator uses the same `JoblibOccupancyPredictor.from_files` loader as the API, then runs one smoke prediction for every supported horizon. `PASS` means the backend accepts the bundle and inference completes; it says nothing about forecast accuracy, calibration, or suitability for a customer-facing release.

After a reviewed model bundle is exported, run:

```powershell
python scripts/validate_model_artifacts.py --dir ml/artifacts
```

Joblib files can execute code during deserialization. Validate only artifacts received from a trusted training pipeline and distribute binary weights through the approved release artifact store; `.joblib` files are ignored by Git.

## Promotion requirements

Before setting `serving_ready` to true, the ML release must:

- evaluate persistence and candidate models on the same frozen, untouched temporal holdout;
- use `scripts/evaluate_occupancy_release.py` against a separate all-observed holdout and report MAE, RMSE, calibration, and sample coverage per supported horizon;
- demonstrate the Phase 04 promotion threshold and supply approved sample-size and calibration policies;
- preserve exact feature order, contract version, Python/runtime dependencies and reproducible training metadata;
- load and smoke-test the exported files in a fresh process using the backend validator;
- state the source-domain and transfer limitations. UrbanEV is Shenzhen data and is not HCMC operational ground truth.

At the current release review, the active backend has no approved artifact and therefore uses persistence fallback. A format-valid bundle is not sufficient to enable model serving. See [release_readiness_ml_data.md](release_readiness_ml_data.md) for current data and evaluation gates.

The serving loader fails closed if a `serving_ready: true` bundle lacks `occupancy_evaluation_report.json`, if its hash differs from `evaluation_report_sha256`, if the report did not pass the HCMC release gates, or if either evaluated model artifact hash differs. The evaluator accepts an unapproved candidate for scoring but never changes its metadata. After independent review of a passing report, place that exact report beside the three artifacts, record its SHA-256 in the metadata, then set `serving_ready: true` and run `scripts/validate_model_artifacts.py`. The report hash detects accidental replacement; protect the release directory and review provenance as part of artifact-store access controls.
