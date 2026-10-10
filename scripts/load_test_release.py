#!/usr/bin/env python3
"""Run a bounded read or journey-write concurrency probe against release staging."""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

MAX_JOURNEY_LOAD_REQUESTS = 100


def fetch_json(
    url: str,
    timeout_s: float,
    *,
    method: str = "GET",
    payload: dict | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, object, float]:
    started = time.perf_counter()
    request_headers = {"Accept": "application/json", **(headers or {})}
    body = None
    if payload is not None:
        request_headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    try:
        with urlopen(
            Request(url, data=body, headers=request_headers, method=method),
            timeout=timeout_s,
        ) as response:
            status = response.status
            payload = json.loads(response.read()) if status == 200 else None
    except HTTPError as error:
        status, payload = error.code, None
    except (URLError, TimeoutError, OSError, json.JSONDecodeError):
        status, payload = 0, None
    return status, payload, time.perf_counter() - started


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8080/api")
    parser.add_argument("--requests", type=int, required=True, help="Total requests (1-100000)")
    parser.add_argument("--concurrency", type=int, required=True, help="Workers (1-200)")
    parser.add_argument(
        "--max-p95-ms", type=float, required=True, help="Approved staging p95 limit"
    )
    parser.add_argument(
        "--max-error-rate", type=float, required=True, help="Approved error-rate limit (0-1)"
    )
    parser.add_argument("--timeout-s", type=float, default=10)
    parser.add_argument(
        "--journey-request-file",
        type=Path,
        help="dynamic JourneyRecommendationRequest JSON for an authenticated staging probe",
    )
    parser.add_argument(
        "--confirm-journey-writes",
        action="store_true",
        help="confirm that each recommendation probe creates a persisted staging journey",
    )
    parser.add_argument(
        "--confirm-staging",
        action="store_true",
        help="Confirm this targets an isolated staging deployment, not production",
    )
    args = parser.parse_args()
    if not args.confirm_staging:
        parser.error("--confirm-staging is required; this command generates concurrent API traffic")
    if not 1 <= args.requests <= 100_000:
        parser.error("--requests must be between 1 and 100000")
    if not 1 <= args.concurrency <= 200:
        parser.error("--concurrency must be between 1 and 200")
    if args.max_p95_ms <= 0 or not math.isfinite(args.max_p95_ms):
        parser.error("--max-p95-ms must be a positive finite value")
    if not 0 <= args.max_error_rate <= 1 or not math.isfinite(args.max_error_rate):
        parser.error("--max-error-rate must be between 0 and 1")
    if args.timeout_s <= 0 or not math.isfinite(args.timeout_s):
        parser.error("--timeout-s must be a positive finite value")
    if bool(args.journey_request_file) != args.confirm_journey_writes:
        parser.error(
            "--journey-request-file and --confirm-journey-writes must be supplied together"
        )
    journey_payload = None
    bearer_token = None
    if args.journey_request_file is not None:
        if args.requests > MAX_JOURNEY_LOAD_REQUESTS:
            parser.error(
                f"journey probes are limited to {MAX_JOURNEY_LOAD_REQUESTS} persisted requests"
            )
        if args.concurrency > 50:
            parser.error("journey probes are limited to 50 concurrent requests")
        bearer_token = os.environ.get("SMART_EV_STAGING_BEARER_TOKEN", "").strip()
        if not bearer_token:
            parser.error("SMART_EV_STAGING_BEARER_TOKEN must contain a staging access token")
        try:
            target = urlsplit(args.api_url)
            _ = target.port
        except ValueError as error:
            parser.error(f"--api-url is invalid: {error}")
        local_http_hosts = {"localhost", "127.0.0.1", "::1"}
        if (
            not target.hostname
            or target.username
            or target.password
            or target.query
            or target.fragment
            or (
                target.scheme != "https"
                and not (target.scheme == "http" and target.hostname in local_http_hosts)
            )
        ):
            parser.error(
                "journey probes require an HTTPS --api-url; HTTP is allowed only for loopback"
            )
        try:
            journey_payload = json.loads(
                args.journey_request_file.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as error:
            parser.error(f"cannot read journey request JSON: {error}")
        if (
            not isinstance(journey_payload, dict)
            or journey_payload.get("scenario_id") is not None
            or not all(
                journey_payload.get(name) is not None
                for name in ("vehicle_id", "initial_soc", "origin", "destination")
            )
        ):
            parser.error(
                "journey request must be dynamic and include vehicle_id, initial_soc, "
                "origin, and destination"
            )

    api_url = args.api_url.rstrip("/")
    ready_status, ready_payload, _ = fetch_json(f"{api_url}/health/ready", args.timeout_s)
    if (
        ready_status != 200
        or not isinstance(ready_payload, dict)
        or ready_payload.get("demo_mode") is not False
    ):
        print("LOAD TEST ABORTED: target is not a ready release deployment", file=sys.stderr)
        return 2
    stations_status, stations_payload, _ = fetch_json(f"{api_url}/stations", args.timeout_s)
    if stations_status != 200 or not isinstance(stations_payload, list) or not stations_payload:
        print("LOAD TEST ABORTED: target has no readable station catalog", file=sys.stderr)
        return 2
    station_ids = [
        item.get("properties", {}).get("station_id")
        for item in stations_payload
        if isinstance(item, dict) and item.get("properties", {}).get("station_id")
    ]
    if not station_ids:
        print("LOAD TEST ABORTED: station catalog has no station IDs", file=sys.stderr)
        return 2
    status_station_ids = []
    for station_id in station_ids[:25]:
        status, _, _ = fetch_json(
            f"{api_url}/stations/{station_id}/status", args.timeout_s
        )
        if status == 200:
            status_station_ids.append(station_id)
    if not status_station_ids:
        print("LOAD TEST ABORTED: no station status endpoint is available", file=sys.stderr)
        return 2

    routes = ["/stations", "/vehicles", "/model/status"]
    routes.extend(f"/stations/{station_id}/status" for station_id in status_station_ids)
    randomizer = random.Random(42)
    results = []
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        remaining = args.requests
        while remaining:
            batch_size = min(remaining, args.concurrency * 10)
            futures = [
                executor.submit(
                    fetch_json,
                    f"{api_url}/journey/recommend",
                    args.timeout_s,
                    method="POST",
                    payload=journey_payload,
                    headers={
                        "Authorization": f"Bearer {bearer_token}",
                        "Idempotency-Key": f"release-load-{uuid4().hex}",
                    },
                )
                if journey_payload is not None
                else executor.submit(
                    fetch_json,
                    f"{api_url}{randomizer.choice(routes)}",
                    args.timeout_s,
                )
                for _ in range(batch_size)
            ]
            for future in as_completed(futures):
                results.append(future.result())
            remaining -= batch_size
    elapsed = time.perf_counter() - started

    statuses = Counter(status for status, _, _ in results)
    latencies_ms = [duration * 1000 for _, _, duration in results]
    failed = sum(count for status, count in statuses.items() if status != 200)
    error_rate = failed / len(results)
    summary = {
        "requests": len(results),
        "workload": (
            "journey_recommendation" if journey_payload is not None else "read_only_get"
        ),
        "persisted_journeys_created": len(results) if journey_payload is not None else 0,
        "concurrency": args.concurrency,
        "elapsed_s": round(elapsed, 3),
        "throughput_rps": round(len(results) / elapsed, 2) if elapsed else 0,
        "status_counts": dict(sorted(statuses.items())),
        "error_rate": round(error_rate, 5),
        "latency_ms": {
            "p50": round(percentile(latencies_ms, 0.50), 2),
            "p95": round(percentile(latencies_ms, 0.95), 2),
            "p99": round(percentile(latencies_ms, 0.99), 2),
            "max": round(max(latencies_ms, default=0), 2),
        },
        "limits": {
            "max_p95_ms": args.max_p95_ms,
            "max_error_rate": args.max_error_rate,
        },
    }
    p95_pass = percentile(latencies_ms, 0.95) <= args.max_p95_ms
    error_pass = error_rate <= args.max_error_rate
    print(json.dumps(summary, indent=2, sort_keys=True))
    print("LOAD TEST PASS" if p95_pass and error_pass else "LOAD TEST FAIL")
    return 0 if p95_pass and error_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
