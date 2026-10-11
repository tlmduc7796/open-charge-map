"""Fixture dựng bảng occupancy thô nhỏ, đủ để kiểm tra build/train mà không cần dữ liệu thật."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def make_raw(
    *,
    start: str,
    periods: int,
    station_id: str = "S1",
    total_ports: int = 1000,
    occupied: np.ndarray | None = None,
) -> pd.DataFrame:
    """Chuỗi 5 phút liên tục; mặc định occupied = chỉ số bước (ratio = i / total_ports)."""
    buckets = pd.date_range(start, periods=periods, freq="5min")
    if occupied is None:
        occupied = np.arange(periods)
    return pd.DataFrame(
        {
            "station_id": station_id,
            "bucket_at": buckets,
            "total_ports": total_ports,
            "operational_ports": total_ports,
            "occupied_ports": occupied,
        }
    )


@pytest.fixture
def raw_factory():
    return make_raw


@pytest.fixture
def random_raw() -> pd.DataFrame:
    """Hai trạm, 6 ngày, bước ngẫu nhiên có seed; đủ dòng cho train/val/test."""
    rng = np.random.default_rng(0)
    frames = []
    for station_id in ("A", "B"):
        steps = rng.integers(-1, 2, size=6 * 288)
        occupied = np.clip(2 + np.cumsum(steps), 0, 4)
        frames.append(
            make_raw(
                start="2026-09-10T00:00:00+07:00",
                periods=6 * 288,
                station_id=station_id,
                total_ports=4,
                occupied=occupied,
            )
        )
    return pd.concat(frames, ignore_index=True)
