import math
from datetime import UTC, datetime, timedelta

import pytest

from backend.app.domain.far_horizon import blend_with_profile, smooth_profile
from backend.app.occupancy_history_repository import build_window
from backend.app.profile_repository import profile_cell

T0 = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)  # a Monday


def test_blend_at_the_anchor_returns_the_t30_prediction() -> None:
    assert blend_with_profile(0.9, 0.5, 0.5, 30) == pytest.approx(0.9)


def test_blend_decays_towards_the_profile() -> None:
    values = [blend_with_profile(0.9, 0.5, 0.3, h, tau_min=30) for h in (30, 40, 50, 60)]

    # Profile at the target is 0.3; the 0.4 deviation shrinks as exp(-(h-30)/30).
    assert values[0] == pytest.approx(0.3 + 0.4)
    assert values == sorted(values, reverse=True)
    assert values[-1] == pytest.approx(0.3 + 0.4 * math.exp(-1))
    assert all(value > 0.3 for value in values)


def test_blend_is_clipped_to_a_ratio() -> None:
    assert blend_with_profile(1.0, 0.0, 0.9, 30) == 1.0
    assert blend_with_profile(0.0, 1.0, 0.1, 30) == 0.0


def test_blend_rejects_horizons_inside_the_model_range() -> None:
    with pytest.raises(ValueError):
        blend_with_profile(0.5, 0.5, 0.5, 25)


def test_smoothing_pulls_small_samples_to_the_station_mean() -> None:
    assert smooth_profile(1.0, 1, 0.4, strength=2) == pytest.approx((1.0 + 0.8) / 3)
    assert smooth_profile(1.0, 1000, 0.4, strength=2) == pytest.approx(1.0, abs=1e-2)
    assert smooth_profile(1.0, 0, 0.4) == 0.4


def test_profile_cell_uses_local_time_and_monday_zero() -> None:
    # 2026-09-28 17:05 UTC is Tuesday 00:05 in Ho Chi Minh City.
    day, step = profile_cell(datetime(2026, 9, 28, 17, 5, tzinfo=UTC))

    assert (day, step) == (1, 1)


def _rows(count: int = 12, *, gap_at: int | None = None, operational: int = 4):
    rows = []
    for index in range(count):
        minutes = 5 * index + (5 if gap_at is not None and index >= gap_at else 0)
        rows.append(
            {
                "bucket_at": T0 - timedelta(minutes=minutes),
                "total_ports": 4,
                "operational_ports": operational,
                "occupied_ports": index % 3,
            }
        )
    return rows


def test_window_is_built_newest_first() -> None:
    window = build_window("ST", _rows())

    assert window is not None
    assert window.t_last == T0
    assert window.lags[:4] == (0.0, 0.25, 0.5, 0.0)
    assert window.total_ports == 4


def test_window_requires_twelve_buckets() -> None:
    assert build_window("ST", _rows(11)) is None


def test_window_rejects_a_gap_between_buckets() -> None:
    assert build_window("ST", _rows(gap_at=6)) is None


def test_window_rejects_buckets_without_operational_ports() -> None:
    assert build_window("ST", _rows(operational=0)) is None
