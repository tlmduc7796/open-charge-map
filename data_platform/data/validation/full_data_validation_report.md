# Full data validation report — Phase 01

**Result:** `PASS`

- Errors: 0
- Warnings: 1
- Checks passed: 7

## Checks

- PASS — Runtime capacity invariants checked for 16 stations
- PASS — Validated 16 routing API cache files
- PASS — Referential and temporal checks completed for 4 planned-arrival records
- PASS — All 4 required event types are present and capacity-safe
- PASS — Validated 4 deterministic demo scenarios
- PASS — Validated one baseline arrival rate for each of 16 stations
- PASS — UrbanEV archive verified: 647305188 bytes, SHA-256 matched

## Errors

- None

## Warnings

- WARNING — Optional station_history.csv omitted; UrbanEV-normalized replay will be decided in Phase 03

## Scope note

`station_history.csv` is optional and is intentionally not generated in Phase 01. If Phase 03 confirms a suitable UrbanEV 5-minute station-level series, the demo replay may be derived from that processed source; it is never an ML training input.
