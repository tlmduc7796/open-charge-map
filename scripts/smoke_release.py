#!/usr/bin/env python3
"""Run release acceptance probes against the deployed web/API stack."""

from __future__ import annotations

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def fetch_json(url: str) -> object:
    with urlopen(url, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")
        return json.loads(response.read())


def fetch_text(url: str) -> tuple[int, str]:
    with urlopen(url, timeout=10) as response:
        return response.status, response.read().decode("utf-8", errors="replace")


def check(name: str, passed: bool, detail: str) -> bool:
    print(f"[{ 'PASS' if passed else 'FAIL' }] {name}: {detail}")
    return passed


def is_synthetic_vehicle(item: dict[str, object]) -> bool:
    source = item.get("source", "")
    return bool(item.get("is_synthetic") or item.get("synthetic_fields")) or (
        isinstance(source, str) and "synthetic" in source.casefold()
    )


def station_catalog_check(
    stations: list[dict[str, object]], eligible_station_count: object
) -> tuple[bool, str]:
    """Check a sampled page against the whole-catalog count from readiness."""
    synthetic_stations = [
        item
        for item in stations
        if "synthetic"
        in item.get("properties", {}).get("source_provider", "").casefold()
        or item.get("properties", {}).get("synthetic_fields")
        or any(
            "synthetic" in connector.get("source", "").lower()
            for connector in item.get("properties", {}).get("connectors", [])
        )
    ]
    count_consistent = (
        type(eligible_station_count) is int
        and eligible_station_count >= len(stations)
        and eligible_station_count > 0
    )
    passed = bool(stations) and not synthetic_stations and count_consistent
    detail = (
        f"eligible={eligible_station_count}; sampled_page={len(stations)}; "
        f"synthetic_in_sample={len(synthetic_stations)}"
    )
    return passed, detail


def release_readiness_checks(readiness: dict[str, object]) -> list[tuple[str, bool, str]]:
    """Validate the detailed release gates, not only the top-level HTTP 200."""
    raw_checks = readiness.get("checks", {})
    checks = raw_checks if isinstance(raw_checks, dict) else {}
    database = checks.get("database", {})
    redis = checks.get("redis", {})
    identity = checks.get("identity", {})
    catalog = checks.get("catalog", {})
    station_status = checks.get("station_status", {})
    database = database if isinstance(database, dict) else {}
    redis = redis if isinstance(redis, dict) else {}
    identity = identity if isinstance(identity, dict) else {}
    catalog = catalog if isinstance(catalog, dict) else {}
    station_status = station_status if isinstance(station_status, dict) else {}

    eligible_stations = catalog.get("eligible_stations", 0)
    eligible_vehicles = catalog.get("eligible_vehicles", 0)
    source_count = catalog.get("source_timestamp_count", 0)
    fresh_source_count = catalog.get("fresh_source_timestamps", 0)
    status_fresh = station_status.get("fresh_stations", 0)
    status_operational = station_status.get("operational_stations", 0)
    status_eligible = station_status.get("eligible_stations", 0)
    signing_keys = identity.get("signing_keys", 0)
    database_revision = database.get("revision")

    return [
        (
            "database_ready",
            readiness.get("status") == "ready"
            and database.get("status") == "ok"
            and isinstance(database_revision, str)
            and bool(database_revision.strip()),
            f"status={database.get('status')} revision={database_revision or 'unknown'}",
        ),
        ("redis_ready", redis.get("status") == "ok", f"status={redis.get('status')}"),
        (
            "identity_ready",
            identity.get("status") == "ok" and type(signing_keys) is int and signing_keys > 0,
            f"status={identity.get('status')} signing_keys={signing_keys}",
        ),
        (
            "catalog_freshness",
            catalog.get("status") == "ok"
            and catalog.get("source_freshness_status") == "ok"
            and type(eligible_stations) is int
            and eligible_stations > 0
            and type(eligible_vehicles) is int
            and eligible_vehicles > 0
            and type(source_count) is int
            and source_count == eligible_stations
            and type(fresh_source_count) is int
            and fresh_source_count == eligible_stations
            and catalog.get("stale_source_timestamps") == 0
            and catalog.get("missing_source_timestamps") == 0
            and catalog.get("future_source_timestamps") == 0,
            "status="
            f"{catalog.get('status')} source_freshness={catalog.get('source_freshness_status')} "
            f"fresh={fresh_source_count}/{eligible_stations}",
        ),
        (
            "operational_station_status",
            station_status.get("status") == "ok"
            and type(status_fresh) is int
            and status_fresh > 0
            and type(status_operational) is int
            and status_operational > 0
            and type(status_eligible) is int
            and status_eligible == eligible_stations
            and status_operational <= status_fresh <= status_eligible,
            f"status={station_status.get('status')} fresh={status_fresh} "
            f"operational={status_operational}/{status_eligible}",
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web-url", default="http://127.0.0.1:8080")
    parser.add_argument("--api-url", default="http://127.0.0.1:8080/api")
    parser.add_argument(
        "--allow-persistence",
        action="store_true",
        help="verify service operation while explicitly allowing the ML persistence fallback",
    )
    args = parser.parse_args()
    web_url = args.web_url.rstrip("/")
    api_url = args.api_url.rstrip("/")
    results: list[bool] = []
    model_ready = False

    try:
        status, _ = fetch_text(f"{web_url}/health/live")
        results.append(check("web_liveness", status == 200, f"HTTP {status}"))
        frontend_status, body = fetch_text(web_url)
        results.append(
            check(
                "frontend_served",
                frontend_status == 200 and "<html" in body.lower(),
                f"HTTP {frontend_status}; HTML document returned",
            )
        )

        readiness = fetch_json(f"{api_url}/health/ready")
        if not isinstance(readiness, dict):
            raise RuntimeError("readiness response is not an object")
        results.append(
            check(
                "release_mode",
                readiness.get("demo_mode") is False,
                f"demo_mode={readiness.get('demo_mode')}",
            )
        )
        results.extend(
            check(name, passed, detail)
            for name, passed, detail in release_readiness_checks(readiness)
        )

        stations = fetch_json(f"{api_url}/stations")
        if not isinstance(stations, list):
            raise RuntimeError("station catalog response is not a list")
        readiness_checks = readiness.get("checks", {})
        catalog_check_data = (
            readiness_checks.get("catalog", {})
            if isinstance(readiness_checks, dict)
            else {}
        )
        eligible_station_count = (
            catalog_check_data.get("eligible_stations")
            if isinstance(catalog_check_data, dict)
            else None
        )
        catalog_passed, catalog_detail = station_catalog_check(
            stations, eligible_station_count
        )
        results.append(
            check("station_catalog", catalog_passed, catalog_detail)
        )
        if stations:
            station_id = stations[0].get("properties", {}).get("station_id")
            station_status = fetch_json(f"{api_url}/stations/{station_id}/status")
            if not isinstance(station_status, dict):
                raise RuntimeError("station status response is not an object")
            unverified_source = station_status.get("data_source") in {
                "synthetic",
                "unknown",
                "runtime",
            }
            results.append(
                check(
                    "station_status_provenance",
                    station_status.get("station_id") == station_id
                    and (not unverified_source or station_status.get("is_stale") is True),
                    "source="
                    f"{station_status.get('data_source')} "
                    f"is_stale={station_status.get('is_stale')}",
                )
            )

        vehicles = fetch_json(f"{api_url}/vehicles")
        if not isinstance(vehicles, list):
            raise RuntimeError("vehicle catalog response is not a list")
        synthetic_vehicles = [item for item in vehicles if is_synthetic_vehicle(item)]
        results.append(
            check(
                "vehicle_catalog",
                bool(vehicles) and not synthetic_vehicles,
                f"{len(vehicles)} vehicles; {len(synthetic_vehicles)} synthetic records",
            )
        )

        model = fetch_json(f"{api_url}/model/status")
        if not isinstance(model, dict):
            raise RuntimeError("model status response is not an object")
        model_ready = (
            model.get("release_ready") is True and model.get("prediction_source") == "model"
        )
        model_pass = model_ready or (
            args.allow_persistence and model.get("prediction_source") == "persistence"
        )
        results.append(
            check(
                "occupancy_model",
                model_pass,
                "source="
                f"{model.get('prediction_source')} "
                f"release_ready={model.get('release_ready')}",
            )
        )
    except (
        HTTPError,
        URLError,
        TimeoutError,
        RuntimeError,
        json.JSONDecodeError,
        AttributeError,
    ) as exc:
        results.append(check("deployment_probe", False, str(exc)))

    passed = all(results)
    if passed and model_ready:
        print("\nRELEASE PASS")
    elif passed:
        print("\nSERVICE SMOKE PASS (persistence fallback explicitly allowed)")
    else:
        print("\nRELEASE FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
