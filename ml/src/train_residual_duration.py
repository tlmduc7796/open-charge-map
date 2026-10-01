#!/usr/bin/env python3
"""Plan the telemetry-gated residual port-release-duration model (RDM).

This is intentionally a training gate, not a synthetic-model generator.  The
future model predicts remaining minutes until a connected EV unplugs; DES uses
that port-release value only when a station provider did not report it directly.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from .domain_schema import DEFAULT_SCHEMA_PATH, load_domain_schema
except ImportError:  # pragma: no cover - direct script invocation.
    from domain_schema import DEFAULT_SCHEMA_PATH, load_domain_schema

ROOT_DIR = Path(__file__).resolve().parents[2]
REQUIRED_COLUMNS = (
    "session_id",
    "entity_id",
    "port_id",
    "timestamp",
    "session_elapsed_min",
    "energy_delivered_kwh",
    "current_power_kw",
    "done_charging_at",
    "disconnect_at",
    "remaining_port_release_min",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA_PATH)
    parser.add_argument(
        "--dataset", type=Path, default=ROOT_DIR / "ml/data/features/session_training.parquet"
    )
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    schema = load_domain_schema(args.schema)
    plan = {
        "will_train": args.execute,
        "dataset": str(args.dataset),
        **schema.training_requirements("residual_duration"),
        "required_columns": REQUIRED_COLUMNS,
        "target": "remaining_port_release_min",
        "target_semantics": (
            "disconnect_at (physical port release), not done_charging_at (last power draw)"
        ),
        "split_rule": ("split by disconnect_at; never mix rows of one session across splits"),
        "serving_rule": (
            "Provider-reported port-release duration wins; RDM needs calibration "
            "and freshness monitoring."
        ),
    }
    if not args.execute:
        print(json.dumps(plan, indent=2))
        return
    if not schema.profile("residual_duration").enabled:
        raise ValueError(
            "Residual-duration profile is disabled: approve real session telemetry and "
            "the ground-truth end-time contract before implementing a training run."
        )
    raise NotImplementedError(
        "RDM execution is intentionally blocked until the approved schema defines "
        "categorical encoding, privacy retention and a benchmark protocol."
    )


if __name__ == "__main__":
    main()
