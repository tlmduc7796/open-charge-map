"""The serving row must equal the training row of `ml.build_dataset` for the same window."""

from datetime import timedelta

import numpy as np
import pytest

pytest.importorskip("xgboost")
pd = pytest.importorskip("pandas")

import xgboost  # noqa: E402

from backend.app.domain.models import OccupancyWindow  # noqa: E402
from backend.app.domain.xgboost_predictor import (  # noqa: E402
    XgboostOccupancyPredictor,
    model_files_available,
)
from ml import build_dataset, features  # noqa: E402
from ml import geo_features as gf  # noqa: E402

TOTAL_PORTS = 6
# Distinct non-zero values so a served/trained mismatch on a geo column would be caught.
GEO_VALUES = tuple(float(index + 1) for index in range(len(gf.GEO_COLUMNS)))


def _geo_table() -> "pd.DataFrame":
    # Single-station universe: self-referencing nearest station (see
    # ml.geo_features._neighbor_features's degenerate-case convention).
    row = dict(zip(gf.GEO_COLUMNS, GEO_VALUES, strict=True))
    row[gf.NEAREST_STATION_ID_COLUMN] = "ST_TEST"
    return pd.DataFrame([row], index=pd.Index(["ST_TEST"], name="station_id"))


@pytest.fixture(scope="module")
def frame() -> "pd.DataFrame":
    index = pd.date_range("2026-03-02 00:00", periods=80, freq="5min", tz="Asia/Ho_Chi_Minh")
    rng = np.random.default_rng(7)
    raw = pd.DataFrame(
        {
            "station_id": "ST_TEST",
            "bucket_at": index,
            "total_ports": TOTAL_PORTS,
            "operational_ports": TOTAL_PORTS,
            "occupied_ports": rng.integers(0, TOTAL_PORTS + 1, size=len(index)),
        }
    )
    return build_dataset.build_frame(raw, geo_table=_geo_table(), warmup_hours=0)


def _train(frame: "pd.DataFrame", model_dir, *, wrong_features_for: int | None = None) -> None:
    for horizon in features.HORIZONS_MIN:
        k = horizon // features.INTERVAL_MIN
        columns = list(features.feature_columns(k))
        x = frame[columns].copy()
        if horizon == wrong_features_for:
            x = x.rename(columns={columns[0]: "unexpected"})
        booster = xgboost.train(
            {"max_depth": 2, "tree_method": "hist", "objective": "reg:squarederror"},
            xgboost.DMatrix(x, label=frame[f"y{k}"]),
            num_boost_round=6,
        )
        booster.save_model(str(model_dir / f"model_h{horizon}.json"))


@pytest.fixture(scope="module")
def model_dir(frame, tmp_path_factory):
    path = tmp_path_factory.mktemp("occupancy_model")
    _train(frame, path)
    return path


def _window(row: "pd.Series") -> OccupancyWindow:
    return OccupancyWindow(
        station_id="ST_TEST",
        lags=tuple(float(row[name]) for name in features.LAG_COLUMNS),
        t_last=row["t_last"].to_pydatetime(),
        total_ports=int(row["total_ports"]),
        geo_features=tuple(float(row[name]) for name in features.GEO_COLUMNS),
        nearest_station_occupancy=float(row[features.SPATIAL_LAG_COLUMNS[0]]),
    )


