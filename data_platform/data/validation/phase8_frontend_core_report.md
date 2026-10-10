# Phase 08 frontend core validation report

**Result:** `DEMO PASS / RELEASE BLOCKED BY PHASE 03–04`

**Branch:** `demo/backend-first`
**Validation date:** `2026-09-26`

## Completed

- Responsive journey dashboard backed by the real Phase 07 API contract.
- Goong Maps primary renderer with automatic Leaflet + OpenStreetMap fallback.
- Backend station markers with available, busy/queue, event-affected and offline states.
- Demo scenario, vehicle, initial SOC, target SOC and event controls.
- Ranked recommendation cards with detour, wait, charging time, arrival SOC and score.
- Expandable excluded-station list with access, offline, compatibility, SOC and route reasons.
- Route geometry display and marker/recommendation station selection.
- Station details for address, access, notes, connectors, ports, queue, occupancy and time estimates.
- Demo indicators for backend, map provider, forecast source and active events.
- Loading, error, pre-submit and empty-result states without frontend business calculations.

## Verification

- PASS — backend test suite: `44 passed`.
- PASS — frontend unit/component suite: `7 passed` across 4 test files, including the
  missing-Goong-key Leaflet/OSM fallback branch.
- PASS — `ruff check backend`.
- PASS — `pnpm --dir frontend lint`.
- PASS — TypeScript check and Vite production build.
- PASS — browser smoke test against live FastAPI and Vite servers.
- PASS — Goong base map, 3 station markers and route geometry rendered with the local Maptiles key.
- PASS — normal journey returned 2 ranked stations and selected Lavida with its detail panel.
- PASS — Lavida outage scenario reranked Deutsches Haus first and exposed both exclusion reasons.
- PASS — Audi marker exposed `private` access and the internal-use note; no cost field was shown.
- PASS — browser console contained no error. Goong emitted one non-blocking missing style sprite warning.

## Remaining limitations

1. **Arbitrary origin/destination:** inputs intentionally remain fixed to backend demo scenarios.
   Free-form location search, geocoding and uncached journey orchestration belong to Phase 09.
2. **Full end-to-end automation:** Phase 08 has mocked frontend contract tests and a manual live
   browser smoke test. Cross-process system tests are Phase 09–10 scope.
3. **Occupancy model:** the UI truthfully shows `persistence`; the trained Phase 04 artifact is
   still unavailable on this backend-first branch.
4. **Runtime persistence:** events and planned arrivals remain in backend memory as documented
   in Phase 07.
5. **Bundle size:** the map SDK produces a roughly 1.15 MB minified JavaScript bundle
   (about 317 kB gzip). It is acceptable for the demo but should be code-split before release.

The Phase 08 frontend gate passes for the backend-first demo. Release status remains blocked
until Phase 03–04 are completed and the real occupancy model is integrated.
