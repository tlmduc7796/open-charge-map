# Phase 07 backend demo validation report

**Result:** `DEMO PASS / RELEASE BLOCKED BY PHASE 04–06`

**Branch:** `demo/backend-first`
**Validation date:** `2026-09-25`

## Completed

- Cache-first routing service with Goong primary live provider and OSRM fallback.
- Normalized route geometry, distance in meters and duration in seconds.
- Public/access, operational, compatibility and reserve-SOC candidate filtering.
- Fixed-threshold explainable scoring for detour, wait, charging time and SOC risk.
- No price or cost input/output in recommendation logic.
- In-memory planned-arrival register/cancel/arrive/expire/reset lifecycle.
- Resettable event engine for congestion, queue spike, port outage and recovery.
- Station, vehicle, route, recommendation, status, event, planned-arrival and model APIs.
- Model status reports persistence truthfully while Phase 04 artifacts are absent.

## Verification

- PASS — `44 passed` with `python -m pytest`.
- PASS — `ruff check backend`.
- PASS — live Goong Directions smoke test returned a normalized Goong route:
  14,523 m, 2,654 s and 287 LineString coordinates.
- PASS — all three existing OSRM cache files load through backend route schemas.
- PASS — private Audi station is excluded by `NON_PUBLIC_ACCESS`.
- PASS — GB/T vehicle filters both public stations by `NO_COMPATIBLE_CONNECTOR`.
- PASS — SOC at reserve filters positive-distance candidates by
  `INSUFFICIENT_SOC_RESERVE`.
- PASS — normal scenario ranks Lavida first and returns all explainable components.
- PASS — applying Lavida outage removes it and reranks Deutsches Haus first.
- PASS — two scenarios complete through `/journey/recommend` integration tests.
- PASS — static station status remains unchanged after runtime event application.

## Demo fallbacks and limitations

1. **Occupancy model:** recommendation uses `prediction_source=persistence` because the
   Phase 04 artifacts do not exist. `/model/status` exposes this limitation.
2. **Deterministic scenario routing:** candidates use the Phase 01 OSRM route caches even
   when Goong is available. Dynamic uncached route requests use Goong first.
3. **Cached route legs:** the original cache stores only aggregate distance/duration.
   Distance and ETA to the station waypoint are approximated from geometry position.
4. **Runtime persistence:** event and newly registered arrival state are in-memory only.
5. **Event scheduling:** demo explicitly applies/reset events; start/end timestamps are not
   driven by a background scheduler.

Items 3–5 are acceptable demo fallbacks but should be replaced for production. The Phase 07
business-flow gates pass; the repository cannot be release-ready until Phase 03–04 complete
and Phase 06 loads the selected occupancy artifact.
