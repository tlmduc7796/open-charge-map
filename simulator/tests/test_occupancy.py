import csv
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from script.__main__ import main
from script.occupancy import BUCKET, OCCUPANCY_FIELDS, build_rows, load_station_uuids

UUIDS = {
    "ST_A": "00000000-0000-0000-0000-00000000000a",
    "ST_B": "00000000-0000-0000-0000-00000000000b",
}
PORTS = [
    {"port_id": "A1", "station_id": "ST_A"},
    {"port_id": "A2", "station_id": "ST_A"},
    {"port_id": "B1", "station_id": "ST_B"},
]
START = datetime.fromisoformat("2026-08-01T00:00:00+07:00")


def session(station: str, connect: str, disconnect: str) -> dict:
    return {"station_id": station, "t_connect": connect, "t_disconnect": disconnect}


def occupied(rows: list[dict], code: str) -> list[int]:
    return [r["occupied_ports"] for r in rows if r["station_id"] == UUIDS[code]]


def test_a_port_is_occupied_from_connect_up_to_but_excluding_disconnect() -> None:
    sessions = [session("ST_A", "2026-08-01T00:03:00+07:00", "2026-08-01T00:15:00+07:00")]
    rows = build_rows(sessions, PORTS, UUIDS, START, START + 5 * BUCKET)
    # buckets 00:00 .. 00:20 -> connected at 00:05 and 00:10, already gone at 00:15
    assert occupied(rows, "ST_A") == [0, 1, 1, 0, 0]


def test_sessions_on_one_station_add_up_and_stations_are_independent() -> None:
    sessions = [
        session("ST_A", "2026-08-01T00:00:00+07:00", "2026-08-01T00:10:00+07:00"),
        session("ST_A", "2026-08-01T00:05:00+07:00", "2026-08-01T00:20:00+07:00"),
        session("ST_B", "2026-08-01T00:10:00+07:00", "2026-08-01T00:15:00+07:00"),
    ]
    rows = build_rows(sessions, PORTS, UUIDS, START, START + 4 * BUCKET)
    assert occupied(rows, "ST_A") == [1, 2, 1, 1]
    assert occupied(rows, "ST_B") == [0, 0, 1, 0]
    assert {r["total_ports"] for r in rows if r["station_id"] == UUIDS["ST_A"]} == {2}
    assert all(r["operational_ports"] == r["total_ports"] for r in rows)


def test_session_crossing_the_range_edges_is_clipped() -> None:
    sessions = [session("ST_B", "2026-07-31T23:00:00+07:00", "2026-08-01T05:00:00+07:00")]
    rows = build_rows(sessions, PORTS, UUIDS, START, START + 3 * BUCKET)
    assert occupied(rows, "ST_B") == [1, 1, 1]


def test_more_occupied_ports_than_the_station_has_is_an_error() -> None:
    sessions = [session("ST_B", "2026-08-01T00:00:00+07:00", "2026-08-01T00:20:00+07:00")] * 2
    with pytest.raises(ValueError, match="ST_B"):
        build_rows(sessions, PORTS, UUIDS, START, START + 4 * BUCKET)


def test_unknown_station_and_missing_uuid_are_errors() -> None:
    stray = [session("ST_X", "2026-08-01T00:00:00+07:00", "2026-08-01T00:10:00+07:00")]
    with pytest.raises(ValueError, match="ST_X"):
        build_rows(stray, PORTS, UUIDS, START, START + BUCKET)
    with pytest.raises(ValueError, match="UUID"):
        build_rows([], PORTS, {"ST_A": UUIDS["ST_A"]}, START, START + BUCKET)


def test_range_must_be_whole_buckets() -> None:
    with pytest.raises(ValueError, match="5 phút"):
        build_rows([], PORTS, UUIDS, START, START + timedelta(minutes=7))


def test_load_station_uuids_reads_the_seed_file() -> None:
    seed = Path(__file__).resolve().parents[2] / "database" / "data" / "catalog" / "stations.sql"
    mapping = load_station_uuids(seed)
    assert mapping["ST_VF_BUI_HUU_NGHIA"] == "e02d241b-1c5c-5f30-9951-a34e0507705e"
    assert len(mapping) == 11


def test_occupancy_command_writes_table_columns_for_whole_days(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    header = "session_id,station_id,t_connect,t_disconnect\n"
    (data_dir / "sessions.csv").write_text(
        header
        + "S1,ST_VF_BUI_HUU_NGHIA,2026-08-01T10:03:00+07:00,2026-08-01T10:33:00+07:00\n"
        + "S2,ST_VF_BUI_HUU_NGHIA,2026-08-02T23:50:00+07:00,2026-08-03T00:30:00+07:00\n",
        encoding="utf-8",
    )
    (data_dir / "ports.csv").write_text(
        "port_id,station_id\nP1,ST_VF_BUI_HUU_NGHIA\nP2,ST_VF_BUI_HUU_NGHIA\n", encoding="utf-8"
    )
    stations = tmp_path / "stations.sql"
    stations.write_text(
        "INSERT INTO public.stations (id, code) VALUES\n"
        "    ('e02d241b-1c5c-5f30-9951-a34e0507705e', 'ST_VF_BUI_HUU_NGHIA', 'x')\n",
        encoding="utf-8",
    )

    argv = ["--data-dir", str(data_dir), "occupancy", "--stations-sql", str(stations)]
    assert main(argv) == 0

    with (data_dir / "station_occupancy_5m.csv").open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == OCCUPANCY_FIELDS
        rows = list(reader)
    assert len(rows) == 2 * 288  # 2 ngày đầu có phiên bắt đầu (08-01, 08-02)
    assert rows[0]["bucket_at"] == "2026-08-01T00:00:00+07:00"
    assert rows[-1]["bucket_at"] == "2026-08-02T23:55:00+07:00"
    by_bucket = {r["bucket_at"]: r for r in rows}
    assert by_bucket["2026-08-01T10:05:00+07:00"]["occupied_ports"] == "1"
    assert by_bucket["2026-08-01T10:35:00+07:00"]["occupied_ports"] == "0"
    assert by_bucket["2026-08-02T23:55:00+07:00"]["occupied_ports"] == "1"
    assert all(r["total_ports"] == "2" for r in rows)
