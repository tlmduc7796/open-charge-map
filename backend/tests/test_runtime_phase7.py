from datetime import UTC, datetime, timedelta

import pytest

from backend.app.config import load_settings
from backend.app.domain.models import PlannedArrival, PortRuntimeStatus
from backend.app.domain.phase7_models import PlannedArrivalCreateRequest
from backend.app.domain.realtime import (
    ChargingPortTelemetry,
    RealtimeTelemetryStore,
    StationTelemetrySnapshot,
)
from backend.app.domain.repositories import StationStatusRepository, load_domain_data
from backend.app.domain.runtime import (
    PlannedArrivalStore,
    RuntimeStateStore,
    planned_arrival_matches_request,
)


def test_planned_arrival_retry_matches_database_numeric_precision() -> None:
    now = datetime.now(UTC)
    request = PlannedArrivalCreateRequest(
        arrival_id="ARR_PRECISION_TEST",
        station_id="ST_TEST",
        vehicle_id="EV_TEST",
        eta_at=now + timedelta(minutes=10),
        eta_window_start=now + timedelta(minutes=5),
        eta_window_end=now + timedelta(minutes=15),
        expected_energy_kwh=12.34567,
        expected_charge_duration_min=20.12345,
        arrival_probability=0.8123456,
        expires_at=now + timedelta(minutes=20),
    )
    persisted = PlannedArrival.model_validate(
        {
            **request.model_dump(),
            "created_at": now,
            "status": "planned",
            "data_source": "runtime",
        }
    ).model_copy(
        update={
            "expected_energy_kwh": 12.346,
            "expected_charge_duration_min": 20.123,
            "arrival_probability": 0.812346,
        }
    )

    assert planned_arrival_matches_request(persisted, request)
    assert not planned_arrival_matches_request(
        persisted,
        request.model_copy(update={"expected_energy_kwh": 12.347}),
    )


def test_event_engine_updates_runtime_without_mutating_static_data() -> None:
    data = load_domain_data(load_settings().data_dir)
    runtime = RuntimeStateStore(data.station_statuses, data.demo_events)
    event = next(
        item for item in data.demo_events.all()
        if item.effects.offline_ports_delta > 0
    )
    static_status = data.station_statuses.get(event.station_id)

    updated = runtime.apply(event.event_id)

    assert updated.offline_ports == min(
        static_status.total_ports,
        static_status.offline_ports + event.effects.offline_ports_delta,
    )
    assert static_status.offline_ports == 0
    assert runtime.active_event_ids() == (event.event_id,)

    runtime.reset()
    reset_status = runtime.get(event.station_id)
    assert reset_status.model_copy(update={"is_stale": False}) == static_status
    assert runtime.active_event_ids() == ()


def test_all_event_effect_types_are_capacity_safe() -> None:
    data = load_domain_data(load_settings().data_dir)
    runtime = RuntimeStateStore(data.station_statuses, data.demo_events)

    for event in data.demo_events.all():
        status = runtime.apply(event.event_id)
        assert status.operational_ports + status.offline_ports == status.total_ports
        assert status.occupied_ports + status.available_ports == status.operational_ports


def test_simulated_persisted_telemetry_is_stale_only_in_release_runtime() -> None:
    data = load_domain_data(load_settings().data_dir)
    station = data.stations.get("ST_EVO_LAVIDA_Q7")
    connector_type = station.properties.connectors[0].type
    snapshot = StationTelemetrySnapshot(
        station_id=station.station_id,
        observed_at=datetime.now(UTC),
        ports=tuple(
            ChargingPortTelemetry(
                port_id=f"SIM_PORT_{index}",
                connector_types=(connector_type,),
                state="available",
            )
            for index in range(station.properties.total_ports)
        ),
        data_source="simulated",
    )
    telemetry = RealtimeTelemetryStore()
    telemetry.upsert(snapshot)
    release_runtime = RuntimeStateStore(
        data.station_statuses,
        data.demo_events,
        telemetry=telemetry,
        enforce_freshness=True,
    )
    demo_runtime = RuntimeStateStore(
        data.station_statuses,
        data.demo_events,
        telemetry=telemetry,
        enforce_freshness=False,
    )

    release_status = release_runtime.get(station.station_id)
    assert release_status.is_stale is True
    assert len(release_status.port_runtime_statuses) == station.properties.total_ports
    assert "port_runtime_statuses" not in release_status.model_dump()
    assert release_runtime.get_many((station.station_id,))[0].is_stale is True
    assert demo_runtime.get(station.station_id).is_stale is False


