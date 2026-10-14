from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from ml import build_dataset as bd
from ml import features as ft
from ml.tests.conftest import make_geo_table

TOTAL = 1000  # ratio = occupied / TOTAL, nên occupied = chỉ số bước cho ra ratio = i / 1000


def _build(raw, **overrides):
    options = {
        "exclude_months": (),
        "warmup_hours": 0.0,
        "val_start": "2099-01-01",
        "test_start": "2099-02-01",
        "geo_table": make_geo_table(sorted(raw["station_id"].unique())),
    }
    options.update(overrides)
    return bd.build_frame(raw, **options)


def test_columns_order_and_dtypes(raw_factory):
    frame = _build(raw_factory(start="2026-09-01T00:00:00+07:00", periods=60))
    expected = (
        *bd.META_COLUMNS,
        *ft.SHARED_FEATURES,
        *ft.ALL_PRED_TIME_COLUMNS,
        *ft.TARGET_COLUMNS,
    )
    assert tuple(frame.columns) == expected
    assert len(frame) == 60 - ft.WINDOW + 1
    assert frame["total_ports"].dtype == np.int16
    assert frame["lag_1"].dtype == np.float32


def test_lag_and_target_alignment(raw_factory):
    frame = _build(raw_factory(start="2026-09-01T00:00:00+07:00", periods=60))
    # ratio(i) = i / 1000, nên y_k - lag_1 = k/1000 và lag_j = lag_1 - (j-1)/1000 ở mọi dòng.
    lag_1 = frame["lag_1"].to_numpy(dtype=float)
    for k, target in enumerate(ft.TARGET_COLUMNS, start=1):
        np.testing.assert_allclose(frame[target] - lag_1, k / TOTAL, atol=1e-6)
    for j in range(1, 13):
        np.testing.assert_allclose(frame[f"lag_{j}"], lag_1 - (j - 1) / TOTAL, atol=1e-6)
    first = frame.iloc[0]
    assert first["t_last"] == pd.Timestamp("2026-09-01T00:55:00+07:00")  # bucket thứ 12
    assert first["lag_1"] == pytest.approx(11 / TOTAL)
    assert first["y1"] == pytest.approx(12 / TOTAL)


def test_october_is_excluded_by_local_month(raw_factory):
    # 20:00+07 ngày 30/9 -> 04:00+07 ngày 1/11 hơn một tháng; 1/10 00:00+07 = 30/9 17:00Z.
    raw = raw_factory(start="2026-09-30T20:00:00+07:00", periods=300 + 288 * 31)
    raw["bucket_at"] = raw["bucket_at"].dt.tz_convert("UTC")
    raw["occupied_ports"] = np.arange(len(raw)) % TOTAL
    frame = _build(raw, exclude_months=["2026-10"])

    local = frame["t_last"].dt.tz_convert(ft.TIMEZONE)
    assert (local.dt.strftime("%Y-%m") != "2026-10").all()
    ends = local + pd.Timedelta(minutes=30)
    assert (ends.dt.strftime("%Y-%m") != "2026-10").all()
    # hai nhóm: cuối tháng 9 (khi t_last + 30' còn trong tháng 9) và đầu tháng 11
    assert local.max() >= pd.Timestamp("2026-11-01T00:00:00+07:00")
    assert local[local < pd.Timestamp("2026-10-01T00:00:00+07:00")].max() == pd.Timestamp(
        "2026-09-30T23:25:00+07:00"
    )


def test_gap_windows_are_dropped(raw_factory):
    raw = raw_factory(start="2026-09-01T00:00:00+07:00", periods=100)
    raw = raw.drop(index=range(50, 53)).reset_index(drop=True)  # thiếu 3 bucket
    frame = _build(raw)
    lag_1 = frame["lag_1"].to_numpy(dtype=float)
    for k, target in enumerate(ft.TARGET_COLUMNS, start=1):
        np.testing.assert_allclose(frame[target] - lag_1, k / TOTAL, atol=1e-6)
    assert len(frame) < 100 - ft.WINDOW + 1  # có cửa sổ bị loại


def test_zero_operational_ports_break_windows(raw_factory):
    raw = raw_factory(start="2026-09-01T00:00:00+07:00", periods=60)
    raw.loc[30, ["operational_ports", "occupied_ports"]] = 0
    frame = _build(raw)
    # cửa sổ không được chứa bucket 30 (ratio không xác định)
    last_index = ((frame["t_last"] - pd.Timestamp("2026-09-01T00:00:00+07:00")) // pd.Timedelta(
        minutes=5
    )).to_numpy()
    assert not ((last_index - 11 <= 30) & (30 <= last_index + 6)).any()


def test_warmup_drops_early_origins(raw_factory):
    raw = raw_factory(start="2026-09-01T00:00:00+07:00", periods=100)
    frame = _build(raw, warmup_hours=2.0)
    assert frame["t_last"].min() == pd.Timestamp("2026-09-01T02:00:00+07:00")


