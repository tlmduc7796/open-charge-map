"""Kéo catalog trạm, cổng và xe từ PostgreSQL về một file snapshot JSON.

Chỉ SELECT, trong transaction READ ONLY; không bao giờ ghi vào DB. Snapshot là đầu vào duy nhất
của simulator, nên cùng snapshot + cùng config + cùng seed cho output giống hệt.

Cách dùng:  python -m script pull [--database-url URL]
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from script.config import ROOT

SNAPSHOT_VERSION = 1

# Cùng mặc định với backend/app/config.py (DB demo chạy bằng database/compose.yaml).
DEFAULT_DATABASE_URL = "postgresql://smart_ev:smart_ev@127.0.0.1:5433/smart_ev_data"

# Một dòng mỗi cổng đang hoạt động của trạm đang hoạt động.
_PORTS_SQL = """
    SELECT s.code AS station_id,
           s.name AS station_name,
           p.label AS port_id,
           p.connector_code AS connector,
           ct.current_type::text AS current,
           p.max_power_kw::float8 AS max_power_kw
    FROM stations s
    JOIN ports p ON p.station_id = s.id
    JOIN connector_types ct ON ct.code = p.connector_code
    WHERE s.is_active AND p.is_active
    ORDER BY s.code, p.label
"""

# Một dòng mỗi mẫu xe dùng được (cần pin và ít nhất một công suất sạc). Khác bộ lọc của backend ở
# chỗ không đòi mức tiêu hao, vì simulator không dùng nó.
_VEHICLES_SQL = """
    SELECT vm.code AS vehicle_id,
           vm.brand,
           vm.model,
           vm.variant,
           vm.battery_kwh::float8 AS battery_kwh,
           vm.max_ac_kw::float8 AS max_ac_kw,
           vm.max_dc_kw::float8 AS max_dc_kw,
           COALESCE(jsonb_agg(vc.connector_code ORDER BY vc.connector_code)
                    FILTER (WHERE ct.current_type = 'AC'), '[]'::jsonb) AS ac_connectors,
           COALESCE(jsonb_agg(vc.connector_code ORDER BY vc.connector_code)
                    FILTER (WHERE ct.current_type = 'DC'), '[]'::jsonb) AS dc_connectors
    FROM vehicle_models vm
    JOIN vehicle_connectors vc ON vc.vehicle_model_id = vm.id
    JOIN connector_types ct ON ct.code = vc.connector_code
    WHERE vm.is_active
      AND vm.battery_kwh IS NOT NULL
      AND (COALESCE(vm.max_ac_kw, 0) > 0 OR COALESCE(vm.max_dc_kw, 0) > 0)
    GROUP BY vm.id
    ORDER BY vm.code
"""


def normalize_url(url: str) -> str:
    """Bỏ hậu tố driver của SQLAlchemy (`postgresql+psycopg://`) để psycopg nhận được."""
    scheme, separator, rest = url.partition("://")
    return f"{scheme.split('+')[0]}{separator}{rest}"


def _dotenv_value(path: Path, key: str) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        name, separator, value = line.strip().partition("=")
        if separator and name.strip() == key:
            return value.strip().strip("'\"") or None
    return None


def find_database_url(explicit: str | None = None) -> str:
    """Thứ tự: `--database-url`, biến môi trường DATABASE_URL, `.env` gốc repo, rồi mặc định."""
    url = (
        explicit
        or os.environ.get("DATABASE_URL")
        or _dotenv_value(ROOT.parent / ".env", "DATABASE_URL")
        or DEFAULT_DATABASE_URL
    )
    return normalize_url(url)


def build_snapshot(
    port_rows: list[dict], vehicle_rows: list[dict], pulled_at: str | None = None
) -> dict:
    """Dựng snapshot từ các dòng đã truy vấn. Hàm thuần nên test được không cần DB."""
    duplicates = sorted(
        port_id for port_id, n in Counter(row["port_id"] for row in port_rows).items() if n > 1
    )
    if duplicates:
        raise ValueError(
            f"port_id (ports.label) không duy nhất toàn cục: {', '.join(duplicates[:5])}"
        )
    stations: dict[str, dict] = {}
    for row in port_rows:
        station = stations.setdefault(
            row["station_id"],
            {"station_id": row["station_id"], "name": row["station_name"], "ports": []},
        )
        station["ports"].append(
            {
                "port_id": row["port_id"],
                "connector": row["connector"],
                "current": row["current"],
                "max_power_kw": float(row["max_power_kw"]),
            }
        )
    vehicles = [
        {
            "vehicle_id": row["vehicle_id"],
            "brand": row["brand"],
            "model": row["model"],
            "variant": row["variant"],
            "battery_kwh": row["battery_kwh"],
            "max_ac_kw": row["max_ac_kw"],
            "max_dc_kw": row["max_dc_kw"],
            "ac_connectors": list(row["ac_connectors"]),
            "dc_connectors": list(row["dc_connectors"]),
        }
        for row in vehicle_rows
    ]
    return {
        "version": SNAPSHOT_VERSION,
        "source": "database",
        "pulled_at": pulled_at or datetime.now(UTC).isoformat(timespec="seconds"),
        "counts": {
            "stations": len(stations),
            "ports": len(port_rows),
            "vehicles": len(vehicles),
        },
        "stations": list(stations.values()),
        "vehicles": vehicles,
    }


def pull_snapshot(database_url: str) -> dict:
    """Kết nối DB (chỉ đọc) và dựng snapshot."""
    import psycopg  # nạp muộn để các lệnh khác không cần psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        connection.read_only = True
        port_rows = connection.execute(_PORTS_SQL).fetchall()
        vehicle_rows = connection.execute(_VEHICLES_SQL).fetchall()
    return build_snapshot(port_rows, vehicle_rows)


def write_snapshot(snapshot: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def read_snapshot(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Chưa có snapshot ({path}); chạy `python -m script pull` trước")
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    if snapshot.get("version") != SNAPSHOT_VERSION:
        raise ValueError(f"Phiên bản snapshot {snapshot.get('version')} không được hỗ trợ")
    return snapshot
