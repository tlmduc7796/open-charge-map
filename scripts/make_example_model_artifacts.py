#!/usr/bin/env python3
"""Write a tiny, valid example of the three Phase 04 artifacts (persistence estimators).

Shows the ML owner the exact file formats. The output is NOT a trained model, so it is
written to a scratch directory by default and never into ml/artifacts/.

    python scripts/make_example_model_artifacts.py --out build/example_artifacts
    python scripts/make_example_model_artifacts.py --out build/example_artifacts --time-features
    python scripts/validate_model_artifacts.py --dir build/example_artifacts
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import joblib  # noqa: E402

from backend.app.domain.occupancy_model import (  # noqa: E402
    LAG_FEATURES,
    SUPPORTED_HORIZONS_MIN,
    TIME_FEATURES,
    PersistenceEstimator,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("build/example_artifacts"))
    parser.add_argument("--time-features", action="store_true", help="also declare time features")
    args = parser.parse_args()
    if args.out.resolve() == (ROOT / "ml" / "artifacts").resolve():
        print("Refusing to write example artifacts into ml/artifacts/; pick another --out.")
        return 1

    features = [*LAG_FEATURES, *(TIME_FEATURES if args.time_features else ())]
    newest_lag_index = features.index("lag_1")
    models = {h: PersistenceEstimator(newest_lag_index) for h in SUPPORTED_HORIZONS_MIN}
    meta = {
        "model_name": "example_persistence",
        "model_version": "0.0.0",
        "task": "occupancy_forecasting",
        "training_dataset": "UrbanEV",
        "training_level": "station",
        "temporal_resolution_min": 5,
        "lookback_steps": 12,
        "forecast_steps": 3,
        "features": features,
        "target": "occupancy_ratio",
        "metrics": {"mae": None, "rmse": None},
        "notes": ["Example only; not trained.", "Station IDs are not features."],
    }
    args.out.mkdir(parents=True, exist_ok=True)
    joblib.dump(models, args.out / "occupancy_model.joblib")
    joblib.dump(None, args.out / "occupancy_preprocessor.joblib")  # None = no scaling
    (args.out / "occupancy_model_meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote example artifacts to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
