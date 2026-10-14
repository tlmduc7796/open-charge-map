"""Serving adapter for the six per-horizon XGBoost occupancy models trained in `ml/`.

Feature construction is not reimplemented here: it reuses `ml.features`, the module the
training pipeline uses, so the serving row has exactly the training columns and order.
"""

from __future__ import annotations

import hashlib
import threading
from datetime import timedelta
from pathlib import Path

from backend.app.domain.models import OccupancyWindow

MODEL_FILE_TEMPLATE = "model_h{horizon}.json"
MEMO_LIMIT = 4096


def model_files(model_dir: Path) -> tuple[Path, ...]:
    horizons = (5, 10, 15, 20, 25, 30)
    return tuple(model_dir / MODEL_FILE_TEMPLATE.format(horizon=h) for h in horizons)


def model_files_available(model_dir: Path) -> bool:
    return all(path.is_file() for path in model_files(model_dir))


class XgboostOccupancyPredictor:
    """`predict(window, horizon_min)` -> occupancy ratio in [0, 1] at `t_last + horizon_min`."""

    def __init__(self, model_dir: Path) -> None:
        # Imported lazily so the backend still starts (with the default gateway) without them.
        import numpy as np
        import pandas as pd
        import xgboost

        from ml import features

        paths = model_files(model_dir)
        missing = [str(path) for path in paths if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"occupancy model files missing: {', '.join(missing)}")

        self._np = np
        self._pd = pd
        self._xgboost = xgboost
        self._features = features
        # The native Booster is used (not the sklearn wrapper) so scikit-learn is not needed.
        self._models: dict[int, xgboost.Booster] = {}
        self._iteration_range: dict[int, tuple[int, int]] = {}
        self._named: dict[int, bool] = {}
        digest = hashlib.sha256()
        for horizon, path in zip(features.HORIZONS_MIN, paths, strict=True):
            booster = xgboost.Booster()
            booster.load_model(str(path))
            expected = list(features.feature_columns(horizon // features.INTERVAL_MIN))
            stored = booster.feature_names
            if booster.num_features() != len(expected) or (
                stored is not None and list(stored) != expected
            ):
                raise ValueError(
                    f"{path.name} was trained on a different feature set than ml.features"
                )
            self._models[horizon] = booster
            self._named[horizon] = stored is not None
            # Same as XGBRegressor.predict: with early stopping only trees up to the best round.
            best = booster.attr("best_iteration")
            self._iteration_range[horizon] = (0, int(best) + 1) if best is not None else (0, 0)
            digest.update(path.read_bytes())
        self.model_version = f"xgb-occupancy-{digest.hexdigest()[:8]}"
        self._lock = threading.Lock()
        self._memo: dict[tuple, float] = {}

    @property
    def horizons_min(self) -> tuple[int, ...]:
        return tuple(self._models)

    def predict(self, window: OccupancyWindow, horizon_min: int) -> float:
        model = self._models.get(horizon_min)
        if model is None:
            raise ValueError(f"no occupancy model for horizon {horizon_min} min")
        key = (
            window.station_id,
            window.t_last,
            window.lags,
            window.total_ports,
            window.geo_features,
            window.nearest_station_occupancy,
            horizon_min,
        )
        cached = self._memo.get(key)
        if cached is not None:
            return cached
        row = self._row(window, horizon_min)
        k = horizon_min // self._features.INTERVAL_MIN
        matrix = self._xgboost.DMatrix(
            row,
            feature_names=(
                list(self._features.feature_columns(k)) if self._named[horizon_min] else None
            ),
        )
        with self._lock:
            raw = float(
                model.predict(matrix, iteration_range=self._iteration_range[horizon_min])[0]
            )
        value = min(1.0, max(0.0, raw))
        if len(self._memo) >= MEMO_LIMIT:
            self._memo.clear()
        self._memo[key] = value
        return value

    def _row(self, window: OccupancyWindow, horizon_min: int):
        np, pd, ft = self._np, self._pd, self._features
        k = horizon_min // ft.INTERVAL_MIN
        lags = np.asarray([window.lags], dtype=float)
        values: dict[str, float] = {
            name: float(lags[0, index]) for index, name in enumerate(ft.LAG_COLUMNS)
        }
        values.update(
            {name: float(column[0]) for name, column in ft.dynamics_features(lags).items()}
        )
        values["total_ports"] = float(window.total_ports)
        values.update(dict(zip(ft.GEO_COLUMNS, window.geo_features, strict=True)))
        values[ft.SPATIAL_LAG_COLUMNS[0]] = float(window.nearest_station_occupancy)
        last = ft.time_features(pd.DatetimeIndex([window.t_last]))
        values.update({f"last_{suffix}": float(v[0]) for suffix, v in last.items()})
        target = ft.time_features(
            pd.DatetimeIndex([window.t_last + timedelta(minutes=horizon_min)])
        )
        values.update({f"pred_h{k}_{suffix}": float(v[0]) for suffix, v in target.items()})
        columns = ft.feature_columns(k)
        return np.asarray([[values[column] for column in columns]], dtype=np.float32)
