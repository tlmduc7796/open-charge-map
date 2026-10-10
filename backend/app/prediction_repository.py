"""Persist timestamped occupancy forecast outputs in PostgreSQL."""

from __future__ import annotations

from sqlalchemy import Engine, bindparam, text

from backend.app.domain.model_contract import SUPPORTED_HORIZONS_MIN
from backend.app.domain.models import OccupancyForecastResult


class DatabasePredictionRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def save_occupancy_forecast(self, result: OccupancyForecastResult) -> bool:
        """Idempotently persist a product-horizon forecast; return false if unsupported."""
        return bool(self.save_occupancy_forecasts((result,)))

    def save_occupancy_forecasts(
        self, results: tuple[OccupancyForecastResult, ...]
    ) -> int:
        """Persist a forecast batch in one transaction; return the rows written."""
        parameters = []
        station_ids: set[str] = set()
        for result in results:
            if result.requested_horizon_min not in SUPPORTED_HORIZONS_MIN:
                continue
            if result.generated_at is None or result.generated_at.tzinfo is None:
                raise ValueError(
                    "persisted occupancy forecast requires a timezone timestamp"
                )
            if result.prediction_source == "model" and result.model_version is None:
                raise ValueError("model forecast persistence requires model_version")
            station_ids.add(result.station_id)
            parameters.append(
                {
                    "station_code": result.station_id,
                    "run_at": result.generated_at,
                    "horizon_min": result.requested_horizon_min,
                    "predicted_occupancy_ratio": result.predicted_occupancy_ratio,
                    "operational_ports": result.operational_ports,
                    "prediction_source": result.prediction_source,
                    "model_version": result.model_version or "persistence",
                }
            )
        if not parameters:
            return 0

        select_stations = text(
            "SELECT code, id FROM stations WHERE code IN :station_codes"
        ).bindparams(bindparam("station_codes", expanding=True))
        statement = text(
            "INSERT INTO predictions ("
            "station_id, run_at, horizon_min, predicted_occupancy_ratio, "
            "operational_ports_at_run, wait_probability, mean_wait_minutes, "
            "p90_wait_minutes, prediction_source, model_version"
            ") VALUES ("
            ":station_id, :run_at, :horizon_min, :predicted_occupancy_ratio, "
            ":operational_ports, NULL, NULL, NULL, "
            "CAST(:prediction_source AS prediction_source), :model_version) "
            "ON CONFLICT (station_id, run_at, horizon_min) DO UPDATE SET "
            "predicted_occupancy_ratio=EXCLUDED.predicted_occupancy_ratio, "
            "operational_ports_at_run=EXCLUDED.operational_ports_at_run, "
            "wait_probability=EXCLUDED.wait_probability, "
            "mean_wait_minutes=EXCLUDED.mean_wait_minutes, "
            "p90_wait_minutes=EXCLUDED.p90_wait_minutes, "
            "prediction_source=EXCLUDED.prediction_source, "
            "model_version=EXCLUDED.model_version"
        )
        with self._engine.begin() as connection:
            station_rows = connection.execute(
                select_stations, {"station_codes": tuple(sorted(station_ids))}
            ).mappings()
            station_pk_by_code = {row["code"]: row["id"] for row in station_rows}
            missing = station_ids - station_pk_by_code.keys()
            if missing:
                raise KeyError(sorted(missing)[0])
            for values in parameters:
                values["station_id"] = station_pk_by_code[values.pop("station_code")]
            connection.execute(statement, parameters)
        return len(parameters)
