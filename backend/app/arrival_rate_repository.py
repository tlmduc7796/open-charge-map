"""Database-backed baseline arrival rates and planned-arrival window."""

from __future__ import annotations

from sqlalchemy import Engine, text

from backend.app.domain.repositories import QueueAssumptionsRepository


class DatabaseArrivalRateRepository:
    def __init__(
        self,
        engine: Engine,
        scenario_assumptions: QueueAssumptionsRepository,
    ) -> None:
        self._scenario_assumptions = scenario_assumptions
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT s.code AS station_code, "
                    "r.baseline_arrival_rate_per_hour, r.data_source "
                    "FROM station_arrival_rates r "
                    "JOIN stations s ON s.id=r.station_id"
                )
            ).all()
            self._station_rates = {
                row.station_code: float(row.baseline_arrival_rate_per_hour)
                for row in rows
            }
            self._station_rate_sources = {
                row.station_code: str(row.data_source) for row in rows
            }
            window_min = connection.scalar(
                text(
                    "SELECT value FROM app_config "
                    "WHERE key='planned_arrival_window_min'"
                )
            )
        if not self._station_rates:
            raise ValueError("station arrival rates are missing from the database")
        if isinstance(window_min, bool) or not isinstance(window_min, int) or window_min <= 0:
            raise ValueError("planned_arrival_window_min must be a positive integer")
        self._planned_arrival_window_min = window_min

    @property
    def planned_arrival_window_min(self) -> int:
        return self._planned_arrival_window_min

    def baseline_rate(self, station_id: str, scenario_id: str | None = None) -> float:
        if scenario_id is not None and self.has_override(scenario_id, station_id):
            return self._scenario_assumptions.baseline_rate(station_id, scenario_id)
        return self._station_rates[station_id]

    def has_override(self, scenario_id: str, station_id: str) -> bool:
        return self._scenario_assumptions.has_override(scenario_id, station_id)

    def baseline_source(self, station_id: str, scenario_id: str | None = None) -> str:
        if scenario_id is not None and self.has_override(scenario_id, station_id):
            return self._scenario_assumptions.baseline_source(station_id, scenario_id)
        return self._station_rate_sources[station_id]
