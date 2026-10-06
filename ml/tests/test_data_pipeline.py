from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ml.src.data_pipeline.adapters import (
    normalize_acn_sessions,
    normalize_operator_sessions,
    normalize_simulator_sessions,
)
from ml.src.data_pipeline.markov import build_markov_state_dataset
from ml.src.data_pipeline.occupancy import prepare_occupancy_history
from ml.src.data_pipeline.rdm import (
    RDM_LIVE_SAFE_FEATURE_COLUMNS,
    RDM_TARGET_COLUMN,
    build_live_safe_rdm_dataset,
    build_rdm_dataset,
)
from ml.src.data_pipeline.splits import TemporalSplitConfig


def _split() -> TemporalSplitConfig:
    return TemporalSplitConfig("2024-01-01T01:00:00+00:00", "2024-01-02T01:00:00+00:00")


def test_occupancy_adapter_writes_canonical_counts_split_and_manifest(tmp_path):
    source = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=6, freq="12h", tz="UTC"),
            "entity_id": ["station-a"] * 6,
            "busy": [1, 2, 0, 1, 1, 2],
            "idle": [3, 2, 4, 3, 3, 2],
        }
    )
    source_path = tmp_path / "source.parquet"
    output_path = tmp_path / "canonical.parquet"
    source.to_parquet(source_path, index=False)

    result = prepare_occupancy_history(
        source_path,
        output_path,
        source="fixture",
        split_config=TemporalSplitConfig("2024-01-01T12:00:00+00:00", "2024-01-02T12:00:00+00:00"),
    )
    frame = pd.read_parquet(output_path)

    assert {"observed_at", "received_at", "station_id", "quality_flag", "split"}.issubset(frame)
    assert set(frame["split"]) == {"train", "val", "test"}
    assert (
        frame["occupied_ports"] + frame["available_ports"] + frame["offline_ports"]
        == frame["total_ports"]
    ).all()
    assert pd.Timestamp(frame["observed_at"].iloc[0]).tzinfo is not None
    assert (
        json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))["dataset_kind"]
        == "canonical_occupancy_history"
    )


