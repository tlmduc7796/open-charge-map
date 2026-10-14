"""Hợp đồng cột và các hàm đặc trưng thuần cho dự báo occupancy theo bucket 5 phút.

Mọi quy ước nằm ở đây để `build_dataset`, `train_eval` và test dùng chung một định nghĩa.

Quy ước thời gian: `t_last` là bucket của quan sát mới nhất đã biết (= `lag_1`). Nhãn `y_k` là
occupancy_ratio tại `t_last + 5k` phút (k = 1..6, tức +5…+30 phút).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from ml.geo_features import GEO_COLUMNS

INTERVAL_MIN = 5
N_LAGS = 12
N_HORIZONS = 6
HORIZONS_MIN = tuple(INTERVAL_MIN * k for k in range(1, N_HORIZONS + 1))  # 5, 10, ..., 30
WINDOW = N_LAGS + N_HORIZONS  # 12 lag + 6 nhãn, liên tiếp nhau trên lưới 5 phút

TIMEZONE = "Asia/Ho_Chi_Minh"
MINUTES_PER_DAY = 24 * 60
DAYS_PER_WEEK = 7
CHANGE_EPS = 1e-9  # hai ratio khác nhau hơn ngưỡng này được tính là "đã đổi"

LAG_COLUMNS = tuple(f"lag_{k}" for k in range(1, N_LAGS + 1))
DYNAMIC_COLUMNS = (
    "diff_1",
    "roll_mean_3",
    "roll_mean_12",
    "n_changes_12",
    "steps_since_change",
)
CAPACITY_COLUMNS = ("total_ports",)
# Đặc trưng địa lý tĩnh theo trạm (POI theo bán kính 300m, dân số phường, quy mô trạm lân
# cận) — xem ml/geo_features.py. `SPATIAL_LAG_COLUMNS` không tĩnh: là occupancy của trạm gần
# nhất tại cùng t_last, build_dataset.py tính lại cho mỗi dòng giống lag_1..lag_12.
SPATIAL_LAG_COLUMNS = ("nearest_station_occupancy_lag1",)
TIME_SUFFIXES = ("tod_sin", "tod_cos", "dow_sin", "dow_cos")
LAST_TIME_COLUMNS = tuple(f"last_{suffix}" for suffix in TIME_SUFFIXES)
TARGET_COLUMNS = tuple(f"y{k}" for k in range(1, N_HORIZONS + 1))

# 36 cột dùng chung cho cả 6 mô hình; mô hình k thêm 4 cột `pred_hk_*` của chính nó.
SHARED_FEATURES = (
    LAG_COLUMNS
    + DYNAMIC_COLUMNS
    + CAPACITY_COLUMNS
    + GEO_COLUMNS
    + SPATIAL_LAG_COLUMNS
    + LAST_TIME_COLUMNS
)


def _check_horizon_index(k: int) -> None:
    if not 1 <= k <= N_HORIZONS:
        raise ValueError(f"horizon index must be in 1..{N_HORIZONS}, got {k}")


def pred_time_columns(k: int) -> tuple[str, ...]:
    """4 cột thời gian của thời điểm đích `t_last + 5k` phút (k = 1..6)."""
    _check_horizon_index(k)
    return tuple(f"pred_h{k}_{suffix}" for suffix in TIME_SUFFIXES)


def feature_columns(k: int) -> tuple[str, ...]:
    """40 đặc trưng, đúng thứ tự, của mô hình thứ k."""
    return SHARED_FEATURES + pred_time_columns(k)


ALL_PRED_TIME_COLUMNS = tuple(
    column for k in range(1, N_HORIZONS + 1) for column in pred_time_columns(k)
)


def valid_window_starts(epoch_min: np.ndarray, ratio: np.ndarray) -> np.ndarray:
    """Chỉ số bắt đầu của các cửa sổ 18 bucket liên tục, không thiếu và không NaN.

    `epoch_min` là phút epoch, tăng nghiêm ngặt và là bội của 5 (người gọi đã kiểm tra), nên
    cửa sổ có hiệu đầu-cuối đúng 17 × 5 phút thì mọi bước đều đúng 5 phút.
    """
    epoch_min = np.asarray(epoch_min, dtype=np.int64)
    ratio = np.asarray(ratio, dtype=float)
    if epoch_min.shape != ratio.shape:
        raise ValueError("epoch_min and ratio must have the same shape")
    n = len(ratio)
    if n < WINDOW:
        return np.empty(0, dtype=np.int64)
    span_ok = (epoch_min[WINDOW - 1 :] - epoch_min[: n - WINDOW + 1]) == INTERVAL_MIN * (
        WINDOW - 1
    )
    has_nan = sliding_window_view(np.isnan(ratio), WINDOW).any(axis=1)
    return np.flatnonzero(span_ok & ~has_nan)


def split_windows(ratio: np.ndarray, starts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Tách cửa sổ thành (lags, targets).

    `lags[:, 0]` là `lag_1` (mới nhất), `lags[:, 11]` là `lag_12`; `targets[:, k-1]` là y_k.
    """
    windows = sliding_window_view(np.asarray(ratio, dtype=float), WINDOW)[starts]
    lags = windows[:, N_LAGS - 1 :: -1]
    targets = windows[:, N_LAGS:]
    return lags, targets


def dynamics_features(lags: np.ndarray) -> dict[str, np.ndarray]:
    """Đặc trưng xu hướng/biến động tính từ 12 lag (cột 0 = `lag_1`)."""
    lags = np.asarray(lags, dtype=float)
    if lags.ndim != 2 or lags.shape[1] != N_LAGS:
        raise ValueError(f"lags must have shape (n, {N_LAGS})")
    # changed[:, i] cho cặp (lag_{i+1}, lag_{i+2}); cột 0 là cặp mới nhất.
    changed = np.abs(lags[:, :-1] - lags[:, 1:]) > CHANGE_EPS
    steps_since_change = np.where(changed.any(axis=1), changed.argmax(axis=1), N_LAGS - 1)
    return {
        "diff_1": lags[:, 0] - lags[:, 1],
        "roll_mean_3": lags[:, :3].mean(axis=1),
        "roll_mean_12": lags.mean(axis=1),
        "n_changes_12": changed.sum(axis=1).astype(float),
        "steps_since_change": steps_since_change.astype(float),
    }


def time_features(timestamps: pd.DatetimeIndex) -> dict[str, np.ndarray]:
    """sin/cos của giờ trong ngày (chu kỳ 1440 phút) và thứ trong tuần (chu kỳ 7 ngày).

    Giờ và thứ tính theo `TIMEZONE`; thứ Hai = 0. Khoá trả về là `TIME_SUFFIXES`.
    """
    if timestamps.tz is None:
        raise ValueError("timestamps must be timezone-aware")
    local = timestamps.tz_convert(TIMEZONE)
    minute_of_day = (local.hour * 60 + local.minute).to_numpy(dtype=float)
    day_of_week = local.dayofweek.to_numpy(dtype=float)
    tod_angle = 2.0 * np.pi * minute_of_day / MINUTES_PER_DAY
    dow_angle = 2.0 * np.pi * day_of_week / DAYS_PER_WEEK
    return {
        "tod_sin": np.sin(tod_angle),
        "tod_cos": np.cos(tod_angle),
        "dow_sin": np.sin(dow_angle),
        "dow_cos": np.cos(dow_angle),
    }
