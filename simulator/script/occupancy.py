"""Chuyển phiên sạc (`sessions.csv`) thành occupancy lịch sử của trạm theo bucket 5 phút, đúng cột
của bảng `history.station_occupancy_5m` (database/schema/history/station_occupancy_5m.sql).

Quy ước:
  - `bucket_at` là một thời điểm, không phải khoảng. Một cổng được tính "đang bị chiếm" tại
    `bucket_at` nếu t_connect <= bucket_at < t_disconnect: xe còn cắm (kể cả đã sạc xong nhưng chưa
    rút) thì cổng chưa trống cho xe khác, đúng cách simulator trả cổng ở t_disconnect.
  - `total_ports` = số cổng của trạm trong `ports.csv`; `operational_ports` = `total_ports` vì
    simulator không mô phỏng cổng hỏng.
  - Không xuất `queue_length` (cột nullable của bảng, nạp vào sẽ là NULL).
  - Cột `station_id` của bảng là UUID, còn sessions dùng mã trạm (`ST_VF_...`); ánh xạ lấy từ
    database/data/catalog/stations.sql nên không cần kết nối DB.
  - Mô phỏng bắt đầu từ trạng thái rỗng và không sinh xe đến sau ngày cuối, nên các giờ đầu của
    ngày đầu có occupancy thấp hơn thực tế. Cắt bớt bằng --start-date nếu cần.

Chỉ dùng thư viện chuẩn. Dùng trong code:

    rows = build_rows(sessions, ports, station_uuids, start, end)
"""

from __future__ import annotations

import csv
import math
import re
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path

BUCKET = timedelta(minutes=5)
OCCUPANCY_FIELDS = [
    "station_id",
    "bucket_at",
    "total_ports",
    "operational_ports",
    "occupied_ports",
]
# Một dòng của data/catalog/stations.sql: ('<uuid>', '<code>', ...
_STATION_ROW = re.compile(r"^\s*\(\s*'([0-9a-fA-F-]{36})'\s*,\s*'([^']+)'", re.MULTILINE)


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"Không thấy {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_station_uuids(stations_sql: Path) -> dict[str, str]:
    """Đọc {mã trạm: UUID} từ file seed `stations.sql`."""
    if not stations_sql.exists():
        raise FileNotFoundError(f"Không thấy {stations_sql}")
    mapping = {
        code: station_uuid
        for station_uuid, code in _STATION_ROW.findall(stations_sql.read_text(encoding="utf-8"))
    }
    if not mapping:
        raise ValueError(f"Không đọc được trạm nào từ {stations_sql}")
    return mapping


def bucket_index(moment: datetime, start: datetime) -> int:
    """Chỉ số của bucket đầu tiên có bucket_at >= moment (bucket i nằm ở start + i * 5 phút)."""
    return math.ceil((moment - start).total_seconds() / BUCKET.total_seconds())


def count_per_bucket(
    intervals: list[tuple[datetime, datetime]], start: datetime, bucket_count: int
) -> list[int]:
    """Số khoảng [a, b) chứa từng bucket_at, bằng mảng hiệu nên chạy O(khoảng + bucket)."""
    diff = [0] * (bucket_count + 1)
    for begin, finish in intervals:
        first = max(bucket_index(begin, start), 0)
        last = min(bucket_index(finish, start), bucket_count)
        if first < last:
            diff[first] += 1
            diff[last] -= 1
    counts, running = [], 0
    for delta in diff[:bucket_count]:
        running += delta
        counts.append(running)
    return counts


def default_range(sessions: list[dict]) -> tuple[date, date]:
    """Ngày đầu và ngày cuối (theo múi giờ của phiên đầu tiên) có phiên bắt đầu."""
    if not sessions:
        raise ValueError("sessions.csv không có phiên nào; truyền --start-date và --end-date")
    connects = [datetime.fromisoformat(row["t_connect"]) for row in sessions]
    zone = min(connects).tzinfo
    local = [moment.astimezone(zone).date() for moment in connects]
    return min(local), max(local)


def build_rows(
    sessions: list[dict],
    ports: list[dict],
    station_uuids: dict[str, str],
    start: datetime,
    end: datetime,
) -> list[dict]:
    """Dựng các dòng occupancy cho mọi trạm trong `ports` và mọi bucket của [start, end).

    `start`, `end` phải có múi giờ và cách nhau một số nguyên lần 5 phút. Báo lỗi nếu có phiên
    thuộc trạm không có trong `ports`, trạm thiếu UUID, hoặc số cổng bị chiếm vượt tổng số cổng
    (dấu hiệu hai phiên chồng nhau trên một cổng).
    """
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start và end phải có múi giờ")
    if end <= start or (end - start) % BUCKET:
        raise ValueError("end phải sau start và cách start một số nguyên lần 5 phút")
    bucket_count = (end - start) // BUCKET

    totals = Counter(port["station_id"] for port in ports)
    unknown = sorted({row["station_id"] for row in sessions} - totals.keys())
    if unknown:
        raise ValueError(f"Phiên của trạm không có trong ports.csv: {', '.join(unknown[:5])}")
    missing = sorted(totals.keys() - station_uuids.keys())
    if missing:
        raise ValueError(f"Trạm không có UUID trong stations.sql: {', '.join(missing[:5])}")

    intervals: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    for row in sessions:
        intervals[row["station_id"]].append(
            (datetime.fromisoformat(row["t_connect"]), datetime.fromisoformat(row["t_disconnect"]))
        )

    rows: list[dict] = []
    for code in sorted(totals):
        occupied = count_per_bucket(intervals[code], start, bucket_count)
        for index, count in enumerate(occupied):
            bucket_at = start + index * BUCKET
            if count > totals[code]:
                raise ValueError(
                    f"{code} tại {bucket_at.isoformat()}: {count} cổng bị chiếm > "
                    f"{totals[code]} cổng của trạm (phiên chồng nhau trên một cổng?)"
                )
            rows.append(
                {
                    "station_id": station_uuids[code],
                    "bucket_at": bucket_at.isoformat(),
                    "total_ports": totals[code],
                    "operational_ports": totals[code],
                    "occupied_ports": count,
                }
            )
    return rows


def write_rows(rows: list[dict], path: Path) -> None:
    """Ghi CSV UTF-8 với tiêu đề là tên cột bảng, nạp thẳng bằng COPY ... HEADER true."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OCCUPANCY_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def convert_files(
    sessions_path: Path,
    ports_path: Path,
    stations_sql: Path,
    output_path: Path,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    """Đọc sessions/ports, ghi occupancy; trả về thống kê ngắn để in ra."""
    sessions = read_csv(sessions_path)
    ports = read_csv(ports_path)
    first_day, last_day = default_range(sessions) if not (start_date and end_date) else (None, None)
    start_date, end_date = start_date or first_day, end_date or last_day
    if end_date < start_date:
        raise ValueError("--end-date phải không sớm hơn --start-date")

    zone = datetime.fromisoformat(sessions[0]["t_connect"]).tzinfo if sessions else None
    if zone is None:
        raise ValueError("Không xác định được múi giờ: sessions.csv rỗng hoặc thiếu offset")
    start = datetime.combine(start_date, time.min, tzinfo=zone)
    end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=zone)

    rows = build_rows(
        sessions,
        ports,
        load_station_uuids(stations_sql),
        start,
        end,
    )
    write_rows(rows, output_path)
    return {
        "rows": len(rows),
        "stations": len({row["station_id"] for row in rows}),
        "start": start,
        "end": end,
        "occupied_max": max((row["occupied_ports"] for row in rows), default=0),
    }
