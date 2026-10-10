#!/usr/bin/env python3
"""Write an importable, unapproved example bundle for the Phase 04 contract.

The output is intentionally rejected by the release validator because it is
not trained or evaluated. It is useful for inspecting the bundle structure.
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

from backend.app.domain.example_models import PersistenceExampleEstimator  # noqa: E402
from backend.app.domain.model_artifacts import (  # noqa: E402
    SUPPORTED_FEATURES,
    SUPPORTED_HORIZONS,
)
from backend.app.domain.model_contract import CONTRACT_VERSION  # noqa: E402


def write_example_artifacts(output_dir: Path) -> None:
    feature_names = list(SUPPORTED_FEATURES)
    feature_names_by_horizon = {
        str(horizon): feature_names for horizon in SUPPORTED_HORIZONS
    }
    model_bundle = {
        "format_version": CONTRACT_VERSION,
        "prediction_mode": "direct",
        "feature_names_by_horizon": feature_names_by_horizon,
        "models": {horizon: PersistenceExampleEstimator() for horizon in SUPPORTED_HORIZONS},
    }
    preprocessor_bundle = {
        "format_version": CONTRACT_VERSION,
        "prediction_mode": "direct",
        "feature_names_by_horizon": feature_names_by_horizon,
    }
    metadata = {
        "format_version": CONTRACT_VERSION,
        "model_version": "example-unapproved",
        "created_at": "example-only",
        "model_type": "persistence_example",
        "prediction_mode": "direct",
        "profile": "baseline",
        "feature_names": feature_names,
        "feature_names_by_horizon": feature_names_by_horizon,
        "lookback_steps": 12,
        "horizons_min": list(SUPPORTED_HORIZONS),
        "target": "occupancy_ratio",
        "metrics": None,
        "serving_ready": False,
        "release_status": "example_only_not_evaluated",
        "limitations": ["Not trained or evaluated; never use for release serving."],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(model_bundle, output_dir / "occupancy_model.joblib")
    joblib.dump(preprocessor_bundle, output_dir / "occupancy_preprocessor.joblib")
    (output_dir / "occupancy_model_meta.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("build/example_artifacts"))
    args = parser.parse_args()
    if args.out.resolve() == (ROOT / "ml" / "artifacts").resolve():
        print("Refusing to write example artifacts into ml/artifacts/; pick another --out.")
        return 1
    write_example_artifacts(args.out)
    print(f"Wrote unapproved contract example to {args.out}")
    print("It is not a trained model and must not be used for release serving.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
