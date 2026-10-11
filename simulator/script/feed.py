"""Phát lại `station_occupancy_5m.csv` thành luồng cập nhật 5 phút vào backend.

Backend nhận số cổng đang dùng của từng trạm qua `POST /api/v1/internal/station-occupancy`. Script
này đóng vai nguồn đo: mỗi mốc 5 phút nó lấy dòng occupancy "đúng thứ, đúng giờ" của mọi trạm trong
CSV rồi gửi một batch duy nhất.

Chọn dòng nguồn cho mốc `T` (bucket 5 phút hiện tại, UTC):
  - nếu `T` nằm trong khoảng dữ liệu của CSV thì lấy đúng bucket `T`;
  - nếu không thì dịch `T` lùi/tiến theo BỘI SỐ 7 NGÀY tới bucket gần nhất không muộn hơn dòng cuối
    của CSV (cùng thứ, cùng giờ, như database/docker/sql/load_history.sql). Báo lỗi nếu CSV ngắn
    tới mức không có bucket nào như vậy.

CSV dùng UUID trạm, API dùng mã trạm (`stations.code`); ánh xạ lấy từ
database/data/catalog/stations.sql, giống `occupancy.py`.

Chỉ dùng thư viện chuẩn. Dùng trong code:

    replay = load_replay(csv_path, stations_sql)
    updates = build_updates(replay, at=datetime.now(UTC))
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from script.db import _dotenv_value
from script.occupancy import BUCKET, load_station_uuids, read_csv

WEEK = timedelta(days=7)
ENDPOINT = "/api/v1/internal/station-occupancy"
DEFAULT_API_URL = "http://127.0.0.1:8000"
MAX_ATTEMPTS = 3
NOT_FOUND_PREFIX = "station not found: "


class FeedError(RuntimeError):
    """Lỗi gửi batch: có mã trạng thái HTTP (hoặc None khi không kết nối được)."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Reading:
    total_ports: int
    operational_ports: int
    occupied_ports: int


@dataclass(frozen=True)
class Replay:
    """Occupancy theo {mã trạm: {bucket_at (UTC): Reading}} và khoảng bucket của CSV."""

    readings: dict[str, dict[datetime, Reading]]
    start: datetime
    end: datetime


def floor_bucket(moment: datetime) -> datetime:
    """Đầu bucket 5 phút (UTC) chứa `moment`."""
    moment = moment.astimezone(UTC)
    return moment.replace(minute=moment.minute - moment.minute % 5, second=0, microsecond=0)


def load_replay(csv_path: Path, stations_sql: Path) -> Replay:
    """Đọc CSV occupancy và đổi UUID trạm thành mã trạm."""
    rows = read_csv(csv_path)
    if not rows:
        raise ValueError(f"{csv_path} không có dòng nào; chạy `python -m script occupancy` trước")
    code_by_uuid = {uuid.lower(): code for code, uuid in load_station_uuids(stations_sql).items()}
    unknown = sorted({row["station_id"] for row in rows} - code_by_uuid.keys())
    if unknown:
        raise ValueError(
            f"CSV có trạm không có trong {stations_sql.name}: {', '.join(unknown[:5])}"
        )
    readings: dict[str, dict[datetime, Reading]] = {}
    for row in rows:
        bucket = datetime.fromisoformat(row["bucket_at"]).astimezone(UTC)
        readings.setdefault(code_by_uuid[row["station_id"].lower()], {})[bucket] = Reading(
            total_ports=int(row["total_ports"]),
            operational_ports=int(row["operational_ports"]),
            occupied_ports=int(row["occupied_ports"]),
        )
    buckets = [bucket for series in readings.values() for bucket in series]
    return Replay(readings=readings, start=min(buckets), end=max(buckets))


def source_bucket(replay: Replay, target: datetime) -> datetime:
    """Bucket của CSV được phát lại cho mốc `target` (đã làm tròn bucket)."""
    if replay.start <= target <= replay.end:
        return target
    weeks = math.ceil((target - replay.end) / WEEK)
    shifted = target - weeks * WEEK
    if not replay.start <= shifted <= replay.end:
        days = (replay.end - replay.start).days
        raise ValueError(
            f"CSV chỉ phủ {days} ngày ({replay.start.isoformat()} -> {replay.end.isoformat()}); "
            f"không có bucket cùng thứ/giờ với {target.isoformat()}. "
            "Sinh lại simulator dài hơn 7 ngày."
        )
    return shifted


def build_updates(replay: Replay, at: datetime) -> tuple[datetime, list[dict]]:
    """Batch gửi cho thời điểm `at`: (bucket nguồn, danh sách cập nhật theo mã trạm)."""
    if at.tzinfo is None:
        raise ValueError("`at` phải có múi giờ")
    reported_at = at.astimezone(UTC)
    source = source_bucket(replay, floor_bucket(reported_at))
    updates = []
    for code in sorted(replay.readings):
        reading = replay.readings[code].get(source)
        if reading is None:
            continue
        updates.append(
            {
                "stationId": code,
                "reportedAt": reported_at.isoformat(),
                "totalPorts": reading.total_ports,
                "operationalPorts": reading.operational_ports,
                "occupiedPorts": reading.occupied_ports,
            }
        )
    if not updates:
        raise ValueError(f"Không có trạm nào có dữ liệu tại bucket nguồn {source.isoformat()}")
    return source, updates


