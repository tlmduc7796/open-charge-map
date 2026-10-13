# M2B technical recommendation engine

`TechnicalOpportunityEngine` implements the framework-free `PlanningEngine` port in
`domain.py`. The M3 application service supplies a resolved `PlanningRunConfig` and one immutable
M1 snapshot, then validates the returned mapping against the shared HTTP response model.

## Dataset mapping expected from M1

```python
{
    "snapshot": {
        "city_id": "hcmc",
        "boundary_version": "...",
        "pilot_extent_id": "...",
        "data_snapshot_id": "...",
        "boundary_crs": "EPSG:4326",
        "boundary_geometry": {"type": "Polygon", "coordinates": [...]},
        "boundary_source_id": "...",
    },
    "candidates": [
        {
            "candidate_id": "...", "lat": 10.7, "lon": 106.7,
            "covered_demand_cell_ids": ["cell-a"],
            "coverage_source_ids": ["..."],
            "coverage_status": "observed",
            "constraints": [
                {"id": "site_access", "status": "pass", "source_id": "...",
                 "evidence_status": "observed"}
            ],
            "grid_capacity_kw": {"value": 120, "unit": "kW", "status": "observed",
                                 "source_id": "..."},
            "network_features": {
                "road_accessibility": {"value": 80, "unit": "score_0_100",
                                       "status": "proxy", "source_id": "..."}
            },
            "provenance": [{"field": "candidate", "source_id": "...",
                            "status": "observed", "is_synthetic": False}],
        }
    ],
    "demand_estimates": [
        # M2A shared payload: candidate_id OR demand_cell_id, target/value/unit,
        # time_window, status, source_id, model_version, data_snapshot_id, scenario,
        # optional uncertainty.
    ],
    "existing_covered_demand_cell_ids": ["cell-b"],
    "existing_coverage_source_ids": ["..."],
    "existing_coverage_status": "observed",
}
```

The selected snapshot must exactly match the requested city, boundary, pilot extent, and snapshot
IDs. Boundary coordinates must be valid WGS84 GeoJSON Polygon/MultiPolygon with a source ID. A
missing or mismatched boundary is `invalid_input`; an outside candidate is excluded only after the
pinned geometry confirms it. Other hard constraints are excluded only for
`status="fail"`, `confirmed_infeasible=True`, and at least one source ID. An unconfirmed fail is
reported as conditional. Candidate type and site rights/site-host status are explicit hard gates;
M1 must provide their pass/fail/conditional/unknown status with source evidence.

Candidate-level demand records are accepted directly. Demand-cell records are aggregated only
when a candidate has explicit catchment cell IDs and every included cell has a compatible, known
record. Values from different target/unit/scenario/time-window contexts cannot be combined. Missing
cells remain unknown and do not contribute a zero-valued label.

## Formula and ranking behavior

The versioned default profile is `technical-demo-v1`, with the configurable team demo weights
30/25/20/15/10 for demand, marginal coverage, grid/site readiness, segment fit, and network gap.
These are screening defaults, not partner policy or finance assumptions.

- Demand potential is min-max normalized within the requested candidate set. Equal known values
  receive 50 points because this component cannot distinguish those candidates.
- Marginal coverage is newly reachable demand-cell demand divided by total known study-area demand,
  after existing covered cells are removed.
- Competition is the share of candidate catchment demand already covered by existing sites;
  network-gap fit is its complement. Absolute coverage gain, residual coverage gap, competition,
  and network fit are returned as separate metrics.
- Grid/site readiness averages source-backed passing gates and reported grid-capacity fit. Unknown
  gates are omitted from the component score and reduce its evidence coverage.
- Segment fit is a weighted mean of available 0-100 road-accessibility, POI/dwell, fleet, and
  charger-mix evidence. Its weights are part of the versioned scoring config.
- Weighted component contributions are normalized over known components. Ranking is limited to a
  highest-coverage group with the same known components and evidence fractions; incomparable
  candidates go to `unranked_candidates` instead of gaining rank from absent evidence.

The requested charger configuration is emitted as scenario capacity. Capacity fit is a direct
comparison with source-backed reported grid capacity; the `overload_risk` category is deterministic
and is neither a probability nor utility approval. Cost/ROI is not computed without a qualified
finance package. This v0.1 engine ranks individual candidates and does not select a multi-site
portfolio.

## Sensitivity reruns

Call `TechnicalOpportunityEngine.compare_sensitivity(config, dataset, cases)` to rerun the same
candidate set with alternate demand/candidate snapshots, run configuration, or a versioned
`TechnicalScoringConfig`. Each `SensitivityCase` has a unique `case_id`; the result includes each
recommendation order and candidate score/rank movement. `rank_movement` is baseline rank minus case
rank, so a positive value means the candidate improved. Unranked or excluded candidates have no
rank or score delta. These deterministic comparisons are not probabilities and do not alter the
single-run shared HTTP response contract.

## Call from the application service

```python
engine = TechnicalOpportunityEngine()
assert engine.algorithm_version == "m2b-technical-screen-0.1.0"
assert engine.config_version == "technical-demo-v1"
result = engine.recommend(run_config, versioned_m1_snapshot)
```

The engine itself imports only standard-library modules and the framework-free planning port. The
API/router, database adapters, and frontend stay outside the M2B domain module.
