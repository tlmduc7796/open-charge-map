"""Read contiguous, observed five-minute occupancy windows for model serving."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import Engine, bindparam, text


class DatabaseOccupancyHistoryRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get_history(
        self,
        station_id: str,
        *,
        as_of: datetime,
        steps: int,
    ) -> tuple[float, ...] | None:
        if as_of.tzinfo is None:
            raise ValueError("occupancy history as_of must include a timezone")
        if steps <= 0:
            raise ValueError("occupancy history steps must be positive")
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT o.bucket_at, o.occupied_ports, o.operational_ports "
                    "FROM station_occupancy_5m o "
                    "JOIN stations s ON s.id=o.station_id "
                    "WHERE s.code=:station_id AND o.data_origin='observed' "
                    "AND o.bucket_at<=:as_of "
                    "ORDER BY o.bucket_at DESC LIMIT :steps"
                ),
                {"station_id": station_id, "as_of": as_of, "steps": steps},
            ).mappings().all()

        if len(rows) != steps:
            return None
        chronological = tuple(reversed(rows))
        if any(
            right["bucket_at"] - left["bucket_at"] != timedelta(minutes=5)
            for left, right in zip(chronological, chronological[1:])
        ):
            return None
        if as_of - chronological[-1]["bucket_at"] > timedelta(minutes=5):
            return None
        ratios: list[float] = []
        for row in chronological:
            operational = int(row["operational_ports"])
            if operational <= 0:
                return None
            ratio = int(row["occupied_ports"]) / operational
            if not 0 <= ratio <= 1:
                return None
            ratios.append(ratio)
        return tuple(ratios)

    def get_observations(
        self,
        station_id: str,
        *,
        start_at: datetime,
        end_at: datetime,
        limit: int,
    ) -> tuple[dict[str, object], ...]:
        """Return bounded, timestamped observed occupancy for the public history view."""
        if start_at.tzinfo is None or end_at.tzinfo is None:
            raise ValueError("occupancy history bounds must include a timezone")
        if start_at >= end_at:
            raise ValueError("occupancy history start must be before end")
        if not 1 <= limit <= 1000:
            raise ValueError("occupancy history limit must be between 1 and 1000")
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT o.bucket_at, o.total_ports, o.operational_ports, "
                    "o.occupied_ports, o.queue_length, o.data_origin "
                    "FROM station_occupancy_5m o JOIN stations s ON s.id=o.station_id "
                    "WHERE s.code=:station_id AND o.data_origin='observed' "
                    "AND o.bucket_at>=:start_at AND o.bucket_at<=:end_at "
                    "ORDER BY o.bucket_at DESC LIMIT :limit"
                ),
                {"station_id": station_id, "start_at": start_at, "end_at": end_at,
                 "limit": limit},
            ).mappings().all()
        return tuple(dict(row) for row in reversed(rows))

    def count_stations_with_complete_history(
        self,
        station_ids: tuple[str, ...],
        *,
        as_of: datetime,
        steps: int,
    ) -> int:
        """Count stations with a fresh, contiguous observed window for serving."""
        if as_of.tzinfo is None:
            raise ValueError("occupancy history as_of must include a timezone")
        if steps <= 0:
            raise ValueError("occupancy history steps must be positive")
        if not station_ids:
            return 0

        statement = text(
            "WITH recent AS ("
            "SELECT s.code AS station_id, o.bucket_at, o.operational_ports, "
            "o.occupied_ports FROM stations s CROSS JOIN LATERAL ("
            "SELECT bucket_at, operational_ports, occupied_ports "
            "FROM station_occupancy_5m WHERE station_id=s.id "
            "AND data_origin='observed' AND bucket_at<=:as_of "
            "ORDER BY bucket_at DESC LIMIT :steps) o "
            "WHERE s.code IN :station_ids), grouped AS ("
            "SELECT station_id, count(*) AS bucket_count, min(bucket_at) AS oldest_bucket, "
            "max(bucket_at) AS newest_bucket, bool_and(operational_ports>0) AS usable "
            "FROM recent GROUP BY station_id) "
            "SELECT count(*) FILTER (WHERE bucket_count=:steps "
            "AND newest_bucket-oldest_bucket=(:steps-1)*interval '5 minutes' "
            "AND newest_bucket>=:as_of-interval '5 minutes' AND usable) "
            "FROM grouped"
        ).bindparams(bindparam("station_ids", expanding=True))
        with self._engine.connect() as connection:
            return int(
                connection.execute(
                    statement,
                    {"station_ids": station_ids, "as_of": as_of, "steps": steps},
                ).scalar_one()
            )
