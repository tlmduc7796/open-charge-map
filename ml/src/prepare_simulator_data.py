#!/usr/bin/env python3
"""Normalize synthetic simulator sessions for offline evaluation only.

The output is canonical enough for adapter, RDM-label and DES replay tests.
It is explicitly not an approved production-training or serving dataset.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:  # Supports package import and `python ml/src/...py`.
    from .data_pipeline.adapters import normalize_simulator_sessions
    from .data_pipeline.manifests import write_dataset_manifest
except ImportError:  # pragma: no cover - direct script invocation.
    from data_pipeline.adapters import normalize_simulator_sessions
    from data_pipeline.manifests import write_dataset_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", required=True, type=Path, help="Simulator sessions.csv")
    parser.add_argument("--ports", required=True, type=Path, help="Simulator ports.csv")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    sessions = normalize_simulator_sessions(args.sessions, args.ports)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sessions.to_parquet(args.output, index=False)
    manifest = write_dataset_manifest(
        args.output,
        sessions,
        dataset_kind="canonical_sessions",
        source_paths=[args.sessions, args.ports],
        split_column="not_a_split",
        extra={
            "adapter": "simulator_hcmc",
            "synthetic": True,
            "training_eligibility": "evaluation_only",
            "disconnect_is_port_release": True,
        },
    )
    print(
        json.dumps(
            {
                "sessions_output": str(args.output),
                "sessions_manifest": str(manifest),
                "sessions": int(len(sessions)),
                "training_eligibility": "evaluation_only",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
