#!/usr/bin/env python3
"""Build connector-aware aggregate states for a future Markov fallback."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:  # Supports package import and `python ml/src/...py`.
    from .data_pipeline.markov import build_markov_state_dataset
    from .data_pipeline.splits import TemporalSplitConfig
except ImportError:  # pragma: no cover - direct CLI invocation.
    from data_pipeline.markov import build_markov_state_dataset
    from data_pipeline.splits import TemporalSplitConfig


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port-status", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--train-end", required=True, help="ISO timestamp including timezone")
    parser.add_argument("--validation-end", required=True, help="ISO timestamp including timezone")
    args = parser.parse_args()
    print(
        json.dumps(
            build_markov_state_dataset(
                args.port_status,
                args.output,
                split_config=TemporalSplitConfig(args.train_end, args.validation_end),
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