def test_memory_telemetry_retries_are_idempotent_but_conflicts_are_rejected() -> None:
    observed_at = datetime.now(UTC)
    snapshot = StationTelemetrySnapshot(
        station_id="ST_TEST",
        observed_at=observed_at,
        ports=(
            ChargingPortTelemetry(
                port_id="PORT_1",
                connector_types=("CCS2",),
                state="available",
            ),
        ),
        queue=(),
        data_source="station_api",
    )
    store = RealtimeTelemetryStore()

    assert store.upsert(snapshot) == snapshot
    assert store.upsert(snapshot) == snapshot

    conflicting_retry = snapshot.model_copy(
        update={
            "ports": (
                ChargingPortTelemetry(
                    port_id="PORT_1",
                    connector_types=("CCS2",),
                    state="offline",
                ),
            )
        }
    )
    with pytest.raises(ValueError, match="different telemetry snapshot"):
        store.upsert(conflicting_retry)
    assert store.get("ST_TEST") == snapshot


def test_expired_per_port_statuses_become_unknown_individually() -> None:
    data = load_domain_data(load_settings().data_dir)
    now = datetime.now(UTC)
    base = data.station_statuses.get("ST_EVO_AUDI_HCM")
    status = base.model_copy(
        update={
            "timestamp": now,
            "data_source": "station_api",
            "port_runtime_statuses": (
                PortRuntimeStatus(
                    connector_types=("CCS2",),
                    state="charging",
                    observed_at=now - timedelta(minutes=10),
                ),
                PortRuntimeStatus(
                    connector_types=("CCS2",),
                    state="out_of_service",
                    observed_at=now,
                ),
                PortRuntimeStatus(
                    connector_types=("Type2",),
                    state="available",
                    observed_at=now,
                ),
                PortRuntimeStatus(
                    connector_types=("Type2",),
                    state="available",
                    observed_at=now,
                ),
            ),
        }
    )
    runtime = RuntimeStateStore(
        StationStatusRepository((status,)),
        data.demo_events,
        telemetry_max_age_s=300,
    )

    current = runtime.get(status.station_id)

    assert current.operational_ports == 2
    assert current.occupied_ports == 0
    assert current.available_ports == 2
    assert current.offline_ports == 1
    assert current.unknown_ports == 1
    assert current.port_runtime_statuses is not None
    assert current.port_runtime_statuses[0].state == "unknown"


def test_planned_arrival_register_cancel_arrive_expire_and_reset() -> None:
    data = load_domain_data(load_settings().data_dir)
    store = PlannedArrivalStore(data.planned_arrivals)
    request = PlannedArrivalCreateRequest(
        arrival_id="ARR_PHASE7_TEST",
        station_id="ST_EVO_LAVIDA_Q7",
        vehicle_id="EV_VF5_PLUS",
        eta_at="2026-09-26T10:10:00+07:00",
        eta_window_start="2026-09-26T10:05:00+07:00",
        eta_window_end="2026-09-26T10:15:00+07:00",
        expected_energy_kwh=12,
        expected_charge_duration_min=20,
        arrival_probability=0.8,
        expires_at="2026-09-26T10:20:00+07:00",
        route_id="ROUTE_VIA_LAVIDA",
    )

    registered = store.register(
        request, created_at=datetime.fromisoformat("2026-09-26T10:00:00+07:00")
    )
    assert registered.status == "planned"
    assert store.cancel(registered.arrival_id).status == "cancelled"

    arrived_request = request.model_copy(update={"arrival_id": "ARR_PHASE7_ARRIVED"})
    arrived = store.register(
        arrived_request,
        created_at=datetime.fromisoformat("2026-09-26T10:00:00+07:00"),
    )
    assert store.mark_arrived(arrived.arrival_id).status == "arrived"

    expiring_request = request.model_copy(update={"arrival_id": "ARR_PHASE7_EXPIRE"})
    expiring = store.register(
        expiring_request,
        created_at=datetime.fromisoformat("2026-09-26T10:00:00+07:00"),
    )
    expired = store.expire(datetime.fromisoformat("2026-09-26T10:21:00+07:00"))
    assert expiring.arrival_id in {arrival.arrival_id for arrival in expired}

    store.reset()
    assert "ARR_PHASE7_TEST" not in {arrival.arrival_id for arrival in store.all()}


def test_active_planned_arrival_can_be_restored_by_journey() -> None:
    data = load_domain_data(load_settings().data_dir)
    store = PlannedArrivalStore(data.planned_arrivals)
    now = datetime.now(UTC)
    request = PlannedArrivalCreateRequest(
        arrival_id="ARR_RESTORE_TEST",
        journey_id="a9d75b53-e852-4dda-aabe-0bf7b1b15008",
        station_id="ST_EVO_LAVIDA_Q7",
        vehicle_id="EV_VF5_PLUS",
        eta_at=now + timedelta(minutes=10),
        eta_window_start=now + timedelta(minutes=5),
        eta_window_end=now + timedelta(minutes=15),
        expected_energy_kwh=10,
        expected_charge_duration_min=20,
        arrival_probability=0.8,
        expires_at=now + timedelta(minutes=30),
    )
    arrival = store.register(request, created_at=now)

    assert store.active_for_journey(str(request.journey_id)) == arrival
    store.cancel(arrival.arrival_id)
    assert store.active_for_journey(str(request.journey_id)) is None
