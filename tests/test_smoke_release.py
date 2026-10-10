from scripts.smoke_release import (
    is_synthetic_vehicle,
    release_readiness_checks,
    station_catalog_check,
)


def test_smoke_treats_vehicle_with_synthetic_fields_as_synthetic() -> None:
    assert is_synthetic_vehicle({"is_synthetic": False, "synthetic_fields": ["max_dc_power_kw"]})
    assert not is_synthetic_vehicle({"is_synthetic": False, "synthetic_fields": []})
    assert is_synthetic_vehicle(
        {"is_synthetic": False, "synthetic_fields": [], "source": "synthetic catalog"}
    )


def test_station_catalog_smoke_distinguishes_sample_page_from_total_count() -> None:
    stations = [
        {"properties": {"station_id": "ST-1", "synthetic_fields": [], "connectors": []}},
        {"properties": {"station_id": "ST-2", "synthetic_fields": [], "connectors": []}},
    ]

    passed, detail = station_catalog_check(stations, 250)

    assert passed
    assert "eligible=250" in detail
    assert "sampled_page=2" in detail


def test_station_catalog_smoke_rejects_page_larger_than_readiness_count() -> None:
    stations = [
        {"properties": {"station_id": "ST-1", "synthetic_fields": [], "connectors": []}},
        {"properties": {"station_id": "ST-2", "synthetic_fields": [], "connectors": []}},
    ]

    passed, _detail = station_catalog_check(stations, 1)

    assert not passed


def test_station_catalog_smoke_rejects_synthetic_provider_even_without_field_flags() -> None:
    stations = [
        {
            "properties": {
                "station_id": "ST-SYNTHETIC",
                "source_provider": "Synthetic Import Feed",
                "synthetic_fields": [],
                "connectors": [],
            }
        }
    ]

    passed, detail = station_catalog_check(stations, 1)

    assert not passed
    assert "synthetic_in_sample=1" in detail


def _ready_payload() -> dict[str, object]:
    return {
        "status": "ready",
        "demo_mode": False,
        "checks": {
            "database": {"status": "ok", "revision": "0016_release"},
            "redis": {"status": "ok"},
            "identity": {"status": "ok", "signing_keys": 2},
            "catalog": {
                "status": "ok",
                "eligible_stations": 3,
                "eligible_vehicles": 2,
                "source_freshness_status": "ok",
                "source_timestamp_count": 3,
                "fresh_source_timestamps": 3,
                "stale_source_timestamps": 0,
                "missing_source_timestamps": 0,
                "future_source_timestamps": 0,
            },
            "station_status": {
                "status": "ok",
                "fresh_stations": 2,
                "operational_stations": 2,
                "eligible_stations": 3,
            },
        },
    }


def test_release_smoke_checks_all_detailed_operational_gates() -> None:
    results = release_readiness_checks(_ready_payload())

    assert [name for name, _passed, _detail in results] == [
        "database_ready",
        "redis_ready",
        "identity_ready",
        "catalog_freshness",
        "operational_station_status",
    ]
    assert all(passed for _name, passed, _detail in results)


def test_release_smoke_rejects_stale_catalog_even_if_top_level_says_ready() -> None:
    readiness = _ready_payload()
    checks = readiness["checks"]
    assert isinstance(checks, dict)
    catalog = checks["catalog"]
    assert isinstance(catalog, dict)
    catalog.update(
        {
            "source_freshness_status": "unavailable",
            "fresh_source_timestamps": 2,
            "stale_source_timestamps": 1,
        }
    )

    results = dict(
        (name, passed) for name, passed, _detail in release_readiness_checks(readiness)
    )

    assert not results["catalog_freshness"]
    assert all(passed for name, passed in results.items() if name != "catalog_freshness")


def test_release_smoke_rejects_missing_identity_or_operational_status() -> None:
    readiness = _ready_payload()
    checks = readiness["checks"]
    assert isinstance(checks, dict)
    checks["identity"] = {"status": "unavailable", "signing_keys": 0}
    checks["station_status"] = {
        "status": "unavailable",
        "fresh_stations": 1,
        "operational_stations": 0,
        "eligible_stations": 3,
    }

    results = dict(
        (name, passed) for name, passed, _detail in release_readiness_checks(readiness)
    )

    assert not results["identity_ready"]
    assert not results["operational_station_status"]
