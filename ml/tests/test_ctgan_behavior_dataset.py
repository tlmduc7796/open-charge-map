from __future__ import annotations

import json

import pandas as pd

from ml.src.build_ctgan_behavior_dataset import build_behavior_dataset
from ml.src.data_pipeline.splits import TemporalSplitConfig


def test_behavior_dataset_excludes_identifiers_and_keeps_temporal_splits(tmp_path):
    source = tmp_path / "acn.json"
    records = []
    for day in (1, 2, 3):
        records.append(
            {
                "_id": f"private-{day}",
                "userID": "private-user",
                "stationID": "private-port",
                "connectionTime": f"2021-01-0{day}T00:00:00Z",
                "disconnectTime": f"2021-01-0{day}T01:00:00Z",
                "doneChargingTime": f"2021-01-0{day}T00:45:00Z",
                "kWhDelivered": 5.0,
                "userInputs": [{"kWhRequested": 10, "minutesAvailable": 90}],
            }
        )
    source.write_text(json.dumps({"_items": records}), encoding="utf-8")
    output = tmp_path / "behavior.parquet"

    build_behavior_dataset(
        source,
        output,
        split_config=TemporalSplitConfig("2021-01-01T23:59:00Z", "2021-01-02T23:59:00Z"),
    )
    result = pd.read_parquet(output)

    assert set(result["split"]) == {"train", "val", "test"}
    assert {"userID", "stationID", "_id", "disconnectTime"}.isdisjoint(result.columns)
    assert {"arrival_hour", "stay_min", "energy_kwh"}.issubset(result.columns)
