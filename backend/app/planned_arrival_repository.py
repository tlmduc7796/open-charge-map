"""PostgreSQL persistence for planned-arrival lifecycle operations."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, Engine, bindparam, text
from sqlalchemy.exc import IntegrityError

from backend.app.domain.models import PlannedArrival
from backend.app.domain.phase7_models import PlannedArrivalCreateRequest
from backend.app.domain.runtime import planned_arrival_matches_request

DEMO_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")

_SELECT_ARRIVALS = """
    SELECT pa.arrival_id, s.code AS station_code, vm.code AS vehicle_code,
           pa.route_id, pa.created_at, pa.eta_at, pa.eta_window_start,
           pa.eta_window_end, pa.expected_energy_kwh,
           pa.expected_charge_duration_min, pa.arrival_probability,
           pa.expires_at, pa.status, pa.data_source, pa.provenance
    FROM planned_arrivals pa
    JOIN stations s ON s.id = pa.station_id
    LEFT JOIN vehicle_models vm ON vm.id = pa.vehicle_model_id
"""


class DatabasePlannedArrivalRepository:
    def __init__(
        self,
        engine: Engine,
        base_arrivals: tuple[PlannedArrival, ...],
    ) -> None:
        self._engine = engine
        self._base_arrivals = base_arrivals

    @staticmethod
    def _provenance(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            return json.loads(value)
        return {}

    @classmethod
    def _to_domain(cls, row: Any) -> PlannedArrival:
        provenance = cls._provenance(row["provenance"])
        return PlannedArrival(
            arrival_id=row["arrival_id"],
            station_id=row["station_code"],
            vehicle_id=provenance.get("vehicle_ref") or row["vehicle_code"],
            created_at=row["created_at"].astimezone(DEMO_TIMEZONE),
            eta_at=row["eta_at"].astimezone(DEMO_TIMEZONE),
            eta_window_start=row["eta_window_start"].astimezone(DEMO_TIMEZONE),
            eta_window_end=row["eta_window_end"].astimezone(DEMO_TIMEZONE),
            expected_energy_kwh=float(row["expected_energy_kwh"]),
            expected_charge_duration_min=float(
                row["expected_charge_duration_min"]
            ),
            arrival_probability=float(row["arrival_probability"]),
            expires_at=row["expires_at"].astimezone(DEMO_TIMEZONE),
            route_id=row["route_id"],
            status=row["status"],
            data_source=row["data_source"],
        )

    @staticmethod
    def _station_id(connection: Connection, station_code: str) -> Any:
        station_id = connection.scalar(
            text("SELECT id FROM stations WHERE code=:code"),
            {"code": station_code},
        )
        if station_id is None:
            raise KeyError(station_code)
        return station_id

    @classmethod
    def _vehicle_model_id(
        cls, connection: Connection, vehicle_code: str | None
    ) -> Any | None:
        if vehicle_code is None:
            return None
        rows = connection.execute(
            text("SELECT id, code, provenance FROM vehicle_models")
        ).mappings()
        matches = []
        for row in rows:
            provenance = cls._provenance(row["provenance"])
            legacy_code = provenance.get("_legacy_demo", {}).get("vehicle_id")
            if vehicle_code in {row["code"], legacy_code}:
                matches.append(row["id"])
        if not matches:
            raise KeyError(vehicle_code)
        if len(matches) > 1:
            raise ValueError(f"ambiguous vehicle reference: {vehicle_code}")
        return matches[0]

    @classmethod
    def _insert(
        cls,
        connection: Connection,
        arrival: PlannedArrival,
    ) -> None:
        connection.execute(
            text(
                "INSERT INTO planned_arrivals "
                "(arrival_id, station_id, vehicle_model_id, route_id, created_at, eta_at, "
                "eta_window_start, eta_window_end, expected_energy_kwh, "
                "expected_charge_duration_min, arrival_probability, expires_at, status, "
                "data_source, provenance) VALUES "
                "(:arrival_id, :station_id, :vehicle_model_id, :route_id, :created_at, "
                ":eta_at, :eta_window_start, :eta_window_end, :expected_energy_kwh, "
                ":expected_charge_duration_min, :arrival_probability, :expires_at, "
                ":status, :data_source, CAST(:provenance AS jsonb))"
            ),
            {
                **arrival.model_dump(),
                "station_id": cls._station_id(connection, arrival.station_id),
                "vehicle_model_id": cls._vehicle_model_id(
                    connection, arrival.vehicle_id
                ),
                "provenance": json.dumps(
                    {
                        "origin": arrival.data_source,
                        "provider": (
                            "planned_arrivals_fixture"
                            if arrival.data_source == "synthetic"
                            else "backend_api"
                        ),
                        "station_code": arrival.station_id,
                        "vehicle_ref": arrival.vehicle_id,
                    }
                ),
            },
        )

    def all(self) -> tuple[PlannedArrival, ...]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(_SELECT_ARRIVALS + " ORDER BY pa.created_at, pa.arrival_id")
            ).mappings()
            return tuple(self._to_domain(row) for row in rows)

    def active_for_stations(
        self, station_ids: tuple[str, ...]
    ) -> tuple[PlannedArrival, ...]:
        if not station_ids:
            return ()
        statement = text(
            _SELECT_ARRIVALS
            + " WHERE pa.status='planned' AND s.code IN :station_ids "
            "ORDER BY pa.eta_at, pa.arrival_id"
        ).bindparams(bindparam("station_ids", expanding=True))
        with self._engine.connect() as connection:
            rows = connection.execute(
                statement, {"station_ids": station_ids}
            ).mappings()
            return tuple(self._to_domain(row) for row in rows)

    def get(self, arrival_id: str) -> PlannedArrival:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(_SELECT_ARRIVALS + " WHERE pa.arrival_id=:arrival_id"),
                {"arrival_id": arrival_id},
            ).mappings().one_or_none()
        if row is None:
            raise KeyError(arrival_id)
        return self._to_domain(row)

    def register(
        self,
        request: PlannedArrivalCreateRequest,
        *,
        created_at: datetime,
    ) -> PlannedArrival:
        if request.arrival_id is not None:
            try:
                existing = self.get(request.arrival_id)
            except KeyError:
                pass
            else:
                if planned_arrival_matches_request(existing, request):
                    return existing
                raise ValueError(
                    f"arrival_id already exists: {request.arrival_id}"
                )
        arrival = PlannedArrival(
            arrival_id=request.arrival_id or f"ARR_{uuid4().hex[:12].upper()}",
            station_id=request.station_id,
            vehicle_id=request.vehicle_id,
            created_at=created_at,
            eta_at=request.eta_at,
            eta_window_start=request.eta_window_start,
            eta_window_end=request.eta_window_end,
            expected_energy_kwh=request.expected_energy_kwh,
            expected_charge_duration_min=request.expected_charge_duration_min,
            arrival_probability=request.arrival_probability,
            expires_at=request.expires_at,
            route_id=request.route_id,
            status="planned",
            data_source="runtime",
        )
        try:
            with self._engine.begin() as connection:
                self._insert(connection, arrival)
        except IntegrityError as exc:
            if request.arrival_id is not None:
                existing = self.get(request.arrival_id)
                if planned_arrival_matches_request(existing, request):
                    return existing
            raise ValueError(
                f"arrival_id already exists: {arrival.arrival_id}"
            ) from exc
        return self.get(arrival.arrival_id)

    def _transition(self, arrival_id: str, status: str) -> PlannedArrival:
        with self._engine.begin() as connection:
            updated = connection.execute(
                text(
                    "UPDATE planned_arrivals SET status=:status "
                    "WHERE arrival_id=:arrival_id AND status='planned' "
                    "RETURNING arrival_id"
                ),
                {"arrival_id": arrival_id, "status": status},
            ).scalar_one_or_none()
            if updated is None:
                current = connection.scalar(
                    text(
                        "SELECT status FROM planned_arrivals "
                        "WHERE arrival_id=:arrival_id"
                    ),
                    {"arrival_id": arrival_id},
                )
                if current is None:
                    raise KeyError(arrival_id)
                raise ValueError(
                    f"planned arrival {arrival_id} cannot transition from {current}"
                )
        return self.get(arrival_id)

    def cancel(self, arrival_id: str) -> PlannedArrival:
        return self._transition(arrival_id, "cancelled")

    def mark_arrived(self, arrival_id: str) -> PlannedArrival:
        return self._transition(arrival_id, "arrived")

    def expire(self, evaluation_at: datetime) -> tuple[PlannedArrival, ...]:
        with self._engine.begin() as connection:
            expired_ids = tuple(
                connection.execute(
                    text(
                        "UPDATE planned_arrivals SET status='expired' "
                        "WHERE status='planned' AND expires_at <= :evaluation_at "
                        "RETURNING arrival_id"
                    ),
                    {"evaluation_at": evaluation_at},
                ).scalars()
            )
        expired = set(expired_ids)
        return tuple(
            arrival for arrival in self.all() if arrival.arrival_id in expired
        )

    def reset(self) -> None:
        with self._engine.begin() as connection:
            connection.execute(text("DELETE FROM planned_arrivals"))
            for arrival in self._base_arrivals:
                self._insert(connection, arrival)
