from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from data_platform.runtime_seed import (
    build_runtime_seed,
    load_runtime_seed,
    synthetic_arrival_rate,
)

DATA = Path(__file__).resolve().parents[1] / "data"


def _fixtures() -> tuple[list[dict], dict]:
    planned = json.loads(
        (DATA / "runtime/planned_arrivals.json").read_text(encoding="utf-8")
    )
    queue = json.loads(
        (DATA / "demo/queue_assumptions.json").read_text(encoding="utf-8")
    )
    return planned, queue


def test_load_runtime_seed_matches_repository_fixtures() -> None:
    bundle = load_runtime_seed(
        DATA / "runtime/planned_arrivals.json",
        DATA / "demo/queue_assumptions.json",
    )

    assert len(bundle.planned_arrivals) == 4
    assert len(bundle.station_rates) == 16
    assert bundle.planned_arrival_window_min == 15
    assert {arrival["status"] for arrival in bundle.planned_arrivals} == {
        "planned",
        "cancelled",
        "expired",
    }


def test_runtime_seed_rejects_duplicate_arrival_id() -> None:
    planned, queue = _fixtures()
    duplicate = deepcopy(planned[0])
    planned.append(duplicate)

    with pytest.raises(ValueError, match="duplicate planned arrival"):
        build_runtime_seed(planned, queue)


def test_runtime_seed_requires_timezone_aware_timestamps() -> None:
    planned, queue = _fixtures()
    planned[0]["eta_at"] = "2026-09-25T18:18:00"

    with pytest.raises(ValueError, match="must include a timezone"):
        build_runtime_seed(planned, queue)


def test_runtime_seed_rejects_unknown_source_and_invalid_probability() -> None:
    planned, queue = _fixtures()
    planned[0]["data_source"] = "manual"
    with pytest.raises(ValueError, match="unsupported planned arrival data_source"):
        build_runtime_seed(planned, queue)

    planned, queue = _fixtures()
    planned[0]["arrival_probability"] = 1.1
    with pytest.raises(ValueError, match="must be at most 1"):
        build_runtime_seed(planned, queue)


def test_synthetic_arrival_rate_is_reproducible_and_bounded() -> None:
    first = synthetic_arrival_rate("CAND_ABC")

    assert first == synthetic_arrival_rate("CAND_ABC")
    assert 0.3 <= first <= 1.5
