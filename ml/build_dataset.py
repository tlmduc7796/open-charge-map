"""Dựng bộ dữ liệu huấn luyện (X, y1…y6) từ `station_occupancy_5m`.

    python -m ml.build_dataset            # chạy từ gốc repo

Mỗi dòng ứng với một (trạm, `t_last`): 12 lag đến `t_last`, các đặc trưng xu hướng, sức chứa,
đặc trưng thời gian của `t_last` và của 6 thời điểm đích, cùng 6 nhãn y1…y6 tại +5…+30 phút.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from ml import features as ft

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPO_ROOT / "simulator" / "data" / "station_occupancy_5m.csv"
DEFAULT_OUT_DIR = Path(__file__).resolve().parent / "data"
DATASET_NAME = "dataset.parquet"
META_NAME = "dataset.meta.json"
FORMAT_VERSION = "1.0"

REQUIRED_COLUMNS = (
    "station_id",
    "bucket_at",
    "total_ports",
    "operational_ports",
    "occupied_ports",
)
META_COLUMNS = ("station_id", "t_last", "split")
EPOCH = pd.Timestamp("1970-01-01", tz="UTC")


def epoch_minutes(timestamps: pd.Series) -> np.ndarray:
    """Phút epoch (int64), không phụ thuộc độ phân giải datetime của pandas."""
    return ((timestamps - EPOCH) // pd.Timedelta(minutes=1)).to_numpy(dtype=np.int64)


def validate_raw(raw: pd.DataFrame) -> pd.DataFrame:
    """Kiểm tra schema/ràng buộc của bảng thô và chuẩn hoá kiểu (bucket_at -> UTC)."""
    missing = set(REQUIRED_COLUMNS) - set(raw.columns)
    if missing:
        raise ValueError(f"occupancy data misses columns: {sorted(missing)}")
    df = raw.loc[:, list(REQUIRED_COLUMNS)].copy()
    if df.isna().any().any():
        raise ValueError("occupancy data contains null values")
    df["station_id"] = df["station_id"].astype(str)
    if pd.api.types.is_datetime64_any_dtype(df["bucket_at"]):
        df["bucket_at"] = pd.to_datetime(df["bucket_at"], utc=True)
    else:
        df["bucket_at"] = pd.to_datetime(df["bucket_at"], utc=True, format="ISO8601")
    for column in ("total_ports", "operational_ports", "occupied_ports"):
        df[column] = df[column].astype("int64")
    if (df["total_ports"] <= 0).any():
        raise ValueError("total_ports must be positive")
    if (df["operational_ports"] < 0).any() or (df["occupied_ports"] < 0).any():
        raise ValueError("port counts must be non-negative")
    if (df["operational_ports"] > df["total_ports"]).any():
        raise ValueError("operational_ports exceeds total_ports")
    if (df["occupied_ports"] > df["operational_ports"]).any():
        raise ValueError("occupied_ports exceeds operational_ports")
    if df.duplicated(["station_id", "bucket_at"]).any():
        raise ValueError("duplicate (station_id, bucket_at) observations")
    seconds = ((df["bucket_at"] - EPOCH) // pd.Timedelta(seconds=1)).to_numpy(dtype=np.int64)
    if (seconds % (ft.INTERVAL_MIN * 60) != 0).any():
        raise ValueError(f"bucket_at must lie on a {ft.INTERVAL_MIN}-minute grid")
    return df


def _local_timestamp(value: str | pd.Timestamp) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    return stamp.tz_localize(ft.TIMEZONE) if stamp.tz is None else stamp.tz_convert(ft.TIMEZONE)


def assign_split(
    timestamps: pd.DatetimeIndex, val_start: pd.Timestamp, test_start: pd.Timestamp
) -> np.ndarray:
    """train < val_start <= val < test_start <= test (theo thời gian)."""
    return np.where(
        timestamps < val_start, "train", np.where(timestamps < test_start, "val", "test")
    )


def build_frame(
    raw: pd.DataFrame,
    *,
    exclude_months: Iterable[str] = (),
    warmup_hours: float = 24.0,
    val_start: str | pd.Timestamp = "2026-07-01",
    test_start: str | pd.Timestamp = "2026-09-01",
) -> pd.DataFrame:
    """Dựng bảng (meta, X, y) từ bảng occupancy thô. Không có I/O.

    - `exclude_months` (`YYYY-MM`, theo giờ địa phương) bị loại trước khi dựng cửa sổ.
    - Chỉ giữ cửa sổ 18 bucket liên tục, không NaN; bỏ `warmup_hours` đầu mỗi trạm
      (simulator khởi động từ trạng thái rỗng).
    - Dòng có `t_last` và `t_last + 30'` thuộc hai split khác nhau bị loại (chống rò nhãn).
    """
    val_ts, test_ts = _local_timestamp(val_start), _local_timestamp(test_start)
    if not val_ts < test_ts:
        raise ValueError("val_start must be earlier than test_start")
    df = validate_raw(raw)
    series_start = df.groupby("station_id")["bucket_at"].min()  # trước khi loại tháng
    local_month = df["bucket_at"].dt.tz_convert(ft.TIMEZONE).dt.strftime("%Y-%m")
    df = df.loc[~local_month.isin(set(exclude_months))]
    if df.empty:
        raise ValueError("no observations left after excluding months")

    parts: list[pd.DataFrame] = []
    horizon_end = pd.Timedelta(minutes=ft.HORIZONS_MIN[-1])
    for station_id, group in df.groupby("station_id", sort=True):
        group = group.sort_values("bucket_at")
        occupied = group["occupied_ports"].to_numpy(dtype=float)
        operational = group["operational_ports"].to_numpy(dtype=float)
        ratio = np.divide(
            occupied, operational, out=np.full(len(group), np.nan), where=operational > 0
        )
        starts = ft.valid_window_starts(epoch_minutes(group["bucket_at"]), ratio)
        if starts.size == 0:
            continue
        last_index = starts + ft.N_LAGS - 1
        t_last = pd.DatetimeIndex(group["bucket_at"].iloc[last_index])
        keep = np.asarray(t_last >= series_start[station_id] + pd.Timedelta(hours=warmup_hours))
        keep &= assign_split(t_last, val_ts, test_ts) == assign_split(
            t_last + horizon_end, val_ts, test_ts
        )
        if not keep.any():
            continue
        starts, last_index, t_last = starts[keep], last_index[keep], t_last[keep]

        lags, targets = ft.split_windows(ratio, starts)
        columns: dict[str, np.ndarray | pd.Series] = {
            "station_id": np.full(len(starts), station_id, dtype=object),
            "t_last": t_last.tz_convert(ft.TIMEZONE),
            "split": assign_split(t_last, val_ts, test_ts),
        }
        for index, name in enumerate(ft.LAG_COLUMNS):
            columns[name] = lags[:, index]
        columns.update(ft.dynamics_features(lags))
        columns["total_ports"] = group["total_ports"].to_numpy()[last_index]
        for suffix, values in ft.time_features(t_last).items():
            columns[f"last_{suffix}"] = values
        for k in range(1, ft.N_HORIZONS + 1):
            shifted = t_last + pd.Timedelta(minutes=ft.INTERVAL_MIN * k)
            for suffix, values in ft.time_features(shifted).items():
                columns[f"pred_h{k}_{suffix}"] = values
        for index, name in enumerate(ft.TARGET_COLUMNS):
            columns[name] = targets[:, index]
        parts.append(pd.DataFrame(columns))

    if not parts:
        raise ValueError("no complete 18-bucket window found")
    out = pd.concat(parts, ignore_index=True)
    out = out.sort_values(["station_id", "t_last"]).reset_index(drop=True)
    float_columns = [
        c for c in out.columns if c not in META_COLUMNS and c != "total_ports"
    ]
    out[float_columns] = out[float_columns].astype("float32")
    out["total_ports"] = out["total_ports"].astype("int16")
    ordered = (
        *META_COLUMNS,
        *ft.SHARED_FEATURES,
        *ft.ALL_PRED_TIME_COLUMNS,
        *ft.TARGET_COLUMNS,
    )
    out = out.loc[:, list(ordered)]
    _validate_output(out, exclude_months)
    return out


def _validate_output(frame: pd.DataFrame, exclude_months: Iterable[str]) -> None:
    numeric = frame.drop(columns=list(META_COLUMNS))
    if numeric.isna().any().any():
        raise ValueError("output contains NaN")
    targets = frame.loc[:, list(ft.TARGET_COLUMNS)].to_numpy()
    if targets.min() < 0 or targets.max() > 1:
        raise ValueError("targets must lie within [0, 1]")
    excluded = set(exclude_months)
    if excluded:
        months = frame["t_last"].dt.strftime("%Y-%m")
        end_months = (frame["t_last"] + pd.Timedelta(minutes=ft.HORIZONS_MIN[-1])).dt.strftime(
            "%Y-%m"
        )
        if months.isin(excluded).any() or end_months.isin(excluded).any():
            raise ValueError("an excluded month leaked into the dataset")


def load_inputs(paths: Sequence[Path]) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    frames: list[pd.DataFrame] = []
    sources: list[dict[str, object]] = []
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"input file not found: {path}")
        frame = pd.read_csv(path, usecols=list(REQUIRED_COLUMNS), dtype={"station_id": str})
        frames.append(frame)
        sources.append(
            {
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "rows": int(len(frame)),
            }
        )
    return pd.concat(frames, ignore_index=True), sources


def build_meta(
    frame: pd.DataFrame,
    *,
    sources: list[dict[str, object]],
    exclude_months: Sequence[str],
    warmup_hours: float,
    val_start: pd.Timestamp,
    test_start: pd.Timestamp,
    data_origin: str,
) -> dict[str, object]:
    return {
        "format_version": FORMAT_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "data_origin": data_origin,
        "is_synthetic": data_origin == "synthetic",
        "sources": sources,
        "excluded_months": list(exclude_months),
        "timezone": ft.TIMEZONE,
        "warmup_hours": warmup_hours,
        "interval_min": ft.INTERVAL_MIN,
        "n_lags": ft.N_LAGS,
        "horizons_min": list(ft.HORIZONS_MIN),
        "split": {
            "rule": "by local date of t_last; rows whose t_last and t_last+30min fall in "
            "different splits are dropped",
            "val_start": val_start.isoformat(),
            "test_start": test_start.isoformat(),
        },
        "meta_columns": list(META_COLUMNS),
        "shared_features": list(ft.SHARED_FEATURES),
        "feature_columns_by_horizon": {
            str(k): list(ft.feature_columns(k)) for k in range(1, ft.N_HORIZONS + 1)
        },
        "target_columns": list(ft.TARGET_COLUMNS),
        "rows": int(len(frame)),
        "rows_by_split": {k: int(v) for k, v in frame["split"].value_counts().items()},
        "rows_by_station": {k: int(v) for k, v in frame["station_id"].value_counts().items()},
        "t_last_min": frame["t_last"].min().isoformat(),
        "t_last_max": frame["t_last"].max().isoformat(),
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, nargs="+", default=[DEFAULT_INPUT])
    parser.add_argument(
        "--exclude-months",
        nargs="*",
        default=["2026-10"],
        help="tháng YYYY-MM (giờ địa phương) bị loại; mặc định 2026-10",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--warmup-hours", type=float, default=24.0)
    parser.add_argument("--val-start", default="2026-07-01")
    parser.add_argument("--test-start", default="2026-09-01")
    parser.add_argument("--data-origin", choices=("synthetic", "real"), default="synthetic")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    raw, sources = load_inputs(args.input)
    frame = build_frame(
        raw,
        exclude_months=args.exclude_months,
        warmup_hours=args.warmup_hours,
        val_start=args.val_start,
        test_start=args.test_start,
    )
    meta = build_meta(
        frame,
        sources=sources,
        exclude_months=args.exclude_months,
        warmup_hours=args.warmup_hours,
        val_start=_local_timestamp(args.val_start),
        test_start=_local_timestamp(args.test_start),
        data_origin=args.data_origin,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = args.out_dir / DATASET_NAME
    meta_path = args.out_dir / META_NAME
    frame.to_parquet(dataset_path, index=False)
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"dataset : {dataset_path}")
    print(f"meta    : {meta_path}")
    print(f"rows    : {meta['rows']:,} | stations: {frame['station_id'].nunique()}")
    print(f"splits  : {meta['rows_by_split']}")
    print(f"t_last  : {meta['t_last_min']} -> {meta['t_last_max']}")
    print(f"excluded: {args.exclude_months} | features/model: {len(ft.feature_columns(1))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
