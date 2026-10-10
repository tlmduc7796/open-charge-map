#!/usr/bin/env python3
"""Phase 03: UrbanEV dataset preprocessing, temporal split, and artifact generation."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import time
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("preprocess_urbanev")

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ZIP_PATH = ROOT_DIR / "data" / "ml" / "urbanev" / "raw" / "UrbanEVDataset.zip"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "data" / "ml" / "urbanev" / "processed"
DEFAULT_REPORT_DIR = DEFAULT_OUTPUT_DIR
DEFAULT_SOURCE_MANIFEST = ROOT_DIR / "data" / "ml" / "urbanev" / "source_manifest.json"

# Canonical temporal boundaries (strictly non-overlapping)
# Total: 2022-09-01 to 2023-02-28 (181 days, 52,128 steps)
TRAIN_END = "2023-01-15 23:55:00"  # ~75.7% (137 days)
VAL_START = "2023-01-16 00:00:00"
VAL_END = "2023-01-31 23:55:00"    # ~8.8%  (16 days)
TEST_START = "2023-02-01 00:00:00"
TEST_END = "2023-02-28 23:55:00"   # ~15.5% (28 days)

CANONICAL_COLUMNS = [
    "timestamp",
    "entity_id",
    "entity_level",
    "interval_min",
    "total_ports",
    "occupied_ports",
    "occupancy_ratio",
    "split",
    "data_source",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class PreprocessingConfig:
    raw_zip_path: Path
    output_dir: Path
    report_dir: Path
    num_stations: int
    source_manifest_path: Path | None = DEFAULT_SOURCE_MANIFEST
    train_end: str = TRAIN_END
    val_start: str = VAL_START
    val_end: str = VAL_END
    test_start: str = TEST_START
    test_end: str = TEST_END


class UrbanEVPreprocessor:
    def __init__(self, config: PreprocessingConfig) -> None:
        self.config = config
        if not self.config.raw_zip_path.is_file():
            raise FileNotFoundError(f"Raw archive not found: {self.config.raw_zip_path}")
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        self.config.report_dir.mkdir(parents=True, exist_ok=True)

    def select_station_ids(self, zip_handle: zipfile.ZipFile) -> list[str]:
        info_path = "UrbanEVDataset/20220901-20230228_station-raw/station_information.csv"
        with zip_handle.open(info_path) as f:
            info_df = pd.read_csv(f)

        processed_names = {
            n.split("/")[-1].replace(".csv", "")
            for n in zip_handle.namelist()
            if "station-processed/" in n and n.endswith(".csv")
        }

        # Filter stations with valid processed series
        valid_info = info_df[info_df["station_id"].astype(str).isin(processed_names)].copy()
        logger.info(
            "Found %d candidate stations in station_information matching processed CSVs",
            len(valid_info),
        )

        if self.config.num_stations <= 0 or self.config.num_stations >= len(valid_info):
            selected = sorted(valid_info["station_id"].astype(str).tolist())
            logger.info("Using all %d available stations", len(selected))
            return selected

        # Stratified sampling across capacity tiers
        bins = [0, 6, 15, 30, 200]
        labels = ["small", "medium", "large", "superhub"]
        valid_info["tier"] = pd.cut(valid_info["charge_count"], bins=bins, labels=labels)

        # Proportions: 20% small, 40% medium, 30% large, 10% superhub
        weights = {"small": 0.20, "medium": 0.40, "large": 0.30, "superhub": 0.10}
        target_counts = {
            tier: max(1, int(round(self.config.num_stations * w)))
            for tier, w in weights.items()
        }
        diff = self.config.num_stations - sum(target_counts.values())
        target_counts["medium"] += diff

        selected_ids: list[str] = []
        for tier, count in target_counts.items():
            tier_df = valid_info[valid_info["tier"] == tier].sort_values("station_id")
            tier_stations = tier_df["station_id"].astype(str).tolist()
            if not tier_stations:
                continue
            idx = np.linspace(0, len(tier_stations) - 1, min(count, len(tier_stations)), dtype=int)
            selected_ids.extend([tier_stations[i] for i in idx])

        selected_ids = sorted(list(dict.fromkeys(selected_ids)))
        logger.info("Selected %d stratified stations: %s...", len(selected_ids), selected_ids[:5])
        return selected_ids

    def process_station(
        self,
        zip_handle: zipfile.ZipFile,
        station_id: str,
    ) -> pd.DataFrame:
        member_name = f"UrbanEVDataset/20220901-20230228_station-processed/{station_id}.csv"
        with zip_handle.open(member_name) as f:
            df = pd.read_csv(f, usecols=["time", "busy", "idle"])

        if len(df) == 0:
            raise ValueError(f"Station {station_id} has empty data")

        df["busy"] = pd.to_numeric(df["busy"], errors="coerce")
        df["idle"] = pd.to_numeric(df["idle"], errors="coerce")
        if df[["busy", "idle"]].isna().any().any():
            raise ValueError(f"Station {station_id} contains missing/non-numeric occupancy values")
        if (df[["busy", "idle"]] < 0).any().any():
            raise ValueError(f"Station {station_id} contains negative occupancy counts")
        timestamps = pd.to_datetime(df["time"], errors="raise")
        if timestamps.isna().any() or timestamps.duplicated().any():
            raise ValueError(f"Station {station_id} contains null or duplicate timestamps")
        if not timestamps.is_monotonic_increasing:
            raise ValueError(f"Station {station_id} timestamps are not chronological")
        cadence_ns = timestamps.diff().dropna().astype("int64")
        if not cadence_ns.eq(5 * 60 * 1_000_000_000).all():
            raise ValueError(f"Station {station_id} does not have a continuous 5-minute cadence")

        total_ports = df["busy"] + df["idle"]
        cap_val = int(round(total_ports.median()))
        if cap_val <= 0:
            raise ValueError(f"Station {station_id} has non-positive capacity: {cap_val}")

        df["total_ports"] = cap_val
        df["occupied_ports"] = df["busy"].clip(lower=0.0, upper=cap_val)
        df["occupancy_ratio"] = (df["occupied_ports"] / cap_val).clip(lower=0.0, upper=1.0)

        df["timestamp"] = timestamps
        df["entity_id"] = f"urbanev_{station_id}"
        df["entity_level"] = "station"
        df["interval_min"] = 5
        df["data_source"] = "urbanev"

        time_col = df["timestamp"]
        conditions = [
            time_col <= pd.Timestamp(self.config.train_end),
            (time_col >= pd.Timestamp(self.config.val_start))
            & (time_col <= pd.Timestamp(self.config.val_end)),
            (time_col >= pd.Timestamp(self.config.test_start))
            & (time_col <= pd.Timestamp(self.config.test_end)),
        ]
        choices = ["train", "val", "test"]
        df["split"] = np.select(conditions, choices, default="unassigned")
        if (df["split"] == "unassigned").any():
            raise ValueError(
                f"Station {station_id} has timestamps outside configured split windows"
            )

        return df[CANONICAL_COLUMNS]

    def run(self) -> dict[str, object]:
        start_time = time.perf_counter()
        logger.info("Opening raw archive: %s", self.config.raw_zip_path)
        archive_hash = sha256_file(self.config.raw_zip_path)
        if self.config.source_manifest_path is not None:
            source_manifest = json.loads(
                self.config.source_manifest_path.read_text(encoding="utf-8")
            )
            expected_hash = source_manifest.get("sha256")
            if not expected_hash or archive_hash != expected_hash:
                raise ValueError("UrbanEV archive SHA-256 does not match source_manifest.json")

        with zipfile.ZipFile(self.config.raw_zip_path) as z:
            station_ids = self.select_station_ids(z)
            dfs: list[pd.DataFrame] = []
            for i, st_id in enumerate(station_ids, 1):
                df_st = self.process_station(z, st_id)
                dfs.append(df_st)
                if i % 10 == 0 or i == len(station_ids):
                    logger.info("Processed %d/%d stations", i, len(station_ids))

        full_df = pd.concat(dfs, ignore_index=True)
        logger.info("Total concatenated records: %d", len(full_df))

        # Invariant validations
        if (full_df["occupied_ports"] < 0).any():
            raise ValueError("Negative occupied_ports detected")
        if (full_df["occupied_ports"] > full_df["total_ports"]).any():
            raise ValueError("Overcapacity detected")
        if not full_df["occupancy_ratio"].between(0.0, 1.0).all():
            raise ValueError("occupancy_ratio must be bounded in [0, 1]")
        if full_df["timestamp"].isna().any():
            raise ValueError("Null timestamp detected")
        if not full_df["split"].isin(["train", "val", "test"]).all():
            raise ValueError("Invalid split label")

        # Temporal leakage check
        train_max = full_df[full_df["split"] == "train"]["timestamp"].max()
        val_min = full_df[full_df["split"] == "val"]["timestamp"].min()
        val_max = full_df[full_df["split"] == "val"]["timestamp"].max()
        test_min = full_df[full_df["split"] == "test"]["timestamp"].min()

        if not train_max < val_min or not val_max < test_min:
            raise ValueError("Temporal split boundaries overlap or are out of order")

        # Export dataset
        parquet_path = self.config.output_dir / "urbanev_processed.parquet"
        full_df.to_parquet(parquet_path, index=False, compression="snappy")
        mb_size = parquet_path.stat().st_size / (1024 * 1024)
        logger.info("Saved parquet: %s (%.2f MB)", parquet_path, mb_size)

        # Export small CSV sample for quick inspection
        sample_path = self.config.output_dir / "urbanev_processed_sample.csv"
        full_df.head(1000).to_csv(sample_path, index=False)

        # Build split manifest
        split_stats = {}
        for s in ["train", "val", "test"]:
            sub = full_df[full_df["split"] == s]
            split_stats[s] = {
                "record_count": int(len(sub)),
                "station_count": int(sub["entity_id"].nunique()),
                "min_timestamp": str(sub["timestamp"].min()),
                "max_timestamp": str(sub["timestamp"].max()),
                "mean_occupancy_ratio": float(round(sub["occupancy_ratio"].mean(), 4)),
                "std_occupancy_ratio": float(round(sub["occupancy_ratio"].std(), 4)),
                "median_occupancy_ratio": float(round(sub["occupancy_ratio"].median(), 4)),
            }

        split_manifest = {
            "source_dataset": "UrbanEV",
            "source_archive_sha256": archive_hash,
            "source_domain": "Shenzhen, China; not HCMC operational ground truth",
            "timestamp_timezone": "not specified in source; preserved as naive source timestamps",
            "created_at": datetime.now(UTC).isoformat(),
            "temporal_resolution_min": 5,
            "entity_level": "station",
            "total_records": len(full_df),
            "total_stations": full_df["entity_id"].nunique(),
            "station_ids": sorted(full_df["entity_id"].unique().tolist()),
            "splits": split_stats,
            "invariants_checked": [
                "occupied_ports >= 0",
                "occupied_ports <= total_ports",
                "0 <= occupancy_ratio <= 1",
                "train_max < val_min < test_min (no temporal leakage)",
                "zero out-of-scope features (no price, weather, POI, queue)",
            ],
        }
        manifest_path = self.config.output_dir / "split_manifest.json"
        manifest_text = json.dumps(split_manifest, indent=2, ensure_ascii=False) + "\n"
        manifest_path.write_text(manifest_text, encoding="utf-8")

        # Build preprocessing metadata
        meta = {
            "version": "1.0.0",
            "created_at": datetime.now(UTC).isoformat(),
            "elapsed_seconds": round(time.perf_counter() - start_time, 2),
            "parquet_file": parquet_path.name,
            "parquet_size_bytes": parquet_path.stat().st_size,
            "parquet_sha256": sha256_file(parquet_path),
            "canonical_columns": CANONICAL_COLUMNS,
            "source_manifest": self.config.source_manifest_path.relative_to(ROOT_DIR).as_posix()
            if self.config.source_manifest_path is not None
            and self.config.source_manifest_path.is_relative_to(ROOT_DIR)
            else self.config.source_manifest_path.name
            if self.config.source_manifest_path is not None
            else None,
            "config": {
                "num_stations": len(station_ids),
                "train_end": self.config.train_end,
                "val_start": self.config.val_start,
                "val_end": self.config.val_end,
                "test_start": self.config.test_start,
                "test_end": self.config.test_end,
            },
        }
        meta_path = self.config.output_dir / "preprocessing_meta.json"
        meta_text = json.dumps(meta, indent=2, ensure_ascii=False) + "\n"
        meta_path.write_text(meta_text, encoding="utf-8")

        # Build Markdown Validation Report
        r_tr = split_stats["train"]
        r_va = split_stats["val"]
        r_te = split_stats["test"]
        report_content = (
            "# Phase 03 — UrbanEV Preprocessing & Temporal Split Validation Report\n\n"
            "**Result:** `PASS`\n"
            f"**Validation Date:** `{datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}`\n"
            f"**Source Archive:** `{self.config.raw_zip_path.name}` (SHA-256: `{archive_hash}`)\n\n"
            "## 1. Summary Metrics\n"
            f"- **Selected Stations:** {split_manifest['total_stations']}\n"
            f"- **Total Records:** {split_manifest['total_records']:,} rows\n"
            "- **Temporal Resolution:** 5 minutes\n"
            f"- **Processed Artifact:** `{parquet_path.name}` ({mb_size:.2f} MB)\n"
            f"- **Execution Time:** {meta['elapsed_seconds']}s\n\n"
            "## 2. Temporal Split Distribution\n"
            "| Split | Records | Range | Mean Occupancy | Std Occupancy |\n"
            "|---|---|---|---|---|\n"
            f"| **Train** | {r_tr['record_count']:,} | "
            f"`{r_tr['min_timestamp']}` → `{r_tr['max_timestamp']}` | "
            f"{r_tr['mean_occupancy_ratio']} | {r_tr['std_occupancy_ratio']} |\n"
            f"| **Validation** | {r_va['record_count']:,} | "
            f"`{r_va['min_timestamp']}` → `{r_va['max_timestamp']}` | "
            f"{r_va['mean_occupancy_ratio']} | {r_va['std_occupancy_ratio']} |\n"
            f"| **Test** | {r_te['record_count']:,} | "
            f"`{r_te['min_timestamp']}` → `{r_te['max_timestamp']}` | "
            f"{r_te['mean_occupancy_ratio']} | {r_te['std_occupancy_ratio']} |\n\n"
            "## 3. Exit Gate Invariants\n"
            "- [x] Preprocessing runs reproducibly from raw via single command.\n"
            "- [x] Zero temporal leakage between train/val/test "
            "(`train_max < val_min < test_min`).\n"
            "- [x] `occupied_ports >= 0` for all 100% rows.\n"
            "- [x] `occupied_ports <= total_ports` for all 100% rows.\n"
            "- [x] Target `occupancy_ratio` is strictly bounded in `[0.0, 1.0]`.\n"
            "- [x] No queue, synthetic wait, price, weather, or POI features included.\n"
            "- [x] Scaler/normalization not required for target as ratio is inherently in [0, 1].\n"
            "- [x] `split_manifest.json` and `preprocessing_meta.json` generated "
            "alongside the dataset.\n"
        )
        report_path = self.config.report_dir / "phase3_preprocessing_report.md"
        report_path.write_text(report_content, encoding="utf-8")
        logger.info("Saved validation report: %s", report_path)

        return meta


def main() -> None:
    parser = argparse.ArgumentParser(description="Preprocess UrbanEV dataset for Phase 03.")
    parser.add_argument(
        "--raw-zip",
        type=Path,
        default=DEFAULT_ZIP_PATH,
        help="Path to UrbanEVDataset.zip",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory to save processed data and provenance",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=DEFAULT_REPORT_DIR,
        help="Directory to save the preprocessing validation report",
    )
    parser.add_argument(
        "--stations-count",
        type=int,
        default=50,
        help="Number of representative stations to preprocess (default: 50). Pass 0 or -1 for all.",
    )
    parser.add_argument(
        "--skip-source-check",
        action="store_true",
        help="Skip archive checksum verification (only for isolated test fixtures).",
    )
    args = parser.parse_args()

    cfg = PreprocessingConfig(
        raw_zip_path=args.raw_zip,
        output_dir=args.output_dir,
        report_dir=args.report_dir,
        num_stations=args.stations_count,
        source_manifest_path=None if args.skip_source_check else DEFAULT_SOURCE_MANIFEST,
    )
    preprocessor = UrbanEVPreprocessor(cfg)
    meta = preprocessor.run()
    print(f"\n[DONE] Preprocessing succeeded in {meta['elapsed_seconds']}s.")
    print(f"Artifact: {args.output_dir / str(meta['parquet_file'])}")


if __name__ == "__main__":
    main()
