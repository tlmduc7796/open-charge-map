#!/usr/bin/env python3
"""Build split-safe supervised observations for an RDM/port-release model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:  # Supports package import and `python ml/src/...py`.
    from .data_pipeline.rdm import build_live_safe_rdm_dataset, build_rdm_dataset
    from .data_pipeline.splits import TemporalSplitConfig
except ImportError:  # pragma: no cover - direct CLI invocation.
    from data_pipeline.rdm import build_live_safe_rdm_dataset, build_rdm_dataset
    from data_pipeline.splits import TemporalSplitConfig


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", required=True, type=Path)
    parser.add_argument("--telemetry", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--train-end", required=True, help="ISO timestamp including timezone")
    parser.add_argument("--validation-end", required=True, help="ISO timestamp including timezone")
    parser.add_argument(
        "--port-inventory",
        type=Path,
        help="Enable the live-safe RDM profile with this operator port inventory CSV/Parquet.",
    )
    parser.add_argument("--local-timezone", default="Asia/Ho_Chi_Minh")
    args = parser.parse_args()
    print(
        json.dumps(
            (
                build_live_safe_rdm_dataset(
                    args.sessions,
                    args.telemetry,
                    args.port_inventory,
                    args.output,
                    split_config=TemporalSplitConfig(args.train_end, args.validation_end),
                    local_timezone=args.local_timezone,
                )
                if args.port_inventory
                else build_rdm_dataset(
                    args.sessions,
                    args.telemetry,
                    args.output,
                    split_config=TemporalSplitConfig(args.train_end, args.validation_end),
                )
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