def test_serving_row_equals_the_training_row(frame, model_dir) -> None:
    predictor = XgboostOccupancyPredictor(model_dir)
    for position in (0, len(frame) // 2, len(frame) - 1):
        row = frame.iloc[position]
        window = _window(row)
        for horizon in features.HORIZONS_MIN:
            k = horizon // features.INTERVAL_MIN
            served = predictor._row(window, horizon)[0]
            trained = row[list(features.feature_columns(k))].to_numpy(dtype=np.float32)
            np.testing.assert_allclose(served, trained, atol=1e-6)


def test_prediction_matches_the_booster_and_is_a_ratio(frame, model_dir) -> None:
    predictor = XgboostOccupancyPredictor(model_dir)
    row = frame.iloc[5]
    window = _window(row)
    for horizon in features.HORIZONS_MIN:
        k = horizon // features.INTERVAL_MIN
        booster = xgboost.Booster()
        booster.load_model(str(model_dir / f"model_h{horizon}.json"))
        sample = xgboost.DMatrix(frame[list(features.feature_columns(k))].iloc[[5]])
        expected = float(booster.predict(sample)[0])

        value = predictor.predict(window, horizon)

        assert value == pytest.approx(min(1.0, max(0.0, expected)), abs=1e-5)
        assert 0.0 <= value <= 1.0


def test_prediction_depends_on_the_target_time(frame, model_dir) -> None:
    predictor = XgboostOccupancyPredictor(model_dir)
    row = frame.iloc[0]
    window = _window(row)
    later = window.model_copy(update={"t_last": window.t_last + timedelta(hours=7, minutes=5)})

    assert predictor._row(window, 15).tolist() != predictor._row(later, 15).tolist()


def test_unknown_horizon_is_rejected(frame, model_dir) -> None:
    predictor = XgboostOccupancyPredictor(model_dir)

    with pytest.raises(ValueError, match="no occupancy model"):
        predictor.predict(_window(frame.iloc[0]), 45)


def test_version_is_stable_and_files_are_detected(model_dir) -> None:
    assert model_files_available(model_dir)
    first = XgboostOccupancyPredictor(model_dir).model_version
    assert first == XgboostOccupancyPredictor(model_dir).model_version
    assert first.startswith("xgb-occupancy-")


def test_missing_files_are_reported(tmp_path) -> None:
    assert not model_files_available(tmp_path)
    with pytest.raises(FileNotFoundError):
        XgboostOccupancyPredictor(tmp_path)


def test_models_trained_on_another_feature_set_are_rejected(frame, tmp_path) -> None:
    _train(frame, tmp_path, wrong_features_for=10)

    with pytest.raises(ValueError, match="different feature set"):
        XgboostOccupancyPredictor(tmp_path)


@pytest.mark.parametrize("column", [features.GEO_COLUMNS[0], features.SPATIAL_LAG_COLUMNS[0]])
def test_cache_refreshes_when_geo_or_neighbor_input_changes(frame, model_dir, column) -> None:
    predictor = XgboostOccupancyPredictor(model_dir)
    index = features.feature_columns(1).index(column)
    calls = []

    class InputPredictor:
        def predict(self, matrix, **kwargs):
            calls.append(matrix)
            return np.asarray([matrix.get_data().toarray()[0, index]])

    predictor._models[5] = InputPredictor()
    base = _window(frame.iloc[0])
    if column in features.GEO_COLUMNS:
        before = base.model_copy(update={"geo_features": (0.1, *base.geo_features[1:])})
        after = base.model_copy(update={"geo_features": (0.9, *base.geo_features[1:])})
    else:
        before = base.model_copy(update={"nearest_station_occupancy": 0.1})
        after = base.model_copy(update={"nearest_station_occupancy": 0.9})
    assert predictor.predict(before, 5) == pytest.approx(0.1)
    assert predictor.predict(after, 5) == pytest.approx(0.9)
    assert predictor.predict(after, 5) == pytest.approx(0.9)
    assert len(calls) == 2


def test_unnamed_old_models_are_rejected(frame, tmp_path) -> None:
    _train(frame, tmp_path)
    old = xgboost.train(
        {"tree_method": "hist", "max_depth": 2},
        xgboost.DMatrix(frame[list(features.feature_columns(1))[:26]].to_numpy(),
                        label=frame["y1"]),
        num_boost_round=2,
    )
    old.save_model(str(tmp_path / "model_h5.json"))
    with pytest.raises(ValueError, match="different feature set"):
        XgboostOccupancyPredictor(tmp_path)
