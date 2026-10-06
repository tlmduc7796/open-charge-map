# Gold synthetic dataset

`ml/data/gold/` contains generated, Git-ignored artifacts.  Parquet is the
authoritative format because it preserves UTC timestamps, numeric types and
schema metadata.  It is a topology-conditioned simulation dataset for offline
model development and evaluation, never observed Vietnamese charging data.

The generator reads a CTGAN behavior prior trained on privacy-minimized ACN
sessions and `data/static/stations.geojson`.  It includes only stations whose
technical topology is marked `provider_reported`; candidates whose connector
details are synthetic or unknown are excluded by default.

| File | Purpose |
| --- | --- |
| `stations.parquet` | Target station inventory and topology confidence. |
| `ports.parquet` | Individual generated ports and their maximum power. |
| `sessions.parquet` | Canonical session lifecycle. Use for RDM labels. |
| `telemetry_5min.parquet` | Piecewise-constant synthetic charging telemetry. Use for RDM features and replay tests. |
| `occupancy_5min.parquet` | Station occupancy replay. Use for XGBoost/LSTM occupancy experiments. |

Every generated table declares `is_synthetic=true`; its manifest records the
CTGAN artifact, station catalog, source hashes, seed and constraint policy.
The split is chronological: 60% train, 20% validation, 20% test.

To reproduce a three-month scenario after training CTGAN:

```powershell
.\.venv\Scripts\python.exe ml\src\build_gold_synthetic.py `
  --model ml\artifacts\ctgan\acn_caltech_behavior_2018_2021.pkl `
  --stations data\static\stations.geojson `
  --output-dir ml\data\gold\hcmc_ctgan_q1_2026 `
  --start 2026-01-01 --end 2026-04-01 --sessions-per-port-day 1.5
```

The `sessions_per_port_day` setting is a scenario assumption, not learned from
ACN and not a claim about Vietnam demand.  Do not change it without recording
the scenario and regenerating the manifest.
