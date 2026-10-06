#!/usr/bin/env python3
"""Normalize approved operator exports before building a live-safe RDM dataset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:  # Supports package import and direct script invocation.
    from .data_pipeline.adapters import normalize_operator_sessions, normalize_session_telemetry
    from .data_pipeline.manifests import write_dataset_manifest
except ImportError:  # pragma: no cover
    from data_pipeline.adapters import normalize_operator_sessions, normalize_session_telemetry
    from data_pipeline.manifests import write_dataset_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", required=True, type=Path)
    parser.add_argument("--telemetry", required=True, type=Path)
    parser.add_argument(
        "--source", required=True, help="Named, non-synthetic operator/provider source"
    )
    parser.add_argument("--sessions-output", required=True, type=Path)
    parser.add_argument("--telemetry-output", required=True, type=Path)
    args = parser.parse_args()

    sessions = normalize_operator_sessions(args.sessions, source=args.source)
    telemetry = normalize_session_telemetry(args.telemetry, source=args.source)
    for path, frame in ((args.sessions_output, sessions), (args.telemetry_output, telemetry)):
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)
    session_manifest = write_dataset_manifest(
        args.sessions_output,
        sessions,
        dataset_kind="canonical_operator_sessions",
        source_paths=[args.sessions],
        split_column="not_a_split",
        extra={"source": args.source, "synthetic_data_forbidden": True},
    )
    telemetry_manifest = write_dataset_manifest(
        args.telemetry_output,
        telemetry,
        dataset_kind="canonical_operator_telemetry",
        source_paths=[args.telemetry],
        split_column="not_a_split",
        extra={"source": args.source, "synthetic_data_forbidden": True},
    )
    print(
        json.dumps(
            {
                "sessions": int(len(sessions)),
                "telemetry_rows": int(len(telemetry)),
                "censored_sessions": int(sessions["is_censored"].sum()),
                "sessions_manifest": str(session_manifest),
                "telemetry_manifest": str(telemetry_manifest),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
