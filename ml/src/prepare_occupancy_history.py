#!/usr/bin/env python3
"""Normalize one aggregate occupancy source and assign its temporal split."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:  # Supports package import and `python ml/src/...py`.
    from .data_pipeline.occupancy import prepare_occupancy_history
    from .data_pipeline.splits import TemporalSplitConfig
except ImportError:  # pragma: no cover - direct CLI invocation.
    from data_pipeline.occupancy import prepare_occupancy_history
    from data_pipeline.splits import TemporalSplitConfig


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source", required=True, help="e.g. urbanev, operator_ocpp")
    parser.add_argument("--train-end", required=True, help="ISO timestamp including timezone")
    parser.add_argument("--validation-end", required=True, help="ISO timestamp including timezone")
    args = parser.parse_args()
    print(
        json.dumps(
            prepare_occupancy_history(
                args.input,
                args.output,
                source=args.source,
                split_config=TemporalSplitConfig(args.train_end, args.validation_end),
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
