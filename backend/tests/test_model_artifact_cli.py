"""CLI handoff checks for the optional occupancy model release bundle."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from backend.app.domain.model_artifacts import SUPPORTED_HORIZONS

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "scripts" / "make_example_model_artifacts.py"
VALIDATOR = ROOT / "scripts" / "validate_model_artifacts.py"


def test_example_bundle_is_loadable_but_not_release_approved(tmp_path: Path) -> None:
    output = tmp_path / "example"
    generated = subprocess.run(
        [sys.executable, str(GENERATOR), "--out", str(output)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert generated.returncode == 0, generated.stdout + generated.stderr
    assert "not a trained model" in generated.stdout

    rejected = subprocess.run(
        [sys.executable, str(VALIDATOR), "--dir", str(output)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert rejected.returncode == 1
    assert "metadata is not approved for serving" in rejected.stdout


def test_validator_smokes_all_horizons_accepted_by_backend(tmp_path: Path) -> None:
    output = tmp_path / "candidate"
    subprocess.run(
        [sys.executable, str(GENERATOR), "--out", str(output)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    metadata_path = output / "occupancy_model_meta.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["serving_ready"] = True
    metadata["model_version"] = "cli-test-v1"
    metadata["model_frozen_at"] = "2026-09-30T00:00:00Z"
    metadata["training_data_max_timestamp"] = "2026-09-29T23:55:00Z"
    metadata["training_data_sha256s"] = ["a" * 64]
    report = {
        "evaluation_type": "independent_temporal_holdout",
        "holdout_status": "independent_untouched",
        "holdout_id": "TEST-HOLDOUT-1",
        "source_record": "TEST-REVIEW-1",
        "timezone": "Asia/Ho_Chi_Minh",
        "evaluation_start": "2026-10-01T01:00:00+00:00",
        "evaluation_end": "2026-10-02T01:00:00+00:00",
        "data_domain": "hcmc_operational",
        "dataset_sha256": "c" * 64,
        "holdout_manifest_sha256": "d" * 64,
        "model_version": "cli-test-v1",
        "model_frozen_at": metadata["model_frozen_at"],
        "training_data_max_timestamp": metadata["training_data_max_timestamp"],
        "training_data_sha256s": metadata["training_data_sha256s"],
        "serving_contract_version": metadata["format_version"],
        "quality_gate_passed": True,
        "evidence_gaps": [],
        "deployment_eligible": True,
        "promotion_performed": False,
        "required_relative_mae_gain": 0.05,
        "approved_calibration_policy": {
            "max_ece_10bin": 0.1,
            "min_slope": 0.5,
            "max_slope": 1.5,
            "max_abs_intercept": 0.2,
            "approved_by": "test reviewer",
            "approval_reference": "TEST-1",
        },
        "approved_sample_policy": {
            "minimum_stations": 1,
            "minimum_samples_per_horizon": 10,
            "approved_by": "test reviewer",
            "approval_reference": "TEST-1",
        },
        "per_horizon": {
            str(horizon): {
                "sample_count": 100,
                "station_count": 10,
                "relative_mae_gain": 0.06,
                "mae_gate_passed": True,
                "calibration_gate_passed": True,
                "sample_coverage_gate_passed": True,
                "candidate_calibration": {
                    "ece_10bin": 0.01,
                    "slope": 1.0,
                    "intercept": 0.0,
                },
            }
            for horizon in SUPPORTED_HORIZONS
        },
        "artifact_sha256s": {
            "occupancy_model.joblib": hashlib.sha256(
                (output / "occupancy_model.joblib").read_bytes()
            ).hexdigest(),
            "occupancy_preprocessor.joblib": hashlib.sha256(
                (output / "occupancy_preprocessor.joblib").read_bytes()
            ).hexdigest(),
        },
    }
    report_bytes = (json.dumps(report, sort_keys=True) + "\n").encode("utf-8")
    (output / "occupancy_evaluation_report.json").write_bytes(report_bytes)
    metadata["evaluation_report_sha256"] = hashlib.sha256(report_bytes).hexdigest()
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    validated = subprocess.run(
        [sys.executable, str(VALIDATOR), "--dir", str(output)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert validated.returncode == 0, validated.stdout + validated.stderr
    assert "PASS: serving loader accepted" in validated.stdout
    assert all(f"[smoke  ] +{horizon}m" in validated.stdout for horizon in (5, 10, 15, 20, 25, 30))
