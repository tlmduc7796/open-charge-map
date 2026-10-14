"""Fixture dựng bảng occupancy thô nhỏ, đủ để kiểm tra build/train mà không cần dữ liệu thật."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml import geo_features as gf


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


def make_geo_table(
    station_ids: list[str], total_ports: dict[str, int] | None = None
) -> pd.DataFrame:
    """Bảng geo tổng hợp (mọi `GEO_COLUMNS` = 0) cho các `station_ids` tuỳ ý trong test.

    Trạm gần nhất là trạm kế tiếp theo vòng tròn (1 trạm thì tự tham chiếu chính nó, giống
    quy ước thoái hoá của `geo_features._neighbor_features`).
    """
    ids = list(station_ids)
    total_ports = total_ports or {}
    n = len(ids)
    nearest = {sid: ids[(i + 1) % n] for i, sid in enumerate(ids)}
    table = pd.DataFrame(
        {column: 0.0 for column in gf.GEO_COLUMNS}, index=pd.Index(ids, name="station_id")
    )
    table["nearest_station_total_ports"] = [
        float(total_ports.get(nearest[sid], 0)) for sid in ids
    ]
    table[gf.NEAREST_STATION_ID_COLUMN] = [nearest[sid] for sid in ids]
    return table


@pytest.fixture
def geo_factory():
    return make_geo_table


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
