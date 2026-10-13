# M2A candidate and cell demand pipeline

This package is separate from the existing five-minute station-occupancy predictor in `ml/`.
It trains a demand model for one spatial unit and one target at a time, then emits records in the
M2A → M2B payload shape from `docs/station-planning/modules/SHARED_CONTRACT_VI.md`.

## Training table

Each CSV/Parquet row represents one candidate or demand cell and a complete target time window.
Required label and lineage columns are `spatial_unit_id`, `spatial_group`, `time_window_start`,
`time_window_end`, `target`, `value`, `unit`, `status`, `source_id`, `data_snapshot_id`, and
`is_synthetic`. `target`/`unit` pairs supported here are `charging_sessions` / `sessions_per_day`
and `charging_energy` / `kwh_per_day`.

The numeric feature schema follows the pipeline design: POI mix, population/buildings, road
accessibility/traffic, fleet activity, home charging, nearby compatible supply, uptime, charger
power, and cyclic day/month features derived from the target window. Provenance and labels are
never passed to the model. Proxy/scenario/unknown values cannot be training labels; they may be
feature inputs only when represented as missing or separately encoded by a future adapter.

## Run a synthetic demonstration

From the repository root:

```powershell
python -m pip install -r ml/requirements.txt
python -m ml.station_demand.train --synthetic-demo --target charging_sessions --output-dir ml/artifacts/station_demand/demo
```

The generator is deterministic with a fixed seed. The resulting model card has
`is_synthetic: true` and `serving_ready: false`. Its metrics only show recovery of the generator;
they are not evidence of HCMC demand accuracy. Synthetic targets are accepted only through the
explicit `--synthetic-demo` path or an explicit `allow_synthetic=True` call.

For M1-provided labels, pass `--input <training-table.csv-or-parquet>`. The trainer rejects proxy,
scenario, unknown, and not-applicable labels, checks target units and provenance, splits full time
windows temporally, and reserves entire spatial groups for a second holdout. Early stopping uses
validation only. The report compares XGBoost with a spatial-group historical-mean baseline on both
temporal and spatial holdouts.

`ml.station_demand.inference.predict_demand_payload()` emits `candidate_id` or `demand_cell_id`,
target/value/unit, time window, evidence status, model version, prediction snapshot, scenario, and
source ID. It does not emit an uncertainty interval until the model has a validated calibration
method. Predictions from an observed-data model are labeled `proxy`; predictions from synthetic
training remain `synthetic`.