def test_split_boundary_rows_are_purged(raw_factory):
    raw = raw_factory(
        start="2026-09-14T00:00:00+07:00", periods=288 * 2, occupied=np.arange(288 * 2) % TOTAL
    )
    boundary = pd.Timestamp("2026-09-15T00:00:00+07:00")
    frame = _build(raw, val_start=boundary, test_start="2026-09-16")
    train, val = frame[frame["split"] == "train"], frame[frame["split"] == "val"]
    assert len(train) and len(val)
    assert (train["t_last"] + pd.Timedelta(minutes=30) < boundary).all()
    assert (val["t_last"] >= boundary).all()
    # các t_last trong 30 phút cuối trước ranh giới bị loại hẳn
    window_start = boundary - pd.Timedelta(minutes=30)
    lost = frame[(frame["t_last"] >= window_start) & (frame["t_last"] < boundary)]
    assert lost.empty


def test_pred_time_columns_use_target_time(raw_factory):
    # Chủ nhật 13/9/2026 23:50 -> mốc đích +30' là Thứ Hai 00:20
    raw = raw_factory(start="2026-09-13T22:00:00+07:00", periods=60)
    frame = _build(raw)
    row = frame.loc[frame["t_last"] == pd.Timestamp("2026-09-13T23:50:00+07:00")].iloc[0]

    last = ft.time_features(pd.DatetimeIndex([row["t_last"]]))
    target = ft.time_features(pd.DatetimeIndex([row["t_last"] + pd.Timedelta(minutes=30)]))
    assert row["last_dow_sin"] == pytest.approx(last["dow_sin"][0], abs=1e-6)
    assert row["pred_h6_dow_sin"] == pytest.approx(target["dow_sin"][0], abs=1e-6)
    assert row["pred_h6_tod_sin"] == pytest.approx(target["tod_sin"][0], abs=1e-6)
    assert row["pred_h6_dow_cos"] == pytest.approx(1.0)  # Thứ Hai
    assert row["last_dow_cos"] == pytest.approx(np.cos(2 * np.pi * 6 / 7), abs=1e-6)
    # mốc +5' vẫn là Chủ nhật 23:55
    near = ft.time_features(pd.DatetimeIndex([row["t_last"] + pd.Timedelta(minutes=5)]))
    assert row["pred_h1_dow_cos"] == pytest.approx(near["dow_cos"][0], abs=1e-6)


def test_total_ports_comes_from_t_last_bucket(raw_factory):
    raw = raw_factory(start="2026-09-01T00:00:00+07:00", periods=40, total_ports=TOTAL)
    frame = _build(raw)
    assert (frame["total_ports"] == TOTAL).all()


def test_validation_rejects_bad_input(raw_factory):
    raw = raw_factory(start="2026-09-01T00:00:00+07:00", periods=40)
    duplicated = pd.concat([raw, raw.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate"):
        _build(duplicated)

    overfull = raw.copy()
    overfull.loc[0, "occupied_ports"] = TOTAL + 1
    with pytest.raises(ValueError, match="exceeds"):
        _build(overfull)

    off_grid = raw.copy()
    off_grid["bucket_at"] = off_grid["bucket_at"] + pd.Timedelta(minutes=1)
    with pytest.raises(ValueError, match="grid"):
        _build(off_grid)

    with pytest.raises(ValueError, match="misses columns"):
        _build(raw.drop(columns=["total_ports"]))


def test_main_writes_dataset_and_meta(tmp_path, random_raw):
    csv_path = tmp_path / "occupancy.csv"
    random_raw.to_csv(csv_path, index=False)
    geo_path = tmp_path / "geo.parquet"
    total_ports = random_raw.drop_duplicates("station_id").set_index("station_id")["total_ports"]
    geo_table = make_geo_table(sorted(random_raw["station_id"].unique()), total_ports.to_dict())
    geo_table.reset_index().to_parquet(geo_path, index=False)
    out_dir = tmp_path / "out"

    code = bd.main(
        [
            "--input", str(csv_path),
            "--out-dir", str(out_dir),
            "--geo-table", str(geo_path),
            "--exclude-months", "2026-10",
            "--warmup-hours", "0",
            "--val-start", "2026-09-13",
            "--test-start", "2026-09-15",
        ]
    )
    assert code == 0
    frame = pd.read_parquet(out_dir / bd.DATASET_NAME)
    meta = json.loads((out_dir / bd.META_NAME).read_text(encoding="utf-8"))

    assert set(frame["split"]) == {"train", "val", "test"}
    assert meta["rows"] == len(frame)
    assert meta["is_synthetic"] is True
    assert meta["excluded_months"] == ["2026-10"]
    assert meta["sources"][0]["rows"] == len(random_raw)
    assert len(meta["sources"][0]["sha256"]) == 64
    for k in range(1, 7):
        assert meta["feature_columns_by_horizon"][str(k)] == list(ft.feature_columns(k))
        assert len(meta["feature_columns_by_horizon"][str(k)]) == 40
