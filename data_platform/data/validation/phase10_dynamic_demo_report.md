# Phase 10 dynamic demo validation report

**Result:** `PASS`

**Validation date:** `2026-09-27`

## Deterministic scenario results

| Scenario | Before event | After event / expected result |
|---|---|---|
| Normal | 15 public stations ranked | La Vela rank 1; Audi excluded as private |
| Low SOC | 10 safe stations ranked | 5 stations excluded by `INSUFFICIENT_SOC_RESERVE`; every returned arrival SOC remains above reserve |
| Congestion | La Vela rank 1, wait 0 min | La Vela wait 120 min and rank 15; Huyền Trân Công Chúa becomes rank 1 |
| Port outage | La Vela rank 1 | La Vela excluded as offline; Nguyễn Cư Trinh becomes rank 1 |
| Routing provider failure | Fixed scenarios use cache | Direct route plus one route for each of 15 public stations are available offline |

## Verification

- PASS — backend suite: `51 passed`.
- PASS — frontend suite: `8 passed` across 5 files.
- PASS — Ruff backend check and frontend ESLint.
- PASS — TypeScript check and Vite production build.
- PASS — static data validation: 16 stations, 3 vehicles, 0 errors.
- PASS — Phase 01 validation: 0 errors; one expected warning for optional
  `station_history.csv`.
- PASS — fixed-scenario cache coverage: 16 cache files, including a direct route and one
  waypoint route for every public station.
- PASS — browser dry-run of normal, low-SOC, congestion and outage scenarios.
- PASS — browser console contained no warnings or errors during the dry-run.
- PASS — `POST /demo/reset` and the UI reset action restore runtime event state.

## Scope decision

Phase 03–04 occupancy preprocessing/training remain intentionally deferred. Forecasts use the
explicit `persistence` source and the UI displays that limitation. This Phase 10 result is a demo
gate, not an ML release gate.

## Non-blocking limitation

The production bundle is approximately 1.15 MB before gzip and Vite reports a chunk-size
warning. This does not block the local hackathon demo.
