import asyncio
import json
import math
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import httpx
import joblib
import pytest

from backend.app.config import load_settings
from backend.app.domain.forecasting import OccupancyForecastService
from backend.app.domain.occupancy_model import (
    LAG_FEATURES,
    TIME_FEATURES,
    ModelContractError,
    OccupancyModelMeta,
    PersistenceEstimator,
    build_feature_row,
    load_meta,
    load_occupancy_model,
    load_predictor_strict,
)
from backend.app.domain.recommendation import RecommendationService, RecommendationThresholds
from backend.app.domain.repositories import load_domain_data
from backend.app.main import app

ROOT = Path(__file__).resolve().parents[2]


class LastLagPlusOffset:
    """Picklable stand-in estimator: newest lag plus a horizon-specific offset."""

    def __init__(self, offset: float) -> None:
        self.offset = offset

    def predict(self, rows):
        return [row[11] + self.offset for row in rows]


class FeatureEcho:
    """Returns one named column of the feature row, to prove the row layout."""

    def __init__(self, index: int) -> None:
        self.index = index

    def predict(self, rows):
        return [row[self.index] for row in rows]


class NaNEstimator:
    def predict(self, rows):
        return [math.nan for _ in rows]


class DoubleScaler:
    def transform(self, rows):
        return [[value * 2 for value in row] for row in rows]


def _meta(**overrides) -> dict:
    meta = {
        "model_name": "smart_ev_occupancy_v1",
        "model_version": "1.0.0",
        "task": "occupancy_forecasting",
        "training_dataset": "UrbanEV",
        "training_level": "station",
        "temporal_resolution_min": 5,
        "lookback_steps": 12,
        "forecast_steps": 3,
        "features": list(LAG_FEATURES),
        "target": "occupancy_ratio",
        "metrics": {"mae": 0.05, "rmse": 0.08},
        "notes": ["Station identifiers are not transferable features."],
    }
    meta.update(overrides)
    return meta


def _offset_models():
    return {5: LastLagPlusOffset(0.01), 10: LastLagPlusOffset(0.02), 15: LastLagPlusOffset(0.03)}


def _write_artifacts(tmp_path: Path, *, meta=None, models=None, preprocessor=None):
    model_path = tmp_path / "occupancy_model.joblib"
    preprocessor_path = tmp_path / "occupancy_preprocessor.joblib"
    meta_path = tmp_path / "occupancy_model_meta.json"
    joblib.dump(models if models is not None else _offset_models(), model_path)
    joblib.dump(preprocessor, preprocessor_path)
    meta_path.write_text(json.dumps(meta or _meta()), encoding="utf-8")
    return replace(
        load_settings(),
        model_artifact_path=model_path,
        model_preprocessor_path=preprocessor_path,
        model_meta_path=meta_path,
    )


def _deutsches_status():
    data = load_domain_data(load_settings().data_dir)
    return data.station_statuses.get("ST_EVO_DEUTSCHES_HAUS")


# --- loading -----------------------------------------------------------------------------


def test_missing_artifacts_are_absent_not_an_error(tmp_path: Path) -> None:
    settings = replace(
        load_settings(),
        model_artifact_path=tmp_path / "a.joblib",
        model_preprocessor_path=tmp_path / "b.joblib",
        model_meta_path=tmp_path / "c.json",
    )

    result = load_occupancy_model(settings)

    assert result.state == "absent"
    assert result.predictor is None
    assert result.error is None


def test_valid_artifacts_load_and_predict_per_horizon(tmp_path: Path) -> None:
    result = load_occupancy_model(_write_artifacts(tmp_path))

    assert result.state == "loaded"
    history = (0.1,) * 11 + (0.4,)
    assert result.predictor.predict(history, 5) == pytest.approx(0.41)
    assert result.predictor.predict(history, 10) == pytest.approx(0.42)
    assert result.predictor.predict(history, 15) == pytest.approx(0.43)


def test_preprocessor_is_applied_before_the_estimator(tmp_path: Path) -> None:
    result = load_occupancy_model(_write_artifacts(tmp_path, preprocessor=DoubleScaler()))

    # newest lag 0.2 -> scaled to 0.4 -> + 0.01
    assert result.predictor.predict((0.1,) * 11 + (0.2,), 5) == pytest.approx(0.41)


def test_loaded_model_drives_the_forecast_service(tmp_path: Path) -> None:
    predictor = load_occupancy_model(_write_artifacts(tmp_path)).predictor

    result = OccupancyForecastService(predictor).forecast_occupancy(
        _deutsches_status(), horizon_min=10
    )

    assert result.prediction_source == "model"
    assert result.predicted_occupancy_ratio == pytest.approx(0.77)
    assert "SYNTHETIC_HISTORY" in result.flags
    assert "PERSISTENCE_FALLBACK" not in result.flags


