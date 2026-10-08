from __future__ import annotations

import os
from datetime import datetime

import pytest
from sqlalchemy import create_engine

from backend.app.config import load_settings
from backend.app.domain.phase7_models import PlannedArrivalCreateRequest
from backend.app.domain.repositories import load_domain_data
from backend.app.planned_arrival_repository import DatabasePlannedArrivalRepository

TEST_DATABASE_URL = os.getenv("BACKEND_TEST_DATABASE_URL")


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="BACKEND_TEST_DATABASE_URL is required for PostgreSQL integration",
)
def test_database_planned_arrival_lifecycle_persists_and_resets() -> None:
    data = load_domain_data(load_settings().data_dir)
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    repository = DatabasePlannedArrivalRepository(
        engine, data.planned_arrivals.all()
    )
    request = PlannedArrivalCreateRequest(
        arrival_id="ARR_DATABASE_TEST",
        station_id="ST_EVO_LAVIDA_Q7",
        vehicle_id="EV_VF5_PLUS",
        eta_at="2026-10-08T10:10:00+07:00",
        eta_window_start="2026-10-08T10:05:00+07:00",
        eta_window_end="2026-10-08T10:15:00+07:00",
        expected_energy_kwh=12,
        expected_charge_duration_min=20,
        arrival_probability=0.8,
        expires_at="2026-10-08T10:20:00+07:00",
        route_id="ROUTE_VIA_LAVIDA",
    )

    try:
        repository.reset()
        registered = repository.register(
            request,
            created_at=datetime.fromisoformat("2026-10-08T10:00:00+07:00"),
        )
        assert registered.vehicle_id == "EV_VF5_PLUS"
        second_repository = DatabasePlannedArrivalRepository(
            engine, data.planned_arrivals.all()
        )
        assert second_repository.get(registered.arrival_id) == registered
        assert repository.cancel(registered.arrival_id).status == "cancelled"
        with pytest.raises(ValueError, match="cannot transition"):
            repository.mark_arrived(registered.arrival_id)

        arrived_request = request.model_copy(
            update={"arrival_id": "ARR_DATABASE_ARRIVED"}
        )
        repository.register(
            arrived_request,
            created_at=datetime.fromisoformat("2026-10-08T10:00:00+07:00"),
        )
        assert repository.mark_arrived("ARR_DATABASE_ARRIVED").status == "arrived"

        expiring_request = request.model_copy(
            update={"arrival_id": "ARR_DATABASE_EXPIRED"}
        )
        repository.register(
            expiring_request,
            created_at=datetime.fromisoformat("2026-10-08T10:00:00+07:00"),
        )
        expired = repository.expire(
            datetime.fromisoformat("2026-10-08T10:21:00+07:00")
        )
        assert "ARR_DATABASE_EXPIRED" in {
            arrival.arrival_id for arrival in expired
        }

        catalog_request = request.model_copy(
            update={
                "arrival_id": "ARR_DATABASE_CATALOG_REFS",
                "station_id": "CAND_2089F3C5E056",
                "vehicle_id": "VF8_ECO_VN",
            }
        )
        catalog_arrival = repository.register(
            catalog_request,
            created_at=datetime.fromisoformat("2026-10-08T10:00:00+07:00"),
        )
        assert catalog_arrival.station_id == "CAND_2089F3C5E056"
        assert catalog_arrival.vehicle_id == "VF8_ECO_VN"

        repository.reset()
        ids = {arrival.arrival_id for arrival in repository.all()}
        assert "ARR_DATABASE_TEST" not in ids
        assert "ARR_DEUTSCHES_001" in ids
    finally:
        repository.reset()
        engine.dispose()
