from __future__ import annotations

from backend.app.domain.models import QueueAssumptions, StationArrivalRate
from backend.app.domain.repositories import QueueAssumptionsRepository
from backend.app.domain.wait_estimation import WaitEstimator
from scripts.simulate_hcmc_network_load import (
    DEFAULT_ASSUMPTIONS,
    DEFAULT_STATIONS,
    DEFAULT_STATUSES,
    Arrival,
    StationInput,
    load_stations,
    run_study,
    simulate_policy,
)


def test_load_aware_policy_spreads_synthetic_herd_and_reduces_wait() -> None:
    stations = [
        StationInput("A", 0.0, 0.0, 1, 0, 0, 60.0, 0.0),
        StationInput("B", 0.1, 0.0, 1, 0, 0, 60.0, 0.0),
    ]
    arrivals = [
        Arrival(
            minute=0.0,
            origin_lon=0.0,
            origin_lat=0.0,
            baseline_station_id=None,
            service_by_station=(("A", 60.0), ("B", 60.0)),
        )
        for _ in range(10)
    ]
    wait_estimator = WaitEstimator(
        QueueAssumptionsRepository(
            QueueAssumptions(
                planned_arrival_window_min=15,
                station_rates=(
                    StationArrivalRate(station_id="A", baseline_arrival_rate_per_hour=0),
                    StationArrivalRate(station_id="B", baseline_arrival_rate_per_hour=0),
                ),
                scenario_overrides=(),
                data_source="synthetic",
            )
        )
    )

    nearest = simulate_policy(
        stations,
        arrivals,
        policy="nearest",
        seed=42,
        duration_hours=4,
        wait_estimator=wait_estimator,
    )
    load_aware = simulate_policy(
        stations,
        arrivals,
        policy="load_aware",
        seed=42,
        duration_hours=4,
        wait_estimator=wait_estimator,
    )

    assert nearest["network_assignments_by_station"] == {"A": 10, "B": 0}
    assert load_aware["network_assignments_by_station"]["B"] > 0
    assert load_aware["mean_network_wait_min"] < nearest["mean_network_wait_min"]


def test_default_inputs_are_provenance_checked_demo_records() -> None:
    stations, hashes = load_stations(
        DEFAULT_STATIONS, DEFAULT_STATUSES, DEFAULT_ASSUMPTIONS
    )

    assert len(stations) >= 10
    assert all(item.station_id.startswith(("ST_EVO_", "ST_VF_")) for item in stations)
    assert set(hashes) == {
        "station_catalog_sha256",
        "station_status_sha256",
        "arrival_assumptions_sha256",
    }


def test_study_is_reproducible_and_never_release_evidence() -> None:
    stations, _ = load_stations(
        DEFAULT_STATIONS, DEFAULT_STATUSES, DEFAULT_ASSUMPTIONS
    )
    estimator = WaitEstimator(
        QueueAssumptionsRepository.from_file(DEFAULT_ASSUMPTIONS)
    )
    parameters = {
        "duration_hours": 2.0,
        "network_arrivals_per_hour": 2.0,
        "seed": 7,
        "capacity_wait_multiplier": 1.0,
        "wait_estimator": estimator,
    }

    first = run_study(stations, **parameters)
    replay = run_study(stations, **parameters)

    assert first == replay
    assert first["data_source"] == "synthetic"
    assert first["release_evidence"] is False
    assert first["training_data"] is False
    assert first["methodology"]["wait_estimator"].startswith("backend WaitEstimator")
    assert len(first["results"]) == 2
