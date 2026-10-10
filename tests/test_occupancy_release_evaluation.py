import json
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from scripts.evaluate_occupancy_release import (
    _load_holdout,
    evaluate_holdout,
    run_evaluation,
    sha256_file,
    validate_release_evidence,
)
from scripts.make_example_model_artifacts import write_example_artifacts
from shared.occupancy_contract import SUPPORTED_HORIZONS_MIN


class _PerfectTimestampPredictor:
    def __init__(self, start: datetime) -> None:
        self.start = start

    def predict(self, _history, _horizon, *, station_id, forecast_at):
        assert station_id == "station-1"
        step = round((forecast_at - self.start).total_seconds() / 300)
        return (step % 20) / 20


def _manifest() -> dict:
    return {
        "holdout_id": "HCMC-OPS-2026-Q4-01",
        "holdout_status": "independent_untouched",
        "model_selection_used": False,
        "source_record": "DATA-REVIEW-123",
        "dataset_sha256": "c" * 64,
        "data_domain": "hcmc_operational",
        "timezone": "Asia/Ho_Chi_Minh",
        "evaluation_start": "2026-10-01T08:00:00+07:00",
        "evaluation_end": "2026-10-01T11:00:00+07:00",
        "calibration_policy": {
            "max_ece_10bin": 0.05,
            "min_slope": 0.8,
            "max_slope": 1.2,
            "max_abs_intercept": 0.1,
            "approved_by": "Model Review Board",
            "approval_reference": "ML-RELEASE-123",
        },
        "sample_policy": {
            "minimum_stations": 1,
            "minimum_samples_per_horizon": 1,
            "approved_by": "Model Review Board",
            "approval_reference": "ML-RELEASE-123",
        },
    }


def _metadata() -> dict:
    return {
        "model_version": "candidate-v1",
        "format_version": "2.2",
        "training_data_sha256s": ["a" * 64],
        "model_frozen_at": "2026-09-30T00:00:00Z",
        "training_data_max_timestamp": "2026-09-29T23:55:00Z",
    }


def test_independent_hcmc_holdout_can_pass_quality_gate_without_promoting() -> None:
    start = datetime(2026, 10, 1, 0, tzinfo=UTC)
    timestamps = [start + timedelta(minutes=5 * index) for index in range(67)]
    values = [(index % 20) / 20 for index in range(len(timestamps))]
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "entity_id": ["station-1"] * len(timestamps),
            "occupancy_ratio": values,
        }
    )

    report = evaluate_holdout(
        frame,
        _PerfectTimestampPredictor(start),
        _manifest(),
        _metadata(),
        dataset_sha256="c" * 64,
        manifest_sha256="f" * 64,
    )

    assert report["quality_gate_passed"] is True
    assert report["deployment_eligible"] is True
    assert report["promotion_performed"] is False
    assert tuple(map(int, report["per_horizon"])) == SUPPORTED_HORIZONS_MIN
    assert all(item["mae_gate_passed"] for item in report["per_horizon"].values())


def test_evaluation_evidence_rejects_reused_or_post_selection_holdout() -> None:
    manifest = _manifest() | {"model_selection_used": True}
    manifest["dataset_sha256"] = "b" * 64
    metadata = _metadata() | {"training_data_sha256s": ["b" * 64]}

    gaps = validate_release_evidence(
        manifest,
        metadata,
        dataset_sha256="b" * 64,
        manifest_sha256="f" * 64,
    )

    assert "holdout_selection_independence_not_attested" in gaps
    assert "holdout_dataset_hash_matches_training_data" in gaps


def test_evaluation_evidence_pins_reviewed_holdout_bytes() -> None:
    gaps = validate_release_evidence(
        _manifest(),
        _metadata(),
        dataset_sha256="d" * 64,
        manifest_sha256="f" * 64,
    )

    assert "holdout_dataset_hash_mismatch" in gaps


def test_evaluation_evidence_requires_sha256_in_manifest() -> None:
    manifest = _manifest() | {"dataset_sha256": None}

    gaps = validate_release_evidence(
        manifest,
        _metadata(),
        dataset_sha256="c" * 64,
        manifest_sha256="f" * 64,
    )

    assert "holdout_dataset_hash_missing_or_invalid" in gaps


def test_evaluation_evidence_requires_manifest_byte_hash() -> None:
    gaps = validate_release_evidence(
        _manifest(),
        _metadata(),
        dataset_sha256="c" * 64,
        manifest_sha256="invalid",
    )

    assert "holdout_manifest_hash_missing_or_invalid" in gaps


def test_training_timestamp_must_precede_holdout_window() -> None:
    gaps = validate_release_evidence(
        _manifest(),
        _metadata() | {"training_data_max_timestamp": "2026-10-01T01:00:00Z"},
        dataset_sha256="c" * 64,
        manifest_sha256="f" * 64,
    )

    assert "training_data_overlaps_or_follows_holdout" in gaps


