from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from backend.app.domain.realtime import (
    ChargingPortTelemetry,
    DESWaitRequest,
    DiscreteEventWaitSimulator,
    QueueVehicleTelemetry,
    RealtimeTelemetryStore,
    ResidualDurationService,
    StationTelemetrySnapshot,
    validate_observation_timestamp,
)
from backend.app.domain.runtime import RuntimeStateStore


def test_observation_timestamp_allows_small_clock_skew_but_rejects_future_poisoning() -> None:
    now = datetime(2026, 10, 9, 12, tzinfo=UTC)

    validate_observation_timestamp(
        now + timedelta(seconds=30), now=now, max_future_skew_s=60
    )
    with pytest.raises(ValueError, match="too far in the future"):
        validate_observation_timestamp(
            now + timedelta(seconds=61), now=now, max_future_skew_s=60
        )


def test_telemetry_snapshot_rejects_non_finite_numeric_values() -> None:
    with pytest.raises(ValidationError):
        StationTelemetrySnapshot(
            station_id="ST_TEST",
            observed_at="2026-10-09T12:00:00Z",
            data_source="station_api",
            avg_session_duration_min=float("inf"),
            ports=(
                ChargingPortTelemetry(
                    port_id="P1", connector_types=("CCS2",), state="available"
                ),
            ),
        )


def test_telemetry_snapshot_bounds_port_and_queue_cardinality() -> None:
    base = _snapshot()
    oversized_ports = {
        **base.model_dump(),
        "ports": (*base.ports, *(base.ports[0] for _ in range(999))),
    }
    with pytest.raises(ValidationError):
        StationTelemetrySnapshot.model_validate(oversized_ports)

    oversized = {
        **base.model_dump(),
        "queue": (*base.queue, *(base.queue[0] for _ in range(1999))),
    }
    with pytest.raises(ValidationError):
        StationTelemetrySnapshot.model_validate(oversized)


def _snapshot() -> StationTelemetrySnapshot:
    return StationTelemetrySnapshot(
        station_id="ST_EVO_DEUTSCHES_HAUS",
        observed_at="2026-09-26T10:00:00+07:00",
        data_source="simulated",
        ports=(
            ChargingPortTelemetry(
                port_id="A", connector_types=("CCS2",), state="charging",
                session_id="SESSION_A", reported_remaining_port_release_min=8,
            ),
            ChargingPortTelemetry(
                port_id="B", connector_types=("CCS2",), state="charging",
                session_id="SESSION_B", reported_remaining_port_release_min=25,
            ),
        ),
        queue=(
            QueueVehicleTelemetry(
                queue_id="Q1", queue_position=1,
                entered_queue_at="2026-09-26T09:55:00+07:00",
                compatible_connector_types=("CCS2",), expected_charge_duration_min=20,
            ),
            QueueVehicleTelemetry(
                queue_id="Q2", queue_position=2,
                entered_queue_at="2026-09-26T09:57:00+07:00",
                compatible_connector_types=("CCS2",), expected_charge_duration_min=15,
            ),
        ),
    )


def test_telemetry_retry_remains_idempotent_after_newer_snapshot() -> None:
    store = RealtimeTelemetryStore()
    original = _snapshot()
    newer = original.model_copy(update={"observed_at": original.observed_at + timedelta(minutes=5)})

    store.upsert(original)
    store.upsert(newer)

    assert store.upsert(original) == original
    assert store.get(original.station_id) == newer
    conflicting = original.model_copy(update={"queue": ()})
    with pytest.raises(ValueError, match="different telemetry snapshot"):
        store.upsert(conflicting)


def _request(connector_types: tuple[str, ...] = ("CCS2",)) -> DESWaitRequest:
    return DESWaitRequest(
        evaluation_at="2026-09-26T10:00:00+07:00",
        compatible_connector_types=connector_types,
    )


def test_discrete_event_simulation_uses_each_port_and_queue_duration() -> None:
    result = DiscreteEventWaitSimulator(ResidualDurationService()).estimate(
        _snapshot(), _request()
    )

    # A frees at +8 then serves Q1 until +28; B frees at +25 then serves Q2.
    assert result.estimated_wait_min == 28
    assert result.predicted_charge_start_at == datetime.fromisoformat(
        "2026-09-26T10:28:00+07:00"
    )
    assert "PROVIDER_REPORTED_PORT_RELEASE" in result.duration_sources
    assert "QUEUE_DURATION_ESTIMATE" in result.duration_sources
    assert "UNOBSERVED_ARRIVALS_EXCLUDED" in result.flags


