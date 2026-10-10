# ML/data release readiness

**Review date:** 2026-10-09
**Scope:** `origin/codex/open-charge-map-main`, `origin/codex/ai-foundation`, and the active `full-stack-main` workspace.
**Decision:** UrbanEV is usable for reproducible source-domain experiments. The ML branch does not provide a deployable occupancy release bundle.

## What is available

- `open-charge-map-main` contains the station catalog, route cache, demo/runtime fixtures, PostgreSQL/PostGIS platform, and a source manifest for UrbanEV. The active workspace has these data-platform changes staged as local edits and the UrbanEV archive is present at `data/ml/urbanev/raw/UrbanEVDataset.zip`.
- The archive matches the manifest: 647,305,188 bytes, 3,138 ZIP members, SHA-256 `9d3f0aec34434546d082509efcdeeaea116eaa841701cc5854a9b62a27881a79`.
- `ai-foundation` contains a committed processed sample/full Parquet dataset for 50 Shenzhen stations across 2022-09-01 to 2023-02-28, plus temporal split metadata and exploratory benchmark results. The active workspace now has a checksum-verified preprocessing command at `scripts/preprocess_urbanev.py`; it rejects missing values and temporal gaps and regenerates the same 50-station split statistics from the raw archive.
- Its original benchmark compares persistence, daily/weekly naive baselines, and gated residual XGBoost over 12 horizons (+5…+60 minutes). The active workspace now also has a six-horizon benchmark entrypoint tied to backend contract 2.2; any run on the existing data remains exploratory because the test window has already been inspected.
- The active six-horizon run (`data/ml/urbanev/processed/exploratory_benchmark_contract_2_2.json`) used seed 42, 200,000 sampled training rows per horizon, XGBoost 2.1.4 and one CPU worker. The residual model improved validation MAE at all six horizons but improved the previously inspected test MAE by at least the required 5% at **zero** horizons. It is explicitly `NO_GO_HISTORICAL_TEST_MAE_THRESHOLD`, not a release evaluation.

## Release blockers

1. No occupancy model/preprocessor weights are committed in `ai-foundation`; `ml/artifacts/occupancy` contains only `.gitkeep`. The current backend also has no validated model bundle in `ml/artifacts/`, so serving remains on persistence.
2. The exploratory benchmark is not an independent release evaluation. It cannot satisfy the release gate or justify enabling model predictions.
3. UrbanEV observations are from Shenzhen. No approved HCMC operational occupancy history or validated transfer result is present. Shenzhen model performance alone does not establish local calibration or forecast quality.
4. The AI branch uses a different data layout and its advanced model profiles remain explicitly disabled pending approved feature sources and validation. Do not merge that branch wholesale into the active backend.
5. The backend serving contract is aligned to six MVP horizons (+5 through +30 minutes, contract 2.2). The ai-foundation benchmark still covers twelve horizons, so any candidate bundle must be retrained/exported for the six serving horizons and pass the independent release gate.

## Safe next steps

1. Keep persistence as the production fallback and label it as such in API/UI.
2. The six-horizon exploratory benchmark is now adapted to the active serving contract. Its candidate did not satisfy the Phase 04 test improvement threshold; keep persistence serving and do not export this candidate. Preprocessing is reproducible from this repository's raw archive path and retains source provenance.
3. Collect a new, untouched temporal holdout (and HCMC operational data) before any further promotion decision; model selection must remain validation-only.
4. Before release, collect HCMC observed telemetry and evaluate transfer/local calibration, or explicitly scope the first release as a source-domain experiment unavailable for customer-facing forecasts.
5. Export an artifact only after the serving contract, exact feature order, dependency versions, and backend loader agree; run the backend artifact validator and an inference smoke check.

### Independent holdout evaluation

`scripts/evaluate_occupancy_release.py` evaluates a frozen serving bundle with the backend's actual `JoblibOccupancyPredictor`. The separate Parquet input must contain `timestamp`, `entity_id`, `occupancy_ratio`, and `data_origin`; every row must be `observed`, in a contiguous five-minute series, with enough context for the 12-step lookback and the +30-minute target. It must not be the existing UrbanEV file with a renamed split. The evaluator computes MAE/RMSE against persistence at all six serving horizons and requires at least 5% relative MAE gain at every horizon. It also reports ECE, calibration slope/intercept, and requires an approved calibration policy in the manifest to pass the calibration gate.

Backend serving now verifies `occupancy_evaluation_report.json` whenever model metadata says `serving_ready: true`. The metadata pins the report SHA-256; the report must pass all six MAE, calibration, and sample-coverage gates for HCMC and must contain hashes matching the loaded model and preprocessor artifacts. An unapproved or altered bundle fails closed to persistence.

The JSON manifest must include `holdout_id`, `holdout_status: independent_untouched`, `model_selection_used: false`, `source_record`, `data_domain`, `timezone`, `evaluation_start`, `evaluation_end`, an approved `sample_policy` with minimum station/sample counts, and an approved `calibration_policy` with ECE, slope, and intercept bounds; both policies require a reviewer and reference. The frozen model metadata must include `model_frozen_at`, `training_data_max_timestamp` before `evaluation_start`, and SHA-256 `training_data_sha256s`. Missing or conflicting provenance appears in `evidence_gaps`; a source-domain holdout cannot qualify for customer deployment. A passing report is evaluation evidence only: the command never promotes an artifact, and the holdout manifest's independence assertion still needs operator review.

```powershell
python scripts/evaluate_occupancy_release.py `
  --dataset C:\SecureInput\hcmc-holdout.parquet `
  --manifest C:\SecureInput\hcmc-holdout-manifest.json `
  --artifact-dir ml\candidate\occupancy `
  --report build\evaluation\hcmc-candidate.json
```

The current repository has no qualifying holdout or deployable artifact, so this command is ready for use when those inputs are supplied; it does not change the current persistence serving decision.

## Release status

| Gate | Status |
|---|---|
| UrbanEV source provenance and checksum | PASS |
| Reproducible preprocessing pipeline | PASS; active workspace reproduced 2,606,400 rows and the branch's 50-station split statistics from the checksum-verified raw archive |
| Final untouched-holdout model evaluation | NOT MET |
| Deployable model/preprocessor bundle | NOT MET |
| HCMC operational data/transfer validation | NOT MET |
| Active backend model artifact validation | NOT MET; persistence fallback remains active |

No result in this review changes `DEMO_MODE`, model-serving configuration, or release readiness.

## Additional release runtime gate

Release-mode `/health/ready` checks that PostgreSQL contains at least one active, non-synthetic station and one eligible, non-synthetic vehicle, plus at least one fresh station snapshot with a known operational port. Fresh snapshots whose ports are all unknown do not pass readiness. An empty or demo-only catalog returns HTTP 503 with counts in `checks.catalog`; liveness remains independent. This prevents Compose from reporting the API healthy before operational catalog data and usable station status are loaded. It is only a minimum completeness check: it does not verify geographic coverage, connector quality, cross-station status quality, or telemetry-provider continuity.
