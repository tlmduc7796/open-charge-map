# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Smart EV Journey: an MVP that ranks EV charging stations for a journey by total time (travel + wait + charge), using predicted occupancy at arrival time. Scope is Ho Chi Minh City (16 master stations in the bootstrap snapshot; the 86 synthetic `CAND_*` demo stations were removed). Project docs, plans and most comments are in Vietnamese. The original plan is `docs/Rule-Based-AI-Ke-hoach-trien-khai.md` (sections A–F); `docs/BACKEND_KE_HOACH_HOAN_THIEN.md` is the living milestone tracker (M0–M6) and `docs/PHASE_INDEX.md` the phase/exit-gate index.

## Commands

Windows-first (PowerShell / `.bat`). Requires Python 3.12, Node 20.19+/22.12+, pnpm 11.19, Docker Desktop.

```powershell
setup.bat            # one-time: venvs, pnpm install, Postgres container, DB bootstrap (idempotent)
start.bat            # Postgres + backend (:8000) + frontend (:5173)

# backend (repo root, .venv active)
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
pytest                                              # testpaths = backend/tests, tests
pytest backend/tests/test_wait_estimation.py        # one file; add -k <name> for one test
ruff check backend                                  # line-length 100, rules E,F,I,UP

# frontend
pnpm --dir frontend dev --host 127.0.0.1
pnpm --dir frontend lint | test | build             # build = tsc --noEmit + vite build
pnpm --dir frontend exec vitest run src/App.test.tsx

# data / database — run from data_platform/ with ITS OWN venv (data_platform/.venv, `pip install -e .`);
# the root .venv has no alembic (data_platform/README.md's `..\.venv` upgrade snippet is wrong)
cd data_platform
.\.venv\Scripts\python.exe scripts\bootstrap_database.py                  # compose up + migrate + load snapshot; refuses a non-empty DB
.\.venv\Scripts\python.exe -m alembic upgrade head                        # existing DB; then scripts\seed_runtime_data.py, seed_synthetic_port_statuses.py
cd ..; python scripts\validate_static_data.py; python scripts\validate_phase1_data.py; python scripts\check_data_paths.py
```

- DB-backed backend tests are skipped unless `BACKEND_TEST_DATABASE_URL` points at a **separate, migrated and seeded** database (they write port state; never point it at the demo DB). `backend/tests/conftest.py` forces `CATALOG_STORAGE=memory` and `PLANNED_ARRIVALS_STORAGE=memory` otherwise.
- `data_platform/tests` import `data_platform`, which is only installed in `data_platform/.venv`; root `pytest` does not collect them.
- Postgres/PostGIS runs from `data_platform/compose.yaml` on host port **5433** (`smart_ev` / `smart_ev_data`). That compose file is the only Docker service — backend and frontend are not containerised.

## Configuration gotchas

- Backend reads the repo-root `.env` (see `.env.example`); Vite does **not** — frontend keys live in `frontend/.env.local`.
- Two different Goong keys: `GOONG_API_KEY` (REST, backend-only, Places/Directions) and `VITE_GOONG_MAPTILES_KEY` (browser, domain-restricted). Never reuse one for the other. Without the maptiles key the frontend falls back to Leaflet + OSM; without the REST key routing uses cached routes / OSRM.
- Use `127.0.0.1` consistently; CORS origin defaults to `http://127.0.0.1:5173`.
- Backend **fails fast at import time** (`main.py` builds everything at module level) if Postgres is unreachable or Alembic revision ≠ `0006_trip_tokens` (`backend/app/database.py`). Adding a migration means bumping `REQUIRED_DATABASE_REVISION`.
- `INTERNAL_API_KEY` empty ⇒ `/api/v1/internal/*` returns 503.

## Architecture

```
frontend/ (React 19 + Vite, Goong JS / Leaflet)  ──HTTP──►  backend/app (FastAPI)
                                                              │  domain/ (pure logic)  +  *_repository.py (SQLAlchemy)
data_platform/ (Alembic migrations, seeds, fixtures) ──────►  PostgreSQL 16 + PostGIS
```

**Two API surfaces coexist in `backend/app`:**
- `api.py` — legacy scenario/demo API (`/journey/recommend`, `/route`, `/demo/*`, `/planned-arrivals/*`, `/model/status`, `/geocoding/*`, `/vehicles`). **The current frontend uses only this one.** Recommendations are a fixed-threshold weighted sum (`domain/recommendation.py`), tied to `DemoScenario`s and cached routes.
- `api_v1.py` + `api_v1_models.py` — the contract from the plan (`/api/v1`: config, stations/bbox, availability offsets 0–30, ports, `search/stations`, `search/route`, `trips` + GPS position + PATCH, `internal/port-status`). Ranks by `totalMin` (`domain/search.py`), camelCase JSON, `{lat,lng}`, battery in percent, unified error envelope + `X-Request-ID` (`api_errors.py`).
- Unit convention boundary: **domain/DB use `{lat, lon}` and SOC in `[0,1]`; `/api/v1` uses `{lat, lng}` and percent.** Convert only at the API edge.

**Wiring:** `backend/app/main.py` constructs every service into `app.state` (no DI framework). `CATALOG_STORAGE` / `PLANNED_ARRIVALS_STORAGE` = `database` (default) or `memory`; the memory path reads JSON fixtures through `domain/repositories.py::load_domain_data`. Even in database mode, demo events, scenarios, queue assumptions and route cache still come from `DATA_DIR` JSON, and `RuntimeStateStore` overlays demo events in process memory on top of DB station status.