def test_des_returns_no_wait_time_when_connector_is_not_supported() -> None:
    result = DiscreteEventWaitSimulator(ResidualDurationService()).estimate(
        _snapshot(), _request(("CHAdeMO",))
    )

    assert result.estimated_wait_min is None
    assert "REQUESTED_CONNECTOR_UNSUPPORTED" in result.flags


def test_des_fails_closed_when_live_session_duration_is_unknown() -> None:
    snapshot = _snapshot().model_copy(
        update={
            "ports": (
                ChargingPortTelemetry(
                    port_id="A", connector_types=("CCS2",), state="charging",
                    session_id="SESSION_A",
                ),
            )
        }
    )

    with pytest.raises(ValueError, match="no reported duration"):
        DiscreteEventWaitSimulator(ResidualDurationService()).estimate(snapshot, _request())


def test_unknown_port_state_is_preserved_and_disables_des_wait_estimate() -> None:
    snapshot = StationTelemetrySnapshot(
        station_id="ST_TEST_UNKNOWN",
        observed_at="2026-10-09T12:00:00Z",
        data_source="station_api",
        ports=(
            ChargingPortTelemetry(
                port_id="P1", connector_types=("CCS2",), state="available"
            ),
            ChargingPortTelemetry(
                port_id="P2", connector_types=("CCS2",), state="unknown"
            ),
            ChargingPortTelemetry(
                port_id="P3", connector_types=("CCS2",), state="out_of_service"
            ),
        ),
    )

    status = RuntimeStateStore._status_from_snapshot(snapshot, total_ports=3)
    result = DiscreteEventWaitSimulator(ResidualDurationService()).estimate(
        snapshot,
        DESWaitRequest(
            evaluation_at="2026-10-09T12:00:00Z",
            compatible_connector_types=("CCS2",),
        ),
    )

    assert status.operational_ports == 1
    assert status.offline_ports == 1
    assert status.unknown_ports == 1
    assert status.occupancy_ratio == 0
    assert result.estimated_wait_min is None
    assert result.operational_ports == 1
    assert result.unknown_ports == 1
    assert "PORT_STATE_UNKNOWN" in result.flags


def test_all_unknown_port_snapshot_is_not_reported_as_offline() -> None:
    snapshot = StationTelemetrySnapshot(
        station_id="ST_TEST_UNKNOWN",
        observed_at="2026-10-09T12:00:00Z",
        data_source="station_api",
        ports=(
            ChargingPortTelemetry(
                port_id="P1", connector_types=("CCS2",), state="unknown"
            ),
        ),
    )

    status = RuntimeStateStore._status_from_snapshot(snapshot, total_ports=1)

    assert status.operational_ports == 0
    assert status.offline_ports == 0
    assert status.unknown_ports == 1
    assert status.occupancy_ratio is None


def test_unreported_queue_is_not_treated_as_an_observed_empty_queue() -> None:
    snapshot = StationTelemetrySnapshot(
        station_id="ST_TEST_QUEUE_UNKNOWN",
        observed_at="2026-10-09T12:00:00Z",
        data_source="station_api",
        ports=(
            ChargingPortTelemetry(
                port_id="P1", connector_types=("CCS2",), state="available"
            ),
        ),
    )
    simulator = DiscreteEventWaitSimulator(ResidualDurationService())
    request = DESWaitRequest(
        evaluation_at="2026-10-09T12:00:00Z",
        compatible_connector_types=("CCS2",),
    )

    unreported = simulator.estimate(snapshot, request)
    observed_empty = simulator.estimate(snapshot.model_copy(update={"queue": ()}), request)

    assert unreported.confirmed_queue_length is None
    assert unreported.estimated_wait_min is None
    assert "QUEUE_STATE_UNKNOWN" in unreported.flags
    assert observed_empty.confirmed_queue_length == 0
    assert observed_empty.estimated_wait_min == 0
