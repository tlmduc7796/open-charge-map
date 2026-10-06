#!/usr/bin/env python3
"""Train a source-domain CTGAN behavior sampler; never a serving model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

FEATURES = (
    "arrival_hour",
    "arrival_weekday",
    "stay_min",
    "charge_min",
    "energy_kwh",
    "requested_energy_kwh",
    "minutes_available",
)


def train(dataset_path: Path, model_path: Path, *, epochs: int) -> dict[str, object]:
    try:
        from sdv.metadata import SingleTableMetadata
        from sdv.single_table import CTGANSynthesizer
    except ImportError as exc:
        raise RuntimeError("Install ml/requirements.txt to train the CTGAN sampler") from exc
    source = pd.read_parquet(dataset_path)
    train_frame = source.loc[source["split"] == "train", list(FEATURES)].dropna().copy()
    if len(train_frame) < 100:
        raise ValueError("CTGAN needs at least 100 complete training records")
    metadata = SingleTableMetadata()
    metadata.detect_from_dataframe(train_frame)
    for field in ("arrival_hour", "arrival_weekday"):
        metadata.update_column(column_name=field, sdtype="categorical")
    synthesizer = CTGANSynthesizer(metadata, epochs=epochs, verbose=False)
    # CTGAN delegates transforms to joblib with ``n_jobs=-1``.  On Windows
    # desktop sandboxes, even a joblib thread pool opens a multiprocessing pipe
    # and can be denied.  Its own synchronous transform is equivalent for this
    # small, seven-column behavior table, so use it only during this local fit.
    from ctgan.data_transformer import DataTransformer

    parallel_transform = DataTransformer._parallel_transform
    DataTransformer._parallel_transform = DataTransformer._synchronous_transform
    try:
        synthesizer.fit(train_frame)
    finally:
        DataTransformer._parallel_transform = parallel_transform
    model_path.parent.mkdir(parents=True, exist_ok=True)
    synthesizer.save(model_path)
    summary = {
        "model": str(model_path),
        "training_records": len(train_frame),
        "features": list(FEATURES),
        "source_domain": "ACN-Data Caltech",
        "usage": "behavior prior for synthetic evaluation only; not Vietnamese ground truth",
    }
    model_path.with_suffix(".meta.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=300)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"will_train": False, "features": list(FEATURES)}, indent=2))
        return
    print(json.dumps(train(args.dataset, args.model, epochs=args.epochs), indent=2))


if __name__ == "__main__":
    main()
