"""Kiểm tra các bất biến của dữ liệu phiên sạc mô phỏng và dựng báo cáo tiếng Việt.

Đọc lại chính các file đã ghi (`sessions.csv`, `ports.csv`, `debug/queue_log.csv`) nên kiểm
tra đúng thứ người dùng nhận được. Chỉ dùng thư viện chuẩn.
"""

from __future__ import annotations

import csv
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

TOLERANCE_MIN = 0.01  # sai số khi so thời lượng với các mốc (mốc đã làm tròn đến giây)
MAX_REPORTED_ERRORS = 20


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def minutes(earlier: datetime, later: datetime) -> float:
    return (later - earlier).total_seconds() / 60


def can_use(vehicle: dict, port: dict) -> bool:
    key = "ac_connectors" if port["current"] == "AC" else "dc_connectors"
    return port["connector"] in vehicle[key]


def power_limit(vehicle: dict, port: dict) -> float:
    key = "max_ac_power_kw" if port["current"] == "AC" else "max_dc_power_kw"
    return min(float(port["max_power_kw"]), vehicle[key])


def check_sessions(sessions: list[dict], ports: dict, vehicles: dict) -> list[str]:
    """Trả về danh sách lỗi vi phạm bất biến (rỗng nghĩa là PASS)."""
    errors: list[str] = []
    by_port: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)

    def error(session_id: str, message: str) -> None:
        errors.append(f"{session_id}: {message}")

    for row in sessions:
        sid = row["session_id"]
        port = ports.get(row["port_id"])
        vehicle = vehicles.get(row["vehicle_id"])
        if port is None or vehicle is None:
            error(sid, "port_id hoặc vehicle_id không tồn tại")
            continue
        if port["station_id"] != row["station_id"]:
            error(sid, "port không thuộc station_id của phiên")
        t = [
            datetime.fromisoformat(row[k])
            for k in ("t_connect", "t_charge_start", "t_charge_end", "t_disconnect")
        ]
        if not (t[0] <= t[1] < t[2] <= t[3]):
            error(sid, "thứ tự thời gian sai (connect <= start < end <= disconnect)")
        soc_start, soc_end = float(row["soc_start"]), float(row["soc_end"])
        if not (0 <= soc_start < soc_end <= 1):
            error(sid, f"SOC không hợp lệ ({soc_start} -> {soc_end})")
        if not can_use(vehicle, port):
            error(sid, "xe không tương thích đầu cắm của cổng")
        p_min, p_avg, p_max = (
            float(row[k]) for k in ("min_power_kw", "avg_power_kw", "max_power_kw")
        )
        if not (0 < p_min <= p_avg <= p_max <= power_limit(vehicle, port) + 1e-9):
            error(sid, f"công suất vượt giới hạn ({p_min}/{p_avg}/{p_max})")
        stored = (soc_end - soc_start) * vehicle["usable_battery_kwh"]
        energy = float(row["energy_kwh"]) * vehicle["charging_efficiency"]
        if abs(energy - stored) > max(0.01, 0.01 * stored):
            error(sid, f"năng lượng không khớp ΔSOC ({energy:.3f} và {stored:.3f} kWh)")
        charge, idle, connected = (
            float(row[k]) for k in ("charge_min", "idle_min", "connected_min")
        )
        if abs(charge - minutes(t[1], t[2])) > TOLERANCE_MIN:
            error(sid, "charge_min không khớp các mốc")
        if abs(idle - minutes(t[2], t[3])) > TOLERANCE_MIN:
            error(sid, "idle_min không khớp các mốc")
        if abs(connected - (charge + idle + minutes(t[0], t[1]))) > TOLERANCE_MIN:
            error(sid, "connected_min không khớp các mốc")
        if row["end_reason"] not in {"target_reached", "user_unplug"}:
            error(sid, f"end_reason không hợp lệ: {row['end_reason']}")
        if row["data_source"] != "synthetic" or row["is_synthetic"] != "true":
            error(sid, "thiếu nhãn nguồn gốc synthetic")
        by_port[row["port_id"]].append((t[0], t[3]))

    for port_id, intervals in by_port.items():
        intervals.sort()
        for (_, end), (start, _) in zip(intervals, intervals[1:], strict=False):
            if start < end:
                errors.append(f"{port_id}: hai phiên chồng lấp thời gian")
                break
    return errors


