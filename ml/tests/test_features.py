from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml import features as ft


def test_feature_contract_has_26_unique_columns_per_horizon():
    assert len(ft.SHARED_FEATURES) == 22
    assert ft.HORIZONS_MIN == (5, 10, 15, 20, 25, 30)
    for k in range(1, 7):
        columns = ft.feature_columns(k)
        assert len(columns) == 26
        assert len(set(columns)) == 26
        assert columns[:22] == ft.SHARED_FEATURES
        assert all(c.startswith(f"pred_h{k}_") for c in columns[22:])
    with pytest.raises(ValueError):
        ft.feature_columns(7)


def test_valid_window_starts_skips_gaps_and_nan():
    n = 40
    epoch = np.arange(n, dtype=np.int64) * 5
    ratio = np.linspace(0, 1, n)
    assert list(ft.valid_window_starts(epoch, ratio)) == list(range(n - ft.WINDOW + 1))

    gapped = epoch.copy()
    gapped[20:] += 5  # thiếu một bucket giữa chỉ số 19 và 20
    starts = ft.valid_window_starts(gapped, ratio)
    assert all(not (s <= 19 < s + ft.WINDOW - 1) for s in starts)  # không cửa sổ nào qua lỗ hổng
    assert 0 in starts and 20 in starts

    with_nan = ratio.copy()
    with_nan[10] = np.nan
    starts = ft.valid_window_starts(epoch, with_nan)
    assert all(not (s <= 10 < s + ft.WINDOW) for s in starts)


def test_split_windows_orders_lags_newest_first_and_targets_forward():
    ratio = np.arange(30) / 100
    starts = np.array([0, 5])
    lags, targets = ft.split_windows(ratio, starts)
    # cửa sổ bắt đầu 0: lag_1 là phần tử thứ 11 (chỉ số 11), lag_12 là chỉ số 0
    assert lags[0, 0] == pytest.approx(0.11)
    assert lags[0, 11] == pytest.approx(0.0)
    assert targets[0, 0] == pytest.approx(0.12)  # y1 = bước kế tiếp
    assert targets[0, 5] == pytest.approx(0.17)  # y6 = +30 phút
    assert lags[1, 0] == pytest.approx(0.16)


def test_dynamics_features_on_hand_built_series():
    # lag_1 (mới nhất) -> lag_12 (cũ nhất)
    lags = np.array(
        [
            [0.8, 0.7, 0.6, 0.6, 0.5, 0.5, 0.4, 0.4, 0.3, 0.3, 0.2, 0.2],  # xu hướng tăng
            [0.5] * 12,  # phẳng hoàn toàn
            [0.5, 0.5, 0.5, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9],  # đổi sau 2 bước
        ]
    )
    out = ft.dynamics_features(lags)
    assert out["diff_1"][0] == pytest.approx(0.1)
    assert out["roll_mean_3"][0] == pytest.approx((0.8 + 0.7 + 0.6) / 3)
    assert out["roll_mean_12"][0] == pytest.approx(lags[0].mean())
    assert out["n_changes_12"].tolist() == [6.0, 0.0, 1.0]
    assert out["steps_since_change"].tolist() == [0.0, 11.0, 2.0]


def test_time_features_wrap_midnight_and_week():
    sunday_late = pd.DatetimeIndex(["2026-09-13T23:50:00+07:00"])  # Chủ nhật
    monday_early = sunday_late + pd.Timedelta(minutes=30)  # 00:20 Thứ Hai
    late = ft.time_features(sunday_late)
    early = ft.time_features(monday_early)

    expected_dow_late = 2 * np.pi * 6 / 7
    assert late["dow_sin"][0] == pytest.approx(np.sin(expected_dow_late))
    assert early["dow_sin"][0] == pytest.approx(0.0, abs=1e-12)  # Thứ Hai = 0
    assert early["dow_cos"][0] == pytest.approx(1.0)
    # 23:50 và 00:20 nằm gần nhau trên vòng tròn giờ
    assert late["tod_cos"][0] == pytest.approx(np.cos(2 * np.pi * (23 * 60 + 50) / 1440))
    assert late["tod_sin"][0] < 0 < early["tod_sin"][0]


def test_time_features_use_local_timezone_not_utc():
    utc_stamp = pd.DatetimeIndex(["2026-09-13T17:00:00Z"])  # = 00:00 Thứ Hai giờ VN
    out = ft.time_features(utc_stamp)
    assert out["tod_sin"][0] == pytest.approx(0.0, abs=1e-12)
    assert out["tod_cos"][0] == pytest.approx(1.0)
    assert out["dow_sin"][0] == pytest.approx(0.0, abs=1e-12)


def test_time_features_require_timezone():
    with pytest.raises(ValueError):
        ft.time_features(pd.DatetimeIndex(["2026-09-13T00:00:00"]))