**Prediction chain (`domain/`):**
1. `ml_gateway.MlGateway` — the single boundary for backend → ML calls (occupancy B1, wait distribution B2, anti-herding B3). `main.py` injects `DefaultMlGateway`, which returns **fixed defaults labelled `source="default"`**: occupancy ratio `0.5` for every online station/horizon, wait distribution as a point mass on the Erlang C estimate, herding correction as a no-op. Replace it with a real adapter implementing `MlGateway`; don't scatter ML calls elsewhere.
2. `forecasting.OccupancyForecastService` — with a gateway and no predictor, forecasts have `prediction_source="default"` (flag `ML_DEFAULT_VALUE`), so future occupancy ignores live station state; only offset 0 reflects real telemetry. Without a gateway it falls back to `persistence`. An optional `predictor` (real model, `prediction_source="model"`) is never supplied yet; `model_artifact.py` defines its metadata contract (12×5 min lookback, must beat persistence MAE by ≥5% per horizon). `/model/status` reports `default` + flag `ML_DEFAULT_VALUES_ACTIVE`. The DB `prediction_source` enum is still `persistence|model` — a writer of `predictions` would need a migration for `default`.
3. `wait_estimation.WaitEstimator` — Erlang C (M/M/c) plus current-queue state and planned arrivals; capped by `WAIT_SCORING_CAP_MIN`. Ranking still uses this scalar; the gateway's `waitDistribution` is attached to search options but not used for ranking. It is not the Markov/quantile model from the plan; do not label its output as such.
4. `routing.RoutingService` — Goong → OSRM → cached route fallback. `search.py` / `recommendation.py` filter candidates (PostGIS corridor, access, connector, reserve SOC, confirmed opening hours), route, forecast, estimate wait/charge, rank.

**Trips (`domain/trip_service.py`, `trip_repository.py`):** persisted in Postgres; `POST /trips` needs a `searchId` (held in process memory 10 min by `search_store.py`, as is the per-IP search rate limiter — not shared across workers). Creation returns a `tripToken` once; only its SHA-256 is stored and every later call needs `Authorization: Bearer`. Re-plan uses thresholds from `app_config` with cooldown and a per-trip declined-station list.

**Synthetic data is labelled, not hidden:** station/recommendation responses carry `syntheticFields`; status rows keep `data_source` (`observed`/`inferred`/`synthetic`). Keep that provenance when changing seeds or responses. The 60 s stale-status job in `main.py` marks only *observed* telemetry `unknown`; synthetic rows are left alone.

**Database:** schema is defined twice — SQLAlchemy models in `data_platform/src/data_platform/database/models.py` and Alembic migrations `0001`–`0006`; keep them in sync (ERD: `docs/DATABASE_ERD.md`). `port_status_history` and `station_occupancy_5m` are range-partitioned by month. Predictions are per station/horizon (not per connector type as in the plan).

**Adding a station:** promote the candidate into `data_platform/data/static/stations.geojson`, regenerate runtime/queue assumptions, add its routes to `config/demo_routes.json`, rerun `scripts/cache_demo_routes.py`; the static and phase‑1 validators fail if fixed scenarios lose route coverage.

## Plan vs. implementation (state at 2026-10-10, branch `fix/ui`)

Implemented: C-database core (PostGIS, trips/positions/events/app_config), D-backend REST (config, stations, availability, ports, search, trips, GPS re-plan, internal port-status), A3 static data, persistence baseline, demo scenarios, frontend demo UI.

Not implemented or diverging from the plan:
- **ML (B1–B3):** no model serving; every backend → ML call returns gateway defaults (see above). XGBoost/LSTM/Markov/CTGAN code and the A4 simulator live on branches `codex/ai-foundation` and `simulator`, **not merged** here; `ml/src`, `ml/tests`, `simulator/`, `shared/` contain only stale `__pycache__`. Untracked `ml/artifacts|data|results` are leftovers whose metadata is `serving_ready=false` and does not match `model_artifact.py`'s schema. Benchmarks are flagged `gold_synthetic_exploratory_not_for_serving`, and XGBoost does not beat persistence at 5–20 min.
- **No** wait distribution (`P(W>0)`, `E[W]`, `W90`), no anti-herding correction beyond planned-arrival load in Erlang C, no 5-minute prediction job, `predictions` table is never written by the backend.
- **No** WebSocket `/ws`, Redis, TimescaleDB, `POST /internal/predictions`, `PUT /internal/{stations,vehicles,config}`, incident reporting, abandoned-trip job, `vehicleId` filter on availability, per-connector forecast in station detail, or v1 `/vehicles` and `/geocode`.
- **Frontend** diverges from section E: Goong+Leaflet instead of MapLibre, no T…T+30 timeline slider, clustering, Tìm trạm/Tìm đường tabs, navigation mode (E5), station-detail forecast strip, or on-device storage; it drives scenario-based legacy endpoints rather than `/api/v1`.
- **F:** no Docker Compose for the full stack, CI, Makefile, OpenAPI TS client, Hypothesis/Playwright/Locust tests.

Rule from `docs/PHASE_INDEX.md`: Phase 03–04 are not done, so never record a model or `RELEASE PASS` as passing based on synthetic/demo data.
