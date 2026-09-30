from datetime import datetime

import pytest

from backend.app.domain.realtime import (
    ChargingPortTelemetry,
    DESWaitRequest,
    DiscreteEventWaitSimulator,
    QueueVehicleTelemetry,
    ResidualDurationService,
    StationTelemetrySnapshot,
)


def _snapshot() -> StationTelemetrySnapshot:
    return StationTelemetrySnapshot(
        station_id="ST_EVO_DEUTSCHES_HAUS",
        observed_at="2026-09-26T10:00:00+07:00",
        data_source="simulated",
        ports=(
            ChargingPortTelemetry(
                port_id="A", connector_types=("CCS2",), state="charging",
                session_id="SESSION_A", reported_remaining_charge_min=8,
            ),
            ChargingPortTelemetry(
                port_id="B", connector_types=("CCS2",), state="charging",
                session_id="SESSION_B", reported_remaining_charge_min=25,
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
    assert "PROVIDER_REPORTED_DURATION" in result.duration_sources
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
