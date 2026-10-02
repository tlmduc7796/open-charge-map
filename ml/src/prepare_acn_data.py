#!/usr/bin/env python3
"""Normalize downloaded ACN exports; it never calls the protected ACN API."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:  # Supports package import and `python ml/src/...py`.
    from .data_pipeline.adapters import normalize_acn_sessions, normalize_session_telemetry
    from .data_pipeline.manifests import write_dataset_manifest
except ImportError:  # pragma: no cover - direct CLI invocation.
    from data_pipeline.adapters import normalize_acn_sessions, normalize_session_telemetry
    from data_pipeline.manifests import write_dataset_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", required=True, type=Path, help="ACN JSON/CSV/Parquet export")
    parser.add_argument("--sessions-output", required=True, type=Path)
    parser.add_argument("--telemetry", type=Path, help="Optional flat telemetry export")
    parser.add_argument("--telemetry-output", type=Path)
    parser.add_argument("--default-station-id", default="ACN_UNKNOWN")
    args = parser.parse_args()
    if (args.telemetry is None) != (args.telemetry_output is None):
        raise ValueError("Provide --telemetry and --telemetry-output together")
    sessions = normalize_acn_sessions(args.sessions, default_station_id=args.default_station_id)
    args.sessions_output.parent.mkdir(parents=True, exist_ok=True)
    sessions.to_parquet(args.sessions_output, index=False)
    session_manifest = write_dataset_manifest(
        args.sessions_output,
        sessions,
        dataset_kind="canonical_sessions",
        source_paths=[args.sessions],
        split_column="not_a_split",
        extra={"adapter": "acn_data", "disconnect_is_port_release": True},
    )
    result: dict[str, object] = {
        "sessions_output": str(args.sessions_output),
        "sessions_manifest": str(session_manifest),
        "sessions": int(len(sessions)),
        "censored_sessions": int(sessions["is_censored"].sum()),
    }
    if args.telemetry is not None:
        telemetry = normalize_session_telemetry(args.telemetry, source="acn_data")
        args.telemetry_output.parent.mkdir(parents=True, exist_ok=True)
        telemetry.to_parquet(args.telemetry_output, index=False)
        telemetry_manifest = write_dataset_manifest(
            args.telemetry_output,
            telemetry,
            dataset_kind="canonical_session_telemetry",
            source_paths=[args.telemetry],
            split_column="not_a_split",
        )
        result.update(
            {
                "telemetry_output": str(args.telemetry_output),
                "telemetry_manifest": str(telemetry_manifest),
                "telemetry_rows": int(len(telemetry)),
            }
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
