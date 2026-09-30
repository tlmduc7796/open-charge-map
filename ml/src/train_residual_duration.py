#!/usr/bin/env python3
"""Plan the telemetry-gated residual charging-duration model (RDM).

This is intentionally a training gate, not a synthetic-model generator.  The
future model predicts remaining charging minutes for a *live session*; DES uses
that value only when a station provider did not report it directly.
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
    "remaining_charge_min",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA_PATH)
    parser.add_argument(
        "--dataset", type=Path, default=ROOT_DIR / "ml/artifacts/session_training.parquet"
    )
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    schema = load_domain_schema(args.schema)
    plan = {
        "will_train": args.execute,
        "dataset": str(args.dataset),
        "required_columns": REQUIRED_COLUMNS,
        "target": "remaining_charge_min",
        "split_rule": (
            "split by completed session end time; never mix rows of one session across splits"
        ),
        "serving_rule": (
            "provider-reported duration wins; RDM needs calibration and freshness monitoring"
        ),
        **schema.training_requirements("residual_duration"),
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
