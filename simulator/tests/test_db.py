import json
import os
from pathlib import Path

import pytest
from script import db

FIXTURE = Path(__file__).parent / "fixtures" / "catalog_snapshot.json"


def port_row(station: str, port: str, current: str = "DC", connector: str = "CCS2") -> dict:
    return {
        "station_id": station,
        "station_name": station.title(),
        "port_id": port,
        "connector": connector,
        "current": current,
        "max_power_kw": 80,
    }


def vehicle_row(vehicle_id: str = "EV_A") -> dict:
    return {
        "vehicle_id": vehicle_id,
        "brand": "VinFast",
        "model": "VF 5",
        "variant": None,
        "battery_kwh": 37.23,
        "max_ac_kw": 6.6,
        "max_dc_kw": 50.0,
        "ac_connectors": ["Type2"],
        "dc_connectors": ["CCS2"],
    }


def test_build_snapshot_groups_ports_by_station() -> None:
    rows = [
        port_row("S1", "S1-001"),
        port_row("S1", "S1-002", current="AC", connector="Type2"),
        port_row("S2", "S2-001"),
    ]
    snapshot = db.build_snapshot(rows, [vehicle_row()], pulled_at="2026-10-11T00:00:00+00:00")
    assert snapshot["counts"] == {"stations": 2, "ports": 3, "vehicles": 1}
    s1, s2 = snapshot["stations"]
    assert [p["port_id"] for p in s1["ports"]] == ["S1-001", "S1-002"]
    assert s1["ports"][1] == {
        "port_id": "S1-002", "connector": "Type2", "current": "AC", "max_power_kw": 80.0,
    }
    assert s2["station_id"] == "S2"
    assert snapshot["source"] == "database"


def test_duplicate_port_labels_are_rejected() -> None:
    rows = [port_row("S1", "SAME"), port_row("S2", "SAME")]
    with pytest.raises(ValueError, match="SAME"):
        db.build_snapshot(rows, [vehicle_row()])


def test_snapshot_round_trip_and_version_check(tmp_path: Path) -> None:
    snapshot = db.build_snapshot([port_row("S1", "S1-001")], [vehicle_row()])
    path = tmp_path / "nested" / "snapshot.json"
    db.write_snapshot(snapshot, path)
    assert db.read_snapshot(path) == snapshot
    path.write_text(json.dumps({**snapshot, "version": 99}), encoding="utf-8")
    with pytest.raises(ValueError, match="99"):
        db.read_snapshot(path)
    with pytest.raises(FileNotFoundError, match="pull"):
        db.read_snapshot(tmp_path / "missing.json")


def test_url_normalization_and_lookup_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert db.normalize_url("postgresql+psycopg://u:p@h:5433/d") == "postgresql://u:p@h:5433/d"
    assert db.normalize_url("postgresql://u@h/d") == "postgresql://u@h/d"

    monkeypatch.setattr(db, "ROOT", tmp_path / "simulator")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert db.find_database_url() == db.DEFAULT_DATABASE_URL
    (tmp_path / ".env").write_text(
        "# comment\nDATABASE_URL='postgresql+psycopg://env@h/d'\n", encoding="utf-8"
    )
    assert db.find_database_url() == "postgresql://env@h/d"
    monkeypatch.setenv("DATABASE_URL", "postgresql://shell@h/d")
    assert db.find_database_url() == "postgresql://shell@h/d"
    assert db.find_database_url("postgresql://flag@h/d") == "postgresql://flag@h/d"


@pytest.mark.skipif(
    not os.environ.get("SIMULATOR_TEST_DATABASE_URL"),
    reason="đặt SIMULATOR_TEST_DATABASE_URL (DB đã bootstrap) để chạy",
)
def test_pull_from_a_real_database() -> None:
    snapshot = db.pull_snapshot(db.normalize_url(os.environ["SIMULATOR_TEST_DATABASE_URL"]))
    assert snapshot["counts"]["stations"] > 0 and snapshot["counts"]["ports"] > 0
    assert all(s["ports"] for s in snapshot["stations"])
    assert all(p["current"] in {"AC", "DC"} for s in snapshot["stations"] for p in s["ports"])