def test_acn_adapter_marks_missing_disconnect_as_censored(tmp_path):
    source_path = tmp_path / "acn.json"
    source_path.write_text(
        json.dumps(
            {
                "_items": [
                    {
                        "_id": "complete",
                        "stationID": "caltech",
                        "spaceID": "EVSE-1",
                        "connectionTime": "2024-01-01T08:00:00Z",
                        "doneChargingTime": "2024-01-01T09:00:00Z",
                        "disconnectTime": "2024-01-01T09:30:00Z",
                        "kWhDelivered": 12.3,
                    },
                    {
                        "_id": "censored",
                        "stationID": "caltech",
                        "spaceID": "EVSE-2",
                        "connectionTime": "2024-01-02T08:00:00Z",
                        "kWhDelivered": 4.0,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    result = normalize_acn_sessions(source_path)

    assert result.loc[result["session_id"] == "complete", "disconnect_at"].notna().all()
    censored = result.loc[result["session_id"] == "censored"].iloc[0]
    assert bool(censored["is_censored"])
    assert pd.notna(censored["censoring_at"])
    assert "final_energy_delivered_kwh" in result


def test_simulator_adapter_preserves_port_release_and_synthetic_provenance(tmp_path):
    sessions_path = tmp_path / "sessions.csv"
    ports_path = tmp_path / "ports.csv"
    pd.DataFrame(
        {
            "session_id": ["SES_1"],
            "station_id": ["HCM_1"],
            "port_id": ["HCM_1_P1"],
            "t_connect": ["2024-01-01T08:00:00+07:00"],
            "t_charge_end": ["2024-01-01T08:30:00+07:00"],
            "t_disconnect": ["2024-01-01T08:45:00+07:00"],
            "energy_kwh": [12.5],
            "is_synthetic": [True],
        }
    ).to_csv(sessions_path, index=False)
    pd.DataFrame(
        {"port_id": ["HCM_1_P1"], "station_id": ["HCM_1"], "connector": ["CCS2"]}
    ).to_csv(ports_path, index=False)

    result = normalize_simulator_sessions(sessions_path, ports_path)

    row = result.iloc[0]
    assert row["connector_type"] == "CCS2"
    assert row["source"] == "simulator_hcmc_synthetic"
    assert row["quality_flag"] == "synthetic_for_evaluation_only"
    assert not bool(row["is_censored"])
    assert row["disconnect_at"] == pd.Timestamp("2024-01-01T01:45:00Z")


def test_simulator_adapter_rejects_rows_without_explicit_synthetic_label(tmp_path):
    sessions_path = tmp_path / "sessions.csv"
    ports_path = tmp_path / "ports.csv"
    pd.DataFrame(
        {
            "session_id": ["SES_1"],
            "station_id": ["HCM_1"],
            "port_id": ["HCM_1_P1"],
            "t_connect": ["2024-01-01T08:00:00+07:00"],
            "t_charge_end": ["2024-01-01T08:30:00+07:00"],
            "t_disconnect": ["2024-01-01T08:45:00+07:00"],
            "energy_kwh": [12.5],
            "is_synthetic": [False],
        }
    ).to_csv(sessions_path, index=False)
    pd.DataFrame(
        {"port_id": ["HCM_1_P1"], "station_id": ["HCM_1"], "connector": ["CCS2"]}
    ).to_csv(ports_path, index=False)

    try:
        normalize_simulator_sessions(sessions_path, ports_path)
    except ValueError as exc:
        assert "is_synthetic=true" in str(exc)
    else:  # pragma: no cover - protects the source-provenance gate.
        raise AssertionError("Expected an explicit synthetic-provenance failure")


def test_operator_adapter_keeps_missing_disconnect_censored_and_rejects_synthetic_source(tmp_path):
    source_path = tmp_path / "operator.csv"
    pd.DataFrame(
        {
            "session_id": ["complete", "open"],
            "station_id": ["hcm-a", "hcm-a"],
            "port_id": ["p-1", "p-2"],
            "connection_at": ["2024-01-01T08:00:00Z", "2024-01-01T09:00:00Z"],
            "disconnect_at": ["2024-01-01T08:40:00Z", None],
            "received_at": ["2024-01-01T08:45:00Z", "2024-01-01T09:10:00Z"],
        }
    ).to_csv(source_path, index=False)

    result = normalize_operator_sessions(source_path, source="provider_hcm")

    assert not bool(result.loc[result["session_id"] == "complete", "is_censored"].iloc[0])
    assert bool(result.loc[result["session_id"] == "open", "is_censored"].iloc[0])
    try:
        normalize_operator_sessions(source_path, source="synthetic_fixture")
    except ValueError as exc:
        assert "non-synthetic" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected source-provenance failure")


def test_rdm_builder_uses_disconnect_label_and_keeps_each_session_in_one_split(tmp_path):
    sessions = pd.DataFrame(
        {
            "session_id": ["train", "val", "test"],
            "station_id": ["s"] * 3,
            "port_id": ["p"] * 3,
            "connector_type": ["CCS2"] * 3,
            "connection_at": pd.to_datetime(
                ["2024-01-01T00:00Z", "2024-01-02T00:00Z", "2024-01-03T00:00Z"]
            ),
            "done_charging_at": pd.to_datetime(
                ["2024-01-01T00:20Z", "2024-01-02T00:20Z", "2024-01-03T00:20Z"]
            ),
            "disconnect_at": pd.to_datetime(
                ["2024-01-01T00:30Z", "2024-01-02T00:30Z", "2024-01-03T00:30Z"]
            ),
            "final_energy_delivered_kwh": [20.0, 20.0, 20.0],
            "source": ["fixture"] * 3,
            "schema_version": ["1"] * 3,
            "quality_flag": ["validated"] * 3,
            "is_censored": [False] * 3,
            "censoring_at": pd.Series([pd.NaT] * 3, dtype="datetime64[ns, UTC]"),
        }
    )
    telemetry = pd.DataFrame(
        {
            "session_id": ["train", "val", "test"],
            "station_id": ["s"] * 3,
            "port_id": ["p"] * 3,
            "observed_at": pd.to_datetime(
                ["2024-01-01T00:10Z", "2024-01-02T00:10Z", "2024-01-03T00:10Z"]
            ),
            "received_at": pd.to_datetime(
                ["2024-01-01T00:10Z", "2024-01-02T00:10Z", "2024-01-03T00:10Z"]
            ),
            "energy_delivered_kwh": [3.0, 3.0, 3.0],
            "current_power_kw": [30.0, 30.0, 30.0],
            "source": ["fixture"] * 3,
            "schema_version": ["1"] * 3,
            "quality_flag": ["validated"] * 3,
            "is_backfilled": [False] * 3,
        }
    )
    sessions_path = tmp_path / "sessions.parquet"
    telemetry_path = tmp_path / "telemetry.parquet"
    output_path = tmp_path / "rdm.parquet"
    sessions.to_parquet(sessions_path, index=False)
    telemetry.to_parquet(telemetry_path, index=False)

    build_rdm_dataset(sessions_path, telemetry_path, output_path, split_config=_split())
    result = pd.read_parquet(output_path)

    assert result[RDM_TARGET_COLUMN].tolist() == [20.0, 20.0, 20.0]
    assert "final_energy_delivered_kwh" not in result
    assert set(result["split"]) == {"train", "val", "test"}
    assert (result.groupby("session_id")["split"].nunique() == 1).all()


def test_live_safe_rdm_builder_joins_inventory_without_future_feature_leakage(tmp_path):
    sessions = pd.DataFrame(
        {
            "session_id": ["train", "val", "test"],
            "station_id": ["s"] * 3,
            "port_id": ["p"] * 3,
            "connector_type": ["CCS2"] * 3,
            "connection_at": pd.to_datetime(
                ["2024-01-01T00:00Z", "2024-01-02T00:00Z", "2024-01-03T00:00Z"]
            ),
            "done_charging_at": pd.to_datetime(
                ["2024-01-01T00:20Z", "2024-01-02T00:20Z", "2024-01-03T00:20Z"]
            ),
            "disconnect_at": pd.to_datetime(
                ["2024-01-01T00:30Z", "2024-01-02T00:30Z", "2024-01-03T00:30Z"]
            ),
            "final_energy_delivered_kwh": [20.0] * 3,
            "source": ["provider_hcm"] * 3,
            "schema_version": ["1"] * 3,
            "quality_flag": ["validated"] * 3,
            "is_censored": [False] * 3,
            "censoring_at": pd.Series([pd.NaT] * 3, dtype="datetime64[ns, UTC]"),
        }
    )
    telemetry = pd.DataFrame(
        {
            "session_id": ["train", "val", "test"],
            "station_id": ["s"] * 3,
            "port_id": ["p"] * 3,
            "observed_at": pd.to_datetime(
                ["2024-01-01T00:10Z", "2024-01-02T00:10Z", "2024-01-03T00:10Z"]
            ),
            "received_at": pd.to_datetime(
                ["2024-01-01T00:10Z", "2024-01-02T00:10Z", "2024-01-03T00:10Z"]
            ),
            "energy_delivered_kwh": [3.0] * 3,
            "current_power_kw": [30.0, 0.0, 30.0],
            "source": ["provider_hcm"] * 3,
            "schema_version": ["1"] * 3,
            "quality_flag": ["validated"] * 3,
            "is_backfilled": [False] * 3,
        }
    )
    sessions_path = tmp_path / "sessions.parquet"
    telemetry_path = tmp_path / "telemetry.parquet"
    inventory_path = tmp_path / "ports.csv"
    output_path = tmp_path / "rdm.parquet"
    sessions.to_parquet(sessions_path, index=False)
    telemetry.to_parquet(telemetry_path, index=False)
    pd.DataFrame({"station_id": ["s"], "port_id": ["p"], "max_power_kw": [60]}).to_csv(
        inventory_path, index=False
    )

    build_live_safe_rdm_dataset(
        sessions_path,
        telemetry_path,
        inventory_path,
        output_path,
        split_config=_split(),
    )
    result = pd.read_parquet(output_path)

    assert set(RDM_LIVE_SAFE_FEATURE_COLUMNS).issubset(result)
    assert result["port_max_power_kw"].tolist() == [60.0] * 3
    assert result.set_index("session_id")["is_drawing_power"].to_dict() == {
        "train": 1,
        "val": 0,
        "test": 1,
    }
    assert "final_energy_delivered_kwh" not in result


def test_markov_builder_preserves_connector_specific_available_capacity(tmp_path):
    rows = []
    for observed_at in pd.date_range("2024-01-01", periods=3, freq="1D", tz="UTC"):
        rows.extend(
            [
                {
                    "observed_at": observed_at,
                    "received_at": observed_at,
                    "station_id": "s",
                    "port_id": "ccs",
                    "connector_type": "CCS2",
                    "state": "available",
                },
                {
                    "observed_at": observed_at,
                    "received_at": observed_at,
                    "station_id": "s",
                    "port_id": "type2",
                    "connector_type": "Type2",
                    "state": "charging",
                },
            ]
        )
    frame = pd.DataFrame(rows).assign(
        event_id=lambda value: [f"event-{index}" for index in range(len(value))],
        event_sequence=1,
        source="fixture",
        schema_version="1",
        quality_flag="validated",
        is_backfilled=False,
    )
    source_path = tmp_path / "ports.parquet"
    output_path = tmp_path / "markov.parquet"
    frame.to_parquet(source_path, index=False)

    build_markov_state_dataset(source_path, output_path, split_config=_split())
    result = pd.read_parquet(output_path)

    assert result.loc[result["connector_type"] == "CCS2", "available_ports"].eq(1).all()
    assert result.loc[result["connector_type"] == "Type2", "available_ports"].eq(0).all()
