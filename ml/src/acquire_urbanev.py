#!/usr/bin/env python3
"""Acquire and fingerprint the immutable official UrbanEV dataset archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
URBANEVDIR = ROOT / "ml" / "data" / "external" / "urbanev"
RAW_DIR = URBANEVDIR / "raw"
ARCHIVE = RAW_DIR / "UrbanEVDataset.zip"
FILE_ID = "1OEpo-XDocd33aK3MbgDt9S5bcqwiAFPQ"
SOURCE_URL = f"https://drive.usercontent.google.com/download?id={FILE_ID}&export=download&confirm=t"
LANDING_PAGE = "https://github.com/IntelligentSystemsLab/UrbanEV"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(destination: Path) -> None:
    part = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "SmartEVJourney/0.1"})
    with urllib.request.urlopen(request, timeout=120) as response, part.open("wb") as output:
        shutil.copyfileobj(response, output, length=1024 * 1024)
    part.replace(destination)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--force", action="store_true", help="Download again even when the archive exists"
    )
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    if args.force or not ARCHIVE.exists():
        download(ARCHIVE)

    with zipfile.ZipFile(ARCHIVE) as archive:
        members = archive.infolist()
        bad_member = archive.testzip()
        if bad_member:
            raise RuntimeError(f"Corrupt ZIP member: {bad_member}")
        member_names = [member.filename for member in members]

    acquired_at = datetime.now(UTC).astimezone().isoformat(timespec="seconds")
    checksum = sha256(ARCHIVE)
    station_processed_prefix = "UrbanEVDataset/20220901-20230228_station-processed/"
    station_raw_prefix = "UrbanEVDataset/20220901-20230228_station-raw/charge_5min/"
    station_level_hints = [
        name
        for name in [
            station_processed_prefix,
            station_raw_prefix,
            "UrbanEVDataset/20220901-20230228_station-raw/station_information.csv",
            "UrbanEVDataset/20220901-20230228_station-raw/pile_rated_power.csv",
            "UrbanEVDataset/20220901-20230228_zone-cleaned-aggregated/charge_5min/occupancy.csv",
        ]
        if name in member_names
    ]
    manifest = {
        "dataset": "UrbanEV",
        "archive": ARCHIVE.name,
        "source_landing_page": LANDING_PAGE,
        "source_url": SOURCE_URL,
        "google_drive_file_id": FILE_ID,
        "acquired_at": acquired_at,
        "size_bytes": ARCHIVE.stat().st_size,
        "sha256": checksum,
        "zip_member_count": len(member_names),
        "zip_test": "PASS",
        "station_level_member_hints": station_level_hints,
        "station_processed_csv_count": sum(
            name.startswith(station_processed_prefix) and name.endswith(".csv")
            for name in member_names
        ),
        "station_raw_5min_csv_count": sum(
            name.startswith(station_raw_prefix) and name.endswith(".csv") for name in member_names
        ),
        "raw_policy": "Do not edit or extract-and-overwrite this archive manually.",
    }
    (URBANEVDIR / "source_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    hints = (
        "\n".join(f"- `{name}`" for name in station_level_hints)
        or "- Không phát hiện theo tên file; kiểm tra ở Phase 03."
    )
    (URBANEVDIR / "source_manifest.md").write_text(
        "# UrbanEV source manifest\n\n"
        f"- Nguồn chính thức: {LANDING_PAGE}\n"
        f"- File Drive: `{FILE_ID}`\n"
        f"- Ngày tải: `{acquired_at}`\n"
        f"- Archive: `raw/{ARCHIVE.name}` ({ARCHIVE.stat().st_size} bytes)\n"
        f"- SHA-256: `{checksum}`\n"
        f"- ZIP integrity: `PASS` ({len(member_names)} members)\n"
        "- License theo upstream: `CC0-1.0`\n"
        "- Chính sách raw: không chỉnh sửa thủ công archive; "
        "mọi biến đổi được thực hiện ở Phase 03.\n\n"
        "## File có dấu hiệu station-level / 5-minute\n\n"
        f"{hints}\n",
        encoding="utf-8",
    )
    print(
        "UrbanEV ready: "
        f"{manifest['size_bytes']} bytes, {manifest['zip_member_count']} ZIP members, "
        f"SHA-256 {manifest['sha256']}"
    )


if __name__ == "__main__":
    main()