@pytest.mark.parametrize(
    "overrides",
    [
        {"target": "occupied_ports"},
        {"lookback_steps": 6},
        {"temporal_resolution_min": 15},
        {"forecast_steps": 1},
        {"features": ["occupied_ports", "occupancy_ratio", "total_ports"]},
        {"features": [*LAG_FEATURES, "station_id"]},
        {"features": [*LAG_FEATURES, "queue_length"]},
        {"features": list(LAG_FEATURES[:-1])},
        {"features": [*LAG_FEATURES, "lag_1"]},
    ],
)
def test_meta_that_breaks_the_serving_contract_is_rejected(
    tmp_path: Path, overrides: dict
) -> None:
    with pytest.raises(ValueError):
        OccupancyModelMeta.model_validate(_meta(**overrides))

    settings = _write_artifacts(tmp_path, meta=_meta(**overrides))
    with pytest.raises(ModelContractError):
        load_meta(settings.model_meta_path)
    result = load_occupancy_model(settings)
    assert result.state == "invalid"
    assert result.predictor is None
    assert result.error


def test_artifact_missing_a_horizon_is_invalid_with_a_reason(tmp_path: Path) -> None:
    settings = _write_artifacts(
        tmp_path, models={5: LastLagPlusOffset(0.0), 10: LastLagPlusOffset(0.0)}
    )

    result = load_occupancy_model(settings)

    assert result.state == "invalid"
    assert "15" in result.error


def test_estimator_without_predict_is_invalid(tmp_path: Path) -> None:
    settings = _write_artifacts(tmp_path, models={5: object(), 10: object(), 15: object()})

    assert "predict" in load_occupancy_model(settings).error


def test_corrupt_model_file_is_invalid_with_a_reason(tmp_path: Path) -> None:
    settings = _write_artifacts(tmp_path)
    settings.model_artifact_path.write_bytes(b"not a joblib file")

    result = load_occupancy_model(settings)

    assert result.state == "invalid"
    assert "unpickle" in result.error


def test_model_returning_garbage_fails_the_smoke_check(tmp_path: Path) -> None:
    settings = _write_artifacts(
        tmp_path, models={5: NaNEstimator(), 10: NaNEstimator(), 15: NaNEstimator()}
    )

    with pytest.raises(ModelContractError):
        load_predictor_strict(
            settings.model_artifact_path,
            settings.model_preprocessor_path,
            settings.model_meta_path,
        )


def test_unsupported_horizon_and_history_length_are_rejected(tmp_path: Path) -> None:
    predictor = load_occupancy_model(_write_artifacts(tmp_path)).predictor

    with pytest.raises(ValueError):
        predictor.predict((0.1,) * 12, 7)
    with pytest.raises(ValueError):
        predictor.predict((0.1,) * 5, 5)


# --- time features -----------------------------------------------------------------------


def test_feature_row_follows_meta_order_and_time_formulas() -> None:
    history = tuple(range(12))  # lag_12 .. lag_1 == 0 .. 11
    # 2026-09-29T23:00Z == 2026-09-30 06:00 in UTC+7, a Wednesday (weekday 2)
    observed_at = datetime(2026, 9, 29, 23, 0, tzinfo=UTC)

    row = build_feature_row(
        ("hour_sin", "lag_1", "dow_cos", "lag_12", "hour_cos"), history, observed_at
    )

    assert row[0] == pytest.approx(1.0)  # sin(2*pi*6/24)
    assert row[1] == 11
    assert row[2] == pytest.approx(math.cos(2 * math.pi * 2 / 7))
    assert row[3] == 0
    assert row[4] == pytest.approx(0.0, abs=1e-12)


def test_time_features_require_a_timezone_aware_timestamp() -> None:
    with pytest.raises(ValueError):
        build_feature_row(("lag_1", "hour_sin"), (0.0,) * 12, None)
    with pytest.raises(ValueError):
        build_feature_row(("lag_1", "hour_sin"), (0.0,) * 12, datetime(2026, 9, 30, 6, 0))


def test_fixed_utc_plus_7_is_used_for_the_wall_clock() -> None:
    tz = timezone(timedelta(hours=-5))
    same_instant = datetime(2026, 9, 30, 6, 0, tzinfo=timezone(timedelta(hours=7))).astimezone(tz)

    a = build_feature_row(("hour_sin", "dow_sin"), (0.0,) * 12, same_instant)
    b = build_feature_row(
        ("hour_sin", "dow_sin"),
        (0.0,) * 12,
        datetime(2026, 9, 30, 6, 0, tzinfo=timezone(timedelta(hours=7))),
    )

    assert a == pytest.approx(b)


