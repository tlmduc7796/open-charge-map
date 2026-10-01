#!/usr/bin/env python3
"""Verify the immutable external UrbanEV archive and its provenance manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
DATASET_DIR = ROOT_DIR / "ml" / "data" / "external" / "urbanev"
MANIFEST_PATH = DATASET_DIR / "source_manifest.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--deep",
        action="store_true",
        help="Decompress every ZIP member; slow but checks per-member integrity.",
    )
    args = parser.parse_args()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    archive = DATASET_DIR / "raw" / str(manifest["archive"])
    if not archive.is_file():
        raise FileNotFoundError(f"UrbanEV archive not found: {archive}")
    if archive.stat().st_size != manifest["size_bytes"]:
        raise ValueError("UrbanEV archive size differs from source manifest")
    if sha256(archive) != manifest["sha256"]:
        raise ValueError("UrbanEV archive SHA-256 differs from source manifest")
    with zipfile.ZipFile(archive) as handle:
        member_count = len(handle.infolist())
        bad_member = handle.testzip() if args.deep else None
    if bad_member:
        raise ValueError(f"UrbanEV ZIP has corrupt member: {bad_member}")
    if member_count != manifest["zip_member_count"]:
        raise ValueError("UrbanEV ZIP member count differs from source manifest")
    print(
        json.dumps(
            {
                "status": "PASS",
                "dataset": manifest["dataset"],
                "archive": str(archive),
                "sha256": manifest["sha256"],
                "zip_member_count": member_count,
                "deep_zip_member_test": args.deep,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
