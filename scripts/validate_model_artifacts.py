#!/usr/bin/env python3
"""Check Phase 04 occupancy artifacts against the backend serving contract.

For the ML owner: run this after exporting artifacts, before handing them to the backend.

    python scripts/validate_model_artifacts.py                 # paths from .env / defaults
    python scripts/validate_model_artifacts.py --dir ml/artifacts

It uses the exact loader the backend uses, so PASS here means the backend will load the
model. Exit code 0 = PASS, 1 = FAIL.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import load_settings  # noqa: E402
from backend.app.domain.occupancy_model import (  # noqa: E402
    SUPPORTED_HORIZONS_MIN,
    ModelContractError,
    load_meta,
    load_predictor_strict,
    smoke_check,
)

FILENAMES = (
    "occupancy_model.joblib",
    "occupancy_preprocessor.joblib",
    "occupancy_model_meta.json",
)


def _resolve_paths(directory: Path | None) -> tuple[Path, Path, Path]:
    if directory is not None:
        return tuple(directory / name for name in FILENAMES)  # type: ignore[return-value]
    settings = load_settings()
    return (
        settings.model_artifact_path,
        settings.model_preprocessor_path,
        settings.model_meta_path,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", type=Path, help="directory holding the three artifact files")
    args = parser.parse_args()
    model_path, preprocessor_path, meta_path = _resolve_paths(args.dir)

    failures: list[str] = []
    for path in (model_path, preprocessor_path, meta_path):
        status = "found  " if path.is_file() else "MISSING"
        print(f"[{status}] {path}")
        if not path.is_file():
            failures.append(f"missing file: {path.name}")
    if failures:
        print("\nFAIL: " + "; ".join(failures))
        return 1

    try:
        meta = load_meta(meta_path)
        print(f"[ok     ] meta: {meta.model_name} v{meta.model_version}, target={meta.target}")
        print(f"[ok     ] features ({len(meta.features)}): {', '.join(meta.features)}")
        predictor = load_predictor_strict(model_path, preprocessor_path, meta_path)
        horizons = ", +".join(map(str, SUPPORTED_HORIZONS_MIN))
        print(f"[ok     ] estimators for horizons +{horizons} min")
        warnings = smoke_check(predictor)
    except ModelContractError as exc:
        print(f"\nFAIL: {exc}")
        return 1

    for warning in warnings:
        print(f"[warn   ] {warning}")
    print(f"[info   ] metrics in meta: {meta.metrics}")
    print("\nPASS: the backend will load this model (prediction_source=model).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