def test_model_with_time_features_gets_observed_at_through_the_service(tmp_path: Path) -> None:
    features = [*LAG_FEATURES, *TIME_FEATURES]
    hour_sin_index = features.index("hour_sin")
    models = {h: FeatureEcho(hour_sin_index) for h in (5, 10, 15)}
    # hour_sin == 1.0 at 06:00 (UTC+7); the service clamps predictions to [0, 1]
    settings = _write_artifacts(tmp_path, meta=_meta(features=features), models=models)
    predictor = load_occupancy_model(settings).predictor
    assert predictor.uses_timestamp is True
    service = OccupancyForecastService(predictor)

    with_time = service.forecast_occupancy(
        _deutsches_status(),
        horizon_min=5,
        observed_at=datetime(2026, 9, 30, 6, 0, tzinfo=timezone(timedelta(hours=7))),
    )
    without_time = service.forecast_occupancy(_deutsches_status(), horizon_min=5)

    assert with_time.prediction_source == "model"
    assert with_time.predicted_occupancy_ratio == pytest.approx(1.0)
    assert without_time.prediction_source == "persistence"
    assert "MODEL_INFERENCE_FAILED" in without_time.flags


def test_recommendation_passes_departure_time_as_observation_time() -> None:
    seen: list[datetime] = []

    class RecordingPredictor:
        uses_timestamp = True

        def predict(self, occupancy_history, horizon_min, observed_at=None):
            seen.append(observed_at)
            return 0.5

    state = app.state
    service = RecommendationService(
        state.domain_data,
        state.runtime_state,
        state.planned_arrival_store,
        state.routing_service,
        OccupancyForecastService(RecordingPredictor()),
        state.wait_estimator,
        RecommendationThresholds(30, 120, 90, 0.2),
    )
    scenario = state.domain_data.demo_scenarios.get("SCN_NORMAL")

    result = service.recommend("SCN_NORMAL")

    assert result.recommendations
    assert {item.prediction_source for item in result.recommendations} == {"model"}
    assert set(seen) == {scenario.departure_at}


# --- status endpoint and tooling ---------------------------------------------------------


def _get_json(path: str) -> dict:
    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path)

    return asyncio.run(request()).json()


def test_model_status_reports_a_loaded_model(tmp_path: Path, monkeypatch) -> None:
    settings = _write_artifacts(tmp_path)
    result = load_occupancy_model(settings)
    monkeypatch.setattr(app.state, "settings", settings)
    monkeypatch.setattr(app.state, "model_load", result)
    monkeypatch.setattr(
        app.state, "occupancy_forecast_service", OccupancyForecastService(result.predictor)
    )

    body = _get_json("/model/status")

    assert body["prediction_source"] == "model"
    assert body["release_ready"] is True
    assert body["model_name"] == "smart_ev_occupancy_v1"
    assert body["model_version"] == "1.0.0"
    assert body["load_error"] is None


def test_model_status_shows_why_a_model_was_rejected(tmp_path: Path, monkeypatch) -> None:
    settings = _write_artifacts(tmp_path, meta=_meta(target="occupied_ports"))
    result = load_occupancy_model(settings)
    monkeypatch.setattr(app.state, "settings", settings)
    monkeypatch.setattr(app.state, "model_load", result)
    monkeypatch.setattr(app.state, "occupancy_forecast_service", OccupancyForecastService())

    body = _get_json("/model/status")
    checks = {c["name"]: c for c in _get_json("/health/checks")["checks"]}

    assert body["prediction_source"] == "persistence"
    assert body["release_ready"] is False
    assert "occupancy_ratio" in body["load_error"] or "target" in body["load_error"]
    assert "MODEL_ADAPTER_NOT_LOADED" in body["flags"]
    assert checks["occupancy_model"]["status"] == "warn"


def _run_script(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, *args], cwd=ROOT, capture_output=True, text=True, timeout=120
    )


@pytest.mark.parametrize("extra", [[], ["--time-features"]])
def test_example_artifacts_pass_the_validator_script(tmp_path: Path, extra: list[str]) -> None:
    made = _run_script("scripts/make_example_model_artifacts.py", "--out", str(tmp_path), *extra)
    assert made.returncode == 0, made.stderr

    checked = _run_script("scripts/validate_model_artifacts.py", "--dir", str(tmp_path))

    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert "PASS" in checked.stdout


def test_validator_script_fails_on_a_bad_contract(tmp_path: Path) -> None:
    _run_script("scripts/make_example_model_artifacts.py", "--out", str(tmp_path))
    meta_path = tmp_path / "occupancy_model_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["target"] = "occupied_ports"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    checked = _run_script("scripts/validate_model_artifacts.py", "--dir", str(tmp_path))

    assert checked.returncode == 1
    assert "FAIL" in checked.stdout


def test_persistence_estimator_is_the_reference_baseline() -> None:
    assert PersistenceEstimator(11).predict([[*range(11), 0.7]]) == [0.7]