def build_report(
    errors: list[str], sessions: list[dict], ports: dict, queue_log: list[dict]
) -> str:
    status = "PASS" if not errors else "FAIL"
    current = {row["session_id"]: ports[row["port_id"]]["current"] for row in sessions}
    lines = [
        "# Báo cáo kiểm định dữ liệu phiên sạc mô phỏng",
        "",
        f"- Trạng thái: **{status}**",
        f"- Số phiên sạc: {len(sessions)}; số cổng: {len(ports)}; số lượt đến: {len(queue_log)}",
        "- Nguồn kiểm tra: các bất biến được triển khai trong simulator/script/validate.py",
        "",
    ]
    if errors:
        lines += ["## Lỗi", ""]
        lines += [f"- {message}" for message in errors[:MAX_REPORTED_ERRORS]]
        if len(errors) > MAX_REPORTED_ERRORS:
            lines.append(f"- ... và {len(errors) - MAX_REPORTED_ERRORS} lỗi khác")
        lines.append("")

    lines += [
        "## Thống kê theo loại cổng",
        "",
        "| Loại cổng | Số phiên | Sạc TB (phút) | Idle TB (phút) | Chiếm cổng TB (phút) "
        "| Rút sớm |",
        "|---|---|---|---|---|---|",
    ]
    for cur in ("DC", "AC"):
        rows = [r for r in sessions if current[r["session_id"]] == cur]
        if not rows:
            continue

        def mean(key: str, rows: list[dict] = rows) -> float:
            return statistics.mean(float(r[key]) for r in rows)

        early = sum(r["end_reason"] == "user_unplug" for r in rows) / len(rows)
        lines.append(
            f"| {cur} | {len(rows)} | {mean('charge_min'):.0f} | {mean('idle_min'):.0f} | "
            f"{mean('connected_min'):.0f} | {early:.0%} |"
        )

    lines += [
        "",
        "## Hàng đợi (từ debug/queue_log.csv, chỉ để kiểm thử)",
        "",
        "| Trạm | Lượt đến | Bỏ đi | Được phục vụ phải chờ | Chờ TB khi phải chờ (phút) |",
        "|---|---|---|---|---|",
    ]
    for station_id in sorted({r["station_id"] for r in queue_log}):
        rows = [r for r in queue_log if r["station_id"] == station_id]
        served = [float(r["wait_min"]) for r in rows if r["outcome"] == "served"]
        waited = [w for w in served if w > 0.01]
        reneged = sum(r["outcome"] == "reneged" for r in rows)
        lines.append(
            f"| {station_id} | {len(rows)} | {reneged / len(rows):.0%} | "
            f"{len(waited) / max(len(served), 1):.0%} | "
            f"{statistics.mean(waited) if waited else 0:.1f} |"
        )

    by_hour: dict[int, list[dict]] = defaultdict(list)
    for r in queue_log:
        by_hour[datetime.fromisoformat(r["t_arrival"]).hour].append(r)
    lines += [
        "",
        "### Theo giờ đến",
        "",
        "| Giờ | Lượt đến | Phải xếp hàng (có xe chờ lúc đến) | Bỏ đi |",
        "|---|---|---|---|",
    ]
    for hour in range(24):
        rows = by_hour[hour]
        if not rows:
            continue
        queued = sum(int(r["queue_len_on_arrival"]) > 0 for r in rows) / len(rows)
        reneged = sum(r["outcome"] == "reneged" for r in rows) / len(rows)
        lines.append(f"| {hour:02d} | {len(rows)} | {queued:.0%} | {reneged:.0%} |")

    reasons = Counter(r["end_reason"] for r in sessions)
    lines += [
        "",
        "## Ghi chú",
        "",
        f"- Lý do kết thúc: {dict(reasons)}.",
        "- Tất cả tham số hành vi (kiên nhẫn, idle theo giờ, xác suất rút sớm, công suất cố định)"
        " là giả định trong config, không phải số đo thực tế.",
        "- Hàng đợi, thời gian chờ và xe bỏ đi không thuộc schema sessions (chỉ nằm trong debug).",
        "",
    ]
    return "\n".join(lines)


def check_dir(data_dir: Path, vehicles: list[dict]) -> tuple[list[str], str]:
    """Đọc output trong `data_dir`, kiểm tra bất biến; trả về (lỗi, nội dung báo cáo)."""
    sessions = read_csv(data_dir / "sessions.csv")
    ports = {row["port_id"]: row for row in read_csv(data_dir / "ports.csv")}
    queue_log = read_csv(data_dir / "debug" / "queue_log.csv")
    by_id = {vehicle["vehicle_id"]: vehicle for vehicle in vehicles}
    errors = check_sessions(sessions, ports, by_id)
    return errors, build_report(errors, sessions, ports, queue_log)
