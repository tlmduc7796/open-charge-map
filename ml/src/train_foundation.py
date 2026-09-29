#!/usr/bin/env python3
"""Foundation-model fine-tuning gate and reproducible handoff plan.

Chronos and TimesFM are intentionally not hard-coded yet: their APIs, licenses
and GPU requirements must be pinned by the team after data approval. This script
prevents an agent from presenting a provider-specific experiment as production.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from .domain_schema import DEFAULT_SCHEMA_PATH, load_domain_schema
except ImportError:  # pragma: no cover - direct script invocation.
    from domain_schema import DEFAULT_SCHEMA_PATH, load_domain_schema


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA_PATH)
    parser.add_argument("--provider", choices=("chronos", "timesfm"), default="chronos")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    schema = load_domain_schema(args.schema)
    plan = schema.training_requirements("foundation_finetune")
    plan["provider"] = args.provider
    plan["required_before_execute"] = [
        "Pin the provider package/version and licence in a reviewed lockfile.",
        "Approve a GPU budget, dataset version and temporal benchmark.",
        "Implement the provider adapter against that pinned version.",
    ]
    if not args.execute:
        print(json.dumps({"will_train": False, **plan}, indent=2))
        return
    if not schema.profile("foundation_finetune").enabled:
        raise ValueError(
            "Foundation profile is disabled; follow DATA_HANDOFF.md before enabling it"
        )
    raise RuntimeError(
        "No provider adapter is pinned yet. This is intentional: choose Chronos or TimesFM "
        "after data/licence/GPU review, then implement and test that exact adapter."
    )


if __name__ == "__main__":
    main()
