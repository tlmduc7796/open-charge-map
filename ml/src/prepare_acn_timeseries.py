#!/usr/bin/env python3
"""Convert ACN nested charging-current exports to canonical RDM inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from .data_pipeline.acn import normalize_acn_raw_timeseries
    from .data_pipeline.manifests import write_dataset_manifest
except ImportError:  # pragma: no cover
    from data_pipeline.acn import normalize_acn_raw_timeseries
    from data_pipeline.manifests import write_dataset_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, nargs="+", required=True)
    parser.add_argument("--sessions-output", type=Path, required=True)
    parser.add_argument("--telemetry-output", type=Path, required=True)
    parser.add_argument("--voltage-v", type=float, default=208.0)
    parser.add_argument("--cadence", default="5min")
    args = parser.parse_args()
    sessions, telemetry, summary = normalize_acn_raw_timeseries(
        args.input, voltage_v=args.voltage_v, cadence=args.cadence
    )
    for path, frame in ((args.sessions_output, sessions), (args.telemetry_output, telemetry)):
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)
    session_manifest = write_dataset_manifest(
        args.sessions_output,
        sessions,
        dataset_kind="canonical_sessions",
        source_paths=args.input,
        split_column="not_a_split",
        extra={"adapter": "acn_raw_timeseries", "disconnect_is_port_release": True},
    )
    telemetry_manifest = write_dataset_manifest(
        args.telemetry_output,
        telemetry,
        dataset_kind="canonical_session_telemetry",
        source_paths=args.input,
        split_column="not_a_split",
        extra={"adapter": "acn_raw_timeseries", "power_semantics": "estimated_from_current"},
    )
    print(
        json.dumps(
            {
                **summary,
                "sessions_manifest": str(session_manifest),
                "telemetry_manifest": str(telemetry_manifest),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
