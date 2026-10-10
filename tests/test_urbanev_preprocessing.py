from __future__ import annotations

import csv
import json
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from scripts.preprocess_urbanev import (
    PreprocessingConfig,
    UrbanEVPreprocessor,
    sha256_file,
)


def _write_archive(path: Path, rows: list[dict[str, str]]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "UrbanEVDataset/20220901-20230228_station-raw/station_information.csv",
            "station_id,charge_count\n1001,8\n",
        )
        from io import StringIO

        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=["time", "busy", "idle"])
        writer.writeheader()
        writer.writerows(rows)
        archive.writestr(
            "UrbanEVDataset/20220901-20230228_station-processed/1001.csv",
            output.getvalue(),
        )


def _config(tmp_path: Path, archive_path: Path) -> PreprocessingConfig:
    return PreprocessingConfig(
        raw_zip_path=archive_path,
        output_dir=tmp_path / "processed",
        report_dir=tmp_path / "reports",
        num_stations=0,
        source_manifest_path=None,
        train_end="2022-09-01 00:05:00",
        val_start="2022-09-01 00:10:00",
        val_end="2022-09-01 00:10:00",
        test_start="2022-09-01 00:15:00",
        test_end="2022-09-01 00:25:00",
    )


def _rows(*, missing_busy: bool = False) -> list[dict[str, str]]:
    start = datetime(2022, 9, 1)
    rows = []
    for index in range(6):
        rows.append(
            {
                "time": (start + timedelta(minutes=5 * index)).strftime("%Y-%m-%d %H:%M:%S"),
                "busy": "" if missing_busy and index == 2 else str(index % 2),
                "idle": "1",
            }
        )
    return rows


def test_preprocessor_keeps_temporal_splits_and_source_provenance(tmp_path: Path) -> None:
    archive_path = tmp_path / "urbanev.zip"
    _write_archive(archive_path, _rows())
    preprocessor = UrbanEVPreprocessor(_config(tmp_path, archive_path))

    metadata = preprocessor.run()

    output = pd.read_parquet(tmp_path / "processed" / "urbanev_processed.parquet")
    assert output["split"].value_counts().to_dict() == {"train": 2, "test": 3, "val": 1}
    assert output["occupancy_ratio"].between(0, 1).all()
    manifest = json.loads((tmp_path / "processed" / "split_manifest.json").read_text())
    assert manifest["source_domain"].startswith("Shenzhen")
    assert manifest["source_archive_sha256"] == sha256_file(archive_path)
    assert metadata["source_manifest"] is None


def test_preprocessor_rejects_missing_occupancy_instead_of_filling_zero(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "urbanev.zip"
    _write_archive(archive_path, _rows(missing_busy=True))
    preprocessor = UrbanEVPreprocessor(_config(tmp_path, archive_path))

    with zipfile.ZipFile(archive_path) as archive:
        with pytest.raises(ValueError, match="missing/non-numeric"):
            preprocessor.process_station(archive, "1001")


def test_preprocessor_rejects_temporal_gaps(tmp_path: Path) -> None:
    archive_path = tmp_path / "urbanev.zip"
    rows = _rows()
    rows.pop(3)
    _write_archive(archive_path, rows)
    preprocessor = UrbanEVPreprocessor(_config(tmp_path, archive_path))

    with zipfile.ZipFile(archive_path) as archive:
        with pytest.raises(ValueError, match="continuous 5-minute cadence"):
            preprocessor.process_station(archive, "1001")


def test_preprocessor_fails_closed_on_source_checksum_mismatch(tmp_path: Path) -> None:
    archive_path = tmp_path / "urbanev.zip"
    _write_archive(archive_path, _rows())
    manifest_path = tmp_path / "source_manifest.json"
    manifest_path.write_text(json.dumps({"sha256": "0" * 64}), encoding="utf-8")
    config = _config(tmp_path, archive_path)
    config = PreprocessingConfig(
        **{**config.__dict__, "source_manifest_path": manifest_path}
    )
    preprocessor = UrbanEVPreprocessor(config)

    with pytest.raises(ValueError, match="does not match source_manifest"):
        preprocessor.run()
