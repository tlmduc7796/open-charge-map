"""Huấn luyện và đánh giá 6 mô hình XGBoost độc lập (+5…+30 phút).

    python -m ml.train_eval               # chạy từ gốc repo, sau `python -m ml.build_dataset`

Mô hình k dự đoán `y_k` từ 40 đặc trưng (`ml.features.feature_columns(k)`), early stopping trên
tập val; so với persistence (`lag_1`) trên val và test.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from ml import features as ft
from ml.build_dataset import DATASET_NAME, META_NAME
from ml.build_dataset import DEFAULT_OUT_DIR as DEFAULT_DATA_DIR

DEFAULT_MODEL_DIR = Path(__file__).resolve().parent / "model"
DEFAULT_RESULT_DIR = DEFAULT_DATA_DIR / "occupancy_xgb"
SPLITS = ("val", "test")
GROUPS = ("all", "small", "large")


def error_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    diff = np.asarray(y_pred, dtype=float) - np.asarray(y_true, dtype=float)
    return {
        "mae": float(np.abs(diff).mean()),
        "rmse": float(np.sqrt((diff**2).mean())),
    }


def gain_pct(baseline: float, model: float) -> float | None:
    """Phần trăm giảm lỗi so với persistence (dương = model tốt hơn)."""
    if baseline <= 0:
        return None
    return 100.0 * (baseline - model) / baseline


def evaluate_split(
    frame: pd.DataFrame, prediction: np.ndarray, target: str, *, small_ports: int
) -> dict[str, dict[str, object]]:
    """Metric của model và persistence, tách theo nhóm trạm."""
    ports = frame["total_ports"].to_numpy()
    masks = {
        "all": np.ones(len(frame), dtype=bool),
        "small": ports <= small_ports,
        "large": ports > small_ports,
    }
    y_true = frame[target].to_numpy(dtype=float)
    persistence = frame["lag_1"].to_numpy(dtype=float)
    result: dict[str, dict[str, object]] = {}
    for name, mask in masks.items():
        if not mask.any():
            result[name] = {"n": 0}
            continue
        model = error_metrics(y_true[mask], prediction[mask])
        base = error_metrics(y_true[mask], persistence[mask])
        result[name] = {
            "n": int(mask.sum()),
            "model": model,
            "persistence": base,
            "mae_gain_pct": gain_pct(base["mae"], model["mae"]),
            "rmse_gain_pct": gain_pct(base["rmse"], model["rmse"]),
        }
    return result


def load_dataset(data_dir: Path) -> tuple[pd.DataFrame, dict[str, object]]:
    dataset_path, meta_path = data_dir / DATASET_NAME, data_dir / META_NAME
    for path in (dataset_path, meta_path):
        if not path.is_file():
            raise FileNotFoundError(f"{path} not found; run `python -m ml.build_dataset` first")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    for k in range(1, ft.N_HORIZONS + 1):
        if tuple(meta["feature_columns_by_horizon"][str(k)]) != ft.feature_columns(k):
            raise ValueError(f"dataset feature order differs from ml.features for horizon {k}")
    frame = pd.read_parquet(dataset_path)
    for split in ("train", "val", "test"):
        if not (frame["split"] == split).any():
            raise ValueError(f"dataset has no rows for split {split!r}")
    return frame, meta


def train_horizon(
    frame: pd.DataFrame, k: int, args: argparse.Namespace
) -> tuple[object, dict[str, object], pd.DataFrame]:
    from xgboost import XGBRegressor

    columns = list(ft.feature_columns(k))
    target = ft.TARGET_COLUMNS[k - 1]
    train = frame.loc[frame["split"] == "train"]
    if args.max_train_rows and len(train) > args.max_train_rows:
        train = train.sample(n=args.max_train_rows, random_state=args.seed).sort_index()
    val = frame.loc[frame["split"] == "val"]

    model = XGBRegressor(
        objective="reg:squarederror",
        eval_metric="rmse",
        tree_method="hist",
        n_estimators=args.n_estimators,
        max_depth=args.max_depth,
        learning_rate=args.learning_rate,
        subsample=0.8,
        colsample_bytree=0.8,
        early_stopping_rounds=args.early_stopping_rounds,
        random_state=args.seed,
        n_jobs=-1,
    )
    model.fit(
        train[columns].astype("float32"),
        train[target].astype("float32"),
        eval_set=[(val[columns].astype("float32"), val[target].astype("float32"))],
        verbose=False,
    )

    horizon_result: dict[str, object] = {
        "horizon_min": ft.HORIZONS_MIN[k - 1],
        "best_iteration": int(model.best_iteration),
        "n_train": int(len(train)),
    }
    for split in SPLITS:
        part = frame.loc[frame["split"] == split]
        prediction = np.clip(model.predict(part[columns].astype("float32")), 0.0, 1.0)
        horizon_result[split] = evaluate_split(
            part, prediction, target, small_ports=args.small_ports
        )
    gains = model.get_booster().get_score(importance_type="gain")
    importance = pd.DataFrame(
        {
            "horizon_min": ft.HORIZONS_MIN[k - 1],
            "feature": columns,
            "gain": [float(gains.get(name, 0.0)) for name in columns],
        }
    )
    return model, horizon_result, importance


def _format_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}"


def format_summary(results: dict[str, dict[str, object]]) -> str:
    header = (
        f"{'h':>4} {'split':<5} {'group':<6} {'n':>8} "
        f"{'MAE pers':>9} {'MAE xgb':>9} {'gain%':>7} "
        f"{'RMSE pers':>10} {'RMSE xgb':>9} {'gain%':>7}"
    )
    lines = [header, "-" * len(header)]
    for horizon, result in results.items():
        for split in SPLITS:
            for group in GROUPS:
                cell = result[split][group]
                if not cell.get("n"):
                    continue
                lines.append(
                    f"{horizon:>4} {split:<5} {group:<6} {cell['n']:>8} "
                    f"{cell['persistence']['mae']:>9.4f} {cell['model']['mae']:>9.4f} "
                    f"{_format_pct(cell['mae_gain_pct']):>7} "
                    f"{cell['persistence']['rmse']:>10.4f} {cell['model']['rmse']:>9.4f} "
                    f"{_format_pct(cell['rmse_gain_pct']):>7}"
                )
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="thư mục chứa dataset.parquet"
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=DEFAULT_MODEL_DIR,
        help="nơi ghi 6 file model_h*.json",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_RESULT_DIR,
        help="nơi ghi metrics.json và feature_importance.csv",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n-estimators", type=int, default=1000)
    parser.add_argument("--early-stopping-rounds", type=int, default=50)
    parser.add_argument("--max-depth", type=int, default=6)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument(
        "--max-train-rows", type=int, default=0, help="chỉ để chạy thử nhanh; 0 = dùng toàn bộ"
    )
    parser.add_argument(
        "--small-ports", type=int, default=4, help="trạm có total_ports <= giá trị này là 'small'"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    frame, meta = load_dataset(args.data_dir)
    args.model_dir.mkdir(parents=True, exist_ok=True)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, dict[str, object]] = {}
    importances: list[pd.DataFrame] = []
    for k in range(1, ft.N_HORIZONS + 1):
        model, horizon_result, importance = train_horizon(frame, k, args)
        horizon = ft.HORIZONS_MIN[k - 1]
        model.save_model(args.model_dir / f"model_h{horizon}.json")
        results[str(horizon)] = horizon_result
        importances.append(importance)
        print(f"+{horizon:>2} min: best_iteration={horizon_result['best_iteration']}", flush=True)

    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "data_origin": meta.get("data_origin"),
        "is_synthetic": meta.get("is_synthetic"),
        "params": {
            key: value
            for key, value in vars(args).items()
            if key not in {"data_dir", "model_dir", "out_dir"}
        },
        "target": "occupancy_ratio",
        "baseline": "persistence (lag_1)",
        "group_definition": {
            "small": f"total_ports <= {args.small_ports}",
            "large": f"total_ports > {args.small_ports}",
        },
        "horizons": results,
        "serving_ready": False,
        "note": "Synthetic data: results compare feature sets, not production quality.",
    }
    (args.out_dir / "metrics.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    pd.concat(importances, ignore_index=True).to_csv(
        args.out_dir / "feature_importance.csv", index=False
    )

    print()
    print(format_summary(results))
    print(f"\nmodels : {args.model_dir}")
    print(f"results: {args.out_dir} (metrics.json, feature_importance.csv)")
    if meta.get("is_synthetic"):
        print("NOTE: synthetic data - not evidence of serving quality.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