def _error_message(body: bytes) -> str:
    text = body.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(text)
        return str(parsed["error"]["message"])
    except (ValueError, KeyError, TypeError):
        return text.strip()[:300]


def post_updates(url: str, api_key: str, updates: list[dict], timeout_s: float = 10.0) -> dict:
    """POST một batch; trả về JSON phản hồi. Ném FeedError kèm mã HTTP khi thất bại."""
    request = urllib.request.Request(
        url.rstrip("/") + ENDPOINT,
        data=json.dumps({"updates": updates}).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-API-Key": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise FeedError(_error_message(exc.read()), status=exc.code) from exc
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        raise FeedError(f"không kết nối được {url}: {exc}") from exc


def send_batch(
    url: str,
    api_key: str,
    updates: list[dict],
    *,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = lambda message: print(message, file=sys.stderr),
) -> tuple[dict, list[str]]:
    """Gửi batch, có retry khi lỗi mạng/5xx và tự bỏ trạm mà backend báo không tồn tại.

    Backend ghi cả batch trong một transaction, nên một mã trạm sai làm hỏng toàn bộ; ở đây trạm
    đó bị loại và batch được gửi lại. Trả về (phản hồi, các mã trạm đã bỏ).
    """
    pending = list(updates)
    dropped: list[str] = []
    attempt = 0
    while pending:
        try:
            return post_updates(url, api_key, pending), dropped
        except FeedError as exc:
            if exc.status == 404 and exc.args[0].startswith(NOT_FOUND_PREFIX):
                code = exc.args[0].removeprefix(NOT_FOUND_PREFIX).strip()
                remaining = [item for item in pending if item["stationId"] != code]
                if len(remaining) == len(pending):
                    raise
                log(f"  bỏ trạm không có trong backend: {code}")
                dropped.append(code)
                pending = remaining
                continue
            retryable = exc.status is None or exc.status >= 500
            attempt += 1
            if not retryable or attempt >= MAX_ATTEMPTS:
                raise
            delay = 2.0 * 2 ** (attempt - 1)
            log(f"  lỗi ({exc}); thử lại sau {delay:.0f}s ({attempt}/{MAX_ATTEMPTS - 1})")
            sleep(delay)
    raise FeedError("không còn trạm nào hợp lệ để gửi", status=404)


def resolve_api_key(explicit: str | None, env_path: Path) -> str | None:
    """Thứ tự: `--api-key`, biến môi trường INTERNAL_API_KEY, `.env` gốc repo."""
    return (
        explicit
        or os.environ.get("INTERNAL_API_KEY")
        or _dotenv_value(env_path, "INTERNAL_API_KEY")
    )


def resolve_api_url(explicit: str | None) -> str:
    return explicit or os.environ.get("FEED_API_URL") or DEFAULT_API_URL


def feed_once(
    replay: Replay,
    *,
    at: datetime,
    url: str,
    api_key: str | None,
    dry_run: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Gửi (hoặc in, với dry_run) một batch cho `at`; trả về số trạm đã ghi."""
    source, updates = build_updates(replay, at)
    stamp = at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    busy = sum(item["occupiedPorts"] for item in updates)
    ports = sum(item["operationalPorts"] for item in updates)
    summary = (
        f"[{stamp}] bucket {floor_bucket(at):%H:%M} <- nguồn {source.isoformat()}: "
        f"{len(updates)} trạm, {busy}/{ports} cổng bận"
    )
    if dry_run:
        print(summary + " (dry-run, không gửi)")
        print(json.dumps({"updates": updates}, ensure_ascii=False, indent=2))
        return len(updates)
    if not api_key:
        raise ValueError(
            "Thiếu INTERNAL_API_KEY: truyền --api-key, đặt biến môi trường hoặc điền vào .env gốc"
        )
    response, dropped = send_batch(url, api_key, updates, sleep=sleep)
    suffix = f", bỏ {len(dropped)} trạm lạ" if dropped else ""
    print(f"{summary} -> backend ghi {response.get('updated', '?')}{suffix}")
    return int(response.get("updated", 0))


def seconds_until_next_beat(now: datetime, delay_s: float) -> float:
    """Số giây tới mốc 5 phút kế tiếp cộng `delay_s` (chờ nguồn chốt xong bucket)."""
    next_beat = floor_bucket(now) + BUCKET + timedelta(seconds=delay_s)
    return max(0.0, (next_beat - now.astimezone(UTC)).total_seconds())


def run_loop(
    replay: Replay,
    *,
    url: str,
    api_key: str | None,
    delay_s: float,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], None] = time.sleep,
    iterations: int | None = None,
) -> None:
    """Gửi ngay một lần, rồi mỗi 5 phút. Lỗi một lượt chỉ được ghi lại, vòng lặp tiếp tục."""
    if not api_key:
        raise ValueError(
            "Thiếu INTERNAL_API_KEY: truyền --api-key, đặt biến môi trường hoặc điền vào .env gốc"
        )
    sent = 0
    while iterations is None or sent < iterations:
        moment = now()
        try:
            feed_once(replay, at=moment, url=url, api_key=api_key, sleep=sleep)
        except (FeedError, ValueError) as exc:
            print(f"[{moment:%Y-%m-%dT%H:%M:%SZ}] lỗi: {exc}", file=sys.stderr)
        sent += 1
        if iterations is not None and sent >= iterations:
            break
        sleep(seconds_until_next_beat(now(), delay_s))
