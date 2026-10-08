from datetime import datetime

from backend.app.config import load_settings
from backend.app.domain.phase7_models import PlannedArrivalCreateRequest
from backend.app.domain.repositories import load_domain_data
from backend.app.domain.runtime import PlannedArrivalStore, RuntimeStateStore


def test_event_engine_updates_runtime_without_mutating_static_data() -> None:
    data = load_domain_data(load_settings().data_dir)
    runtime = RuntimeStateStore(data.station_statuses, data.demo_events)
    static_status = data.station_statuses.get("ST_VF_LA_VELA")

    updated = runtime.apply("EVT_OUTAGE_LA_VELA")

    assert updated.operational_ports == 0
    assert updated.offline_ports == 2
    assert static_status.operational_ports == 2
    assert static_status.offline_ports == 0
    assert runtime.active_event_ids() == ("EVT_OUTAGE_LA_VELA",)

    runtime.reset()
    assert runtime.get("ST_VF_LA_VELA") == static_status
    assert runtime.active_event_ids() == ()


def test_all_event_effect_types_are_capacity_safe() -> None:
    data = load_domain_data(load_settings().data_dir)
    runtime = RuntimeStateStore(data.station_statuses, data.demo_events)

    for event in data.demo_events.all():
        status = runtime.apply(event.event_id)
        assert status.operational_ports + status.offline_ports == status.total_ports
        assert status.occupied_ports + status.available_ports == status.operational_ports


def test_planned_arrival_register_cancel_arrive_expire_and_reset() -> None:
    data = load_domain_data(load_settings().data_dir)
    store = PlannedArrivalStore(data.planned_arrivals)
    assert {
        arrival.arrival_id
        for arrival in store.active_for_stations(("ST_EVO_DEUTSCHES_HAUS",))
    } == {"ARR_DEUTSCHES_001", "ARR_DEUTSCHES_002"}
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
