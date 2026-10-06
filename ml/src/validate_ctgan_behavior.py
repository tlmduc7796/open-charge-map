#!/usr/bin/env python3
"""Compare a CTGAN behavior sampler with its held-out ACN source distribution.

This is a fidelity diagnostic, not proof that generated behavior represents
Vietnam.  It prevents a broken source-domain sampler from silently feeding the
downstream topology-conditioned simulator.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from .train_ctgan_behavior import FEATURES
except ImportError:  # pragma: no cover - direct CLI invocation.
    from train_ctgan_behavior import FEATURES


CONTINUOUS = (
    "stay_min",
    "charge_min",
    "energy_kwh",
    "requested_energy_kwh",
    "minutes_available",
)
CATEGORICAL = ("arrival_hour", "arrival_weekday")


def _total_variation(source: pd.Series, synthetic: pd.Series) -> float:
    values = pd.concat(
        [source.astype("string"), synthetic.astype("string")], ignore_index=True
    ).unique()
    source_p = source.astype("string").value_counts(normalize=True).reindex(values, fill_value=0)
    synthetic_p = (
        synthetic.astype("string").value_counts(normalize=True).reindex(values, fill_value=0)
    )
    return float(0.5 * (source_p - synthetic_p).abs().sum())


def validate(dataset_path: Path, model_path: Path, output_path: Path) -> dict[str, object]:
    try:
        from sdv.single_table import CTGANSynthesizer
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Install ml/requirements.txt before validating CTGAN") from exc
    source = pd.read_parquet(dataset_path)
    held_out = source.loc[source["split"] == "test", list(FEATURES)].dropna().reset_index(drop=True)
    if held_out.empty:
        raise ValueError("The CTGAN behavior dataset needs a non-empty test split")
    sampled = (
        CTGANSynthesizer.load(model_path).sample(num_rows=len(held_out)).loc[:, list(FEATURES)]
    )
    categorical = {
        field: {
            "total_variation_distance": round(_total_variation(held_out[field], sampled[field]), 5)
        }
        for field in CATEGORICAL
    }
    continuous = {}
    for field in CONTINUOUS:
        source_values = pd.to_numeric(held_out[field], errors="coerce").dropna()
        sample_values = pd.to_numeric(sampled[field], errors="coerce").dropna()
        source_quantiles = np.quantile(source_values, [0.1, 0.5, 0.9])
        sample_quantiles = np.quantile(sample_values, [0.1, 0.5, 0.9])
        continuous[field] = {
            "source_p10_p50_p90": [round(float(value), 4) for value in source_quantiles],
            "synthetic_p10_p50_p90": [round(float(value), 4) for value in sample_quantiles],
            "median_relative_error": round(
                float(
                    abs(sample_quantiles[1] - source_quantiles[1])
                    / max(abs(source_quantiles[1]), 1)
                ),
                5,
            ),
            "synthetic_negative_rate": round(float((sample_values < 0).mean()), 5),
        }
    result = {
        "dataset": str(dataset_path),
        "model": str(model_path),
        "held_out_records": int(len(held_out)),
        "categorical": categorical,
        "continuous": continuous,
        "interpretation": "source-domain fidelity only; not evidence of Vietnamese behavior",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(validate(args.dataset, args.model, args.output), indent=2))


if __name__ == "__main__":
    main()
