from __future__ import annotations

import json

from ml.src.data_pipeline.acn import normalize_acn_raw_timeseries


def test_normalize_acn_raw_timeseries_resamples_current_and_keeps_port_release(tmp_path):
    source = tmp_path / "acn.json"
    source.write_text(
        json.dumps(
            {
                "_items": [
                    {
                        "_id": "session-1",
                        "siteID": "caltech",
                        "stationID": "station-1",
                        "connectionTime": "2021-01-01T00:00:00Z",
                        "doneChargingTime": "2021-01-01T00:08:00Z",
                        "disconnectTime": "2021-01-01T00:12:00Z",
                        "kWhDelivered": 0.4,
                        "chargingCurrent": {
                            "timestamps": [
                                "2021-01-01T00:00:00Z",
                                "2021-01-01T00:03:00Z",
                                "2021-01-01T00:06:00Z",
                            ],
                            "current": [10, 10, 10],
                        },
                    },
                    {
                        "_id": "session-without-series",
                        "siteID": "caltech",
                        "stationID": "station-2",
                        "connectionTime": "2021-01-01T00:00:00Z",
                        "disconnectTime": "2021-01-01T00:12:00Z",
                        "kWhDelivered": 0.4,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    sessions, telemetry, summary = normalize_acn_raw_timeseries([source], voltage_v=200)

    assert len(sessions) == 2
    assert summary == {
        "source_sessions": 2,
        "sessions_with_telemetry": 1,
        "telemetry_rows": 2,
        "censored_sessions": 0,
    }
    assert telemetry["current_power_kw"].tolist() == [2.0, 2.0]
    assert telemetry["energy_delivered_kwh"].tolist() == [0.1, 0.2]
    assert sessions.loc[sessions["session_id"] == "session-1", "disconnect_at"].notna().all()
