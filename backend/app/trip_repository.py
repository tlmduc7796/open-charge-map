"""PostgreSQL log of "Chỉ đường" clicks: one `trips` row per click."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Engine, text

from backend.app.api_v1_models import ApiPoint

_INSERT = text(
    """
    INSERT INTO trips
    (id, mode, vehicle_model_id, origin, destination, start_battery_pct,
     recommended_station_id, actual_station_id, created_at)
    VALUES
    (CAST(:trip_id AS uuid), :mode, :vehicle_uuid,
     ST_SetSRID(ST_MakePoint(:origin_lng, :origin_lat), 4326)::geography,
     CASE WHEN CAST(:destination_lng AS double precision) IS NULL THEN NULL ELSE
       ST_SetSRID(
         ST_MakePoint(CAST(:destination_lng AS double precision),
                      CAST(:destination_lat AS double precision)),
         4326
       )::geography
     END,
     :battery_pct, :recommended_uuid, :actual_uuid, :created_at)
    """
)


class DatabaseTripRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def log_direction_click(
        self,
        *,
        mode: str,
        vehicle_id: str,
        origin: ApiPoint,
        destination: ApiPoint | None,
        battery_pct: float,
        recommended_station_id: str,
        actual_station_id: str,
        created_at: datetime,
    ) -> str:
        """Insert one click and return its id. Raises KeyError for an unknown vehicle/station."""
        trip_id = uuid4()
        with self._engine.begin() as connection:
            vehicle_uuid = connection.scalar(
                text("SELECT id FROM vehicle_models WHERE code=:code"), {"code": vehicle_id}
            )
            if vehicle_uuid is None:
                raise KeyError(vehicle_id)
            station_uuids: dict[str, object] = {}
            for code in {recommended_station_id, actual_station_id}:
                station_uuid = connection.scalar(
                    text("SELECT id FROM stations WHERE code=:code"), {"code": code}
                )
                if station_uuid is None:
                    raise KeyError(code)
                station_uuids[code] = station_uuid
            connection.execute(
                _INSERT,
                {
                    "trip_id": str(trip_id),
                    "mode": mode,
                    "vehicle_uuid": vehicle_uuid,
                    "origin_lng": origin.lng,
                    "origin_lat": origin.lat,
                    "destination_lng": destination.lng if destination else None,
                    "destination_lat": destination.lat if destination else None,
                    "battery_pct": battery_pct,
                    "recommended_uuid": station_uuids[recommended_station_id],
                    "actual_uuid": station_uuids[actual_station_id],
                    "created_at": created_at,
                },
            )
        return str(trip_id)