def test_holdout_loader_normalizes_local_wall_time_to_utc(tmp_path) -> None:
    dataset_path = tmp_path / "holdout.parquet"
    pd.DataFrame(
        {
            "timestamp": [
                "2026-10-01 07:00:00",
                "2026-10-01 07:05:00",
            ],
            "entity_id": ["station-1", "station-1"],
            "occupancy_ratio": [0.2, 0.3],
            "data_origin": ["observed", "observed"],
        }
    ).to_parquet(dataset_path, index=False)

    frame = _load_holdout(dataset_path, {"timezone": "Asia/Ho_Chi_Minh"})

    assert frame["timestamp"].iloc[0] == pd.Timestamp("2026-10-01T00:00:00Z")


def test_holdout_loader_rejects_existing_split_dataset(tmp_path) -> None:
    dataset_path = tmp_path / "split-data.parquet"
    pd.DataFrame(
        {
            "timestamp": ["2026-10-01T00:00:00Z"],
            "entity_id": ["station-1"],
            "occupancy_ratio": [0.2],
            "data_origin": ["observed"],
            "split": ["test"],
        }
    ).to_parquet(dataset_path, index=False)

    with pytest.raises(ValueError, match="separate dataset without a split column"):
        _load_holdout(dataset_path, {"timezone": "UTC"})


def test_holdout_loader_rejects_inferred_or_synthetic_observations(tmp_path) -> None:
    dataset_path = tmp_path / "not-observed.parquet"
    pd.DataFrame(
        {
            "timestamp": ["2026-10-01T00:00:00Z"],
            "entity_id": ["station-1"],
            "occupancy_ratio": [0.2],
            "data_origin": ["synthetic"],
        }
    ).to_parquet(dataset_path, index=False)

    with pytest.raises(ValueError, match="only data_origin=observed"):
        _load_holdout(dataset_path, {"timezone": "UTC"})


def test_evaluator_can_load_candidate_without_approving_or_mutating_it(tmp_path) -> None:
    artifact_dir = tmp_path / "candidate"
    write_example_artifacts(artifact_dir)
    metadata_path = artifact_dir / "occupancy_model_meta.json"
    before_metadata = metadata_path.read_bytes()
    start = datetime(2026, 10, 1, 0, tzinfo=UTC)
    dataset_path = tmp_path / "holdout.parquet"
    pd.DataFrame(
        {
            "timestamp": [start + timedelta(minutes=5 * index) for index in range(67)],
            "entity_id": ["station-1"] * 67,
            "occupancy_ratio": [(index % 20) / 20 for index in range(67)],
            "data_origin": ["observed"] * 67,
        }
    ).to_parquet(dataset_path, index=False)
    manifest_path = tmp_path / "manifest.json"
    manifest = _manifest() | {"dataset_sha256": sha256_file(dataset_path)}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report_path = tmp_path / "report.json"

    report = run_evaluation(dataset_path, manifest_path, artifact_dir, report_path)

    assert report["quality_gate_passed"] is False
    assert report["deployment_eligible"] is False
    assert report["promotion_performed"] is False
    assert metadata_path.read_bytes() == before_metadata
    assert report_path.is_file()


def test_source_domain_holdout_does_not_qualify_for_customer_release() -> None:
    start = datetime(2026, 10, 1, 0, tzinfo=UTC)
    timestamps = [start + timedelta(minutes=5 * index) for index in range(67)]
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "entity_id": ["station-1"] * len(timestamps),
            "occupancy_ratio": [(index % 20) / 20 for index in range(len(timestamps))],
        }
    )

    report = evaluate_holdout(
        frame,
        _PerfectTimestampPredictor(start),
        _manifest() | {"data_domain": "shenzhen_source_domain"},
        _metadata(),
        dataset_sha256="c" * 64,
        manifest_sha256="f" * 64,
    )

    assert report["quality_gate_passed"] is True
    assert report["deployment_eligible"] is False
    assert "customer_release_requires_hcmc_operational_holdout" in report["evidence_gaps"]


def test_quality_gate_fails_when_approved_sample_coverage_is_not_met() -> None:
    start = datetime(2026, 10, 1, 0, tzinfo=UTC)
    timestamps = [start + timedelta(minutes=5 * index) for index in range(67)]
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "entity_id": ["station-1"] * len(timestamps),
            "occupancy_ratio": [(index % 20) / 20 for index in range(len(timestamps))],
        }
    )

    report = evaluate_holdout(
        frame,
        _PerfectTimestampPredictor(start),
        _manifest()
        | {
            "sample_policy": {
                "minimum_stations": 2,
                "minimum_samples_per_horizon": 1,
                "approved_by": "Model Review Board",
                "approval_reference": "ML-RELEASE-123",
            }
        },
        _metadata(),
        dataset_sha256="c" * 64,
        manifest_sha256="f" * 64,
    )

    assert report["mae_gate_passed"] is True
    assert report["calibration_gate_passed"] is True
    assert report["sample_coverage_gate_passed"] is False
    assert report["quality_gate_passed"] is False
    assert report["deployment_eligible"] is False
