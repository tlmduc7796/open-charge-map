#!/usr/bin/env python3
"""Validate and smoke-test an occupancy bundle with the serving loader.

Exit code 0 means the backend accepts the bundle and all supported horizons
produce finite predictions. It does not evaluate model quality or local fit.
"""

from __future__ import annotations

import argparse
import math
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import load_settings  # noqa: E402
from backend.app.domain.model_artifacts import (  # noqa: E402
    SUPPORTED_HORIZONS,
    ArtifactValidationError,
    JoblibOccupancyPredictor,
)

FILENAMES = (
    "occupancy_model.joblib",
    "occupancy_preprocessor.joblib",
    "occupancy_model_meta.json",
)


def resolve_paths(directory: Path | None) -> tuple[Path, Path, Path]:
    if directory is not None:
        return tuple(directory / name for name in FILENAMES)  # type: ignore[return-value]
    settings = load_settings()
    return (
        settings.model_artifact_path,
        settings.model_preprocessor_path,
        settings.model_meta_path,
    )


def validate_bundle(paths: tuple[Path, Path, Path]) -> int:
    model_path, preprocessor_path, metadata_path = paths
    missing = [path.name for path in paths if not path.is_file()]
    for path in paths:
        print(f"[{'found  ' if path.is_file() else 'MISSING'}] {path}")
    if missing:
        print("\nFAIL: missing file(s): " + ", ".join(missing))
        return 1

    try:
        predictor, metadata = JoblibOccupancyPredictor.from_files(
            model_path, preprocessor_path, metadata_path
        )
        history = tuple(index / 20 for index in range(1, 13))
        forecast_at = datetime.now(UTC)
        predictions = {
            horizon: predictor.predict(
                history,
                horizon,
                station_id="artifact-validation-station",
                forecast_at=forecast_at,
            )
            for horizon in SUPPORTED_HORIZONS
        }
    except (ArtifactValidationError, ValueError, TypeError, KeyError) as exc:
        print(f"\nFAIL: {exc}")
        return 1
    except Exception as exc:
        print(f"\nFAIL: inference smoke check failed: {type(exc).__name__}: {exc}")
        return 1

    if any(not math.isfinite(value) for value in predictions.values()):
        print("\nFAIL: smoke prediction contains NaN or infinity")
        return 1
    out_of_range = {
        horizon: value
        for horizon, value in predictions.items()
        if not 0 <= value <= 1
    }
    print(
        f"[ok     ] model_type={metadata.get('model_type')} "
        f"profile={metadata.get('profile')} contract={metadata.get('format_version')}"
    )
    feature_names = metadata.get("feature_names")
    feature_count = len(feature_names) if isinstance(feature_names, list) else "per-horizon"
    print(f"[ok     ] feature contract: {feature_count} features")
    for horizon, value in predictions.items():
        print(f"[smoke  ] +{horizon}m -> {value:.6f}")
    if out_of_range:
        print(f"[warn   ] backend will clamp predictions outside [0, 1]: {out_of_range}")
    print("\nPASS: serving loader accepted the bundle and smoke inference completed.")
    print("This check does not approve model quality, calibration, or deployment scope.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", type=Path, help="directory holding the three bundle files")
    args = parser.parse_args()
    return validate_bundle(resolve_paths(args.dir))


if __name__ == "__main__":
    sys.exit(main())
