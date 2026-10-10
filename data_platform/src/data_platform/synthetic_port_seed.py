"""Fill demo-only port runtime data from the original station status fixture."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, text

STATUSES = ("available", "charging", "out_of_service")


def _scaled_statuses(template: dict[str, Any], port_count: int) -> tuple[str, ...]:
    source_count = template["total_ports"]
    counts = (
        template["available_ports"],
        template["occupied_ports"],
        template["offline_ports"],
    )
    if source_count <= 0 or sum(counts) != source_count:
        raise ValueError(f"invalid station status template: {template['station_id']}")
    scaled = [count * port_count // source_count for count in counts]
    remainders = [count * port_count % source_count for count in counts]
    for index in sorted(range(3), key=lambda i: (-remainders[i], i))[
        : port_count - sum(scaled)
    ]:
        scaled[index] += 1
    return tuple(status for status, count in zip(STATUSES, scaled) for _ in range(count))


def seed_synthetic_port_statuses(engine: Engine, status_path: Path) -> dict[str, int]:
    templates = json.loads(status_path.read_text(encoding="utf-8"))
    source_ids = tuple(item["station_id"] for item in templates)
    if not source_ids or len(source_ids) != len(set(source_ids)):
        raise ValueError("station status templates must have unique station IDs")
    templates_by_station = {item["station_id"]: item for item in templates}

    with engine.begin() as connection:
        enriched_stations = connection.execute(
            text(
                """
                UPDATE stations
                SET opening_hours=CASE WHEN opening_hours IS NULL
                        OR opening_hours='null'::jsonb THEN '"24/7"'::jsonb
                        ELSE opening_hours END,
                    access_level=CASE WHEN access_level='unknown' THEN 'public'::access_level
                        ELSE access_level END,
                    provenance=provenance
                        || CASE WHEN opening_hours IS NULL OR opening_hours='null'::jsonb
                            THEN jsonb_build_object('opening_hours', jsonb_build_object(
                                'origin','synthetic','provider','deterministic_demo_fill_v1',
                                'note','Demo assumption: always open')) ELSE '{}'::jsonb END
                        || CASE WHEN access_level='unknown'
                            THEN jsonb_build_object('access_level', jsonb_build_object(
                                'origin','synthetic','provider','deterministic_demo_fill_v1',
                                'note','Demo assumption: public access')) ELSE '{}'::jsonb END
                WHERE is_active AND (
                    opening_hours IS NULL OR opening_hours='null'::jsonb
                    OR access_level='unknown'
                )
                RETURNING id
                """
            )
        ).scalars().all()
        statement = text(
            "SELECT s.id AS station_id, s.code, p.id AS port_id, p.label, "
            "ps.port_id IS NOT NULL AS has_status "
            "FROM stations s JOIN ports p ON p.station_id=s.id "
            "LEFT JOIN port_status ps ON ps.port_id=p.id "
            "WHERE s.is_active AND p.is_active "
            "ORDER BY s.code, p.label"
        )
        by_station: dict[str, list[Any]] = defaultdict(list)
        for row in connection.execute(statement).mappings():
            by_station[row["code"]].append(row)

        inserted_statuses = 0
        inserted_metrics = 0
        for station_code, ports in by_station.items():
            digest = hashlib.sha256(station_code.encode("utf-8")).digest()
            template = templates_by_station.get(station_code) or templates[
                int.from_bytes(digest[:4], "big") % len(templates)
            ]
            statuses = _scaled_statuses(template, len(ports))
            reported_at = datetime.fromisoformat(template["timestamp"])
            for port, status in zip(ports, statuses):
                if port["has_status"]:
                    continue
                connection.execute(
                    text(
                        "INSERT INTO port_status "
                        "(port_id, status, reported_at, data_origin) "
                        "VALUES (:port_id, :status, :reported_at, 'synthetic') "
                        "ON CONFLICT (port_id) DO NOTHING"
                    ),
                    {"port_id": port["port_id"], "status": status, "reported_at": reported_at},
                )
                connection.execute(
                    text(
                        "INSERT INTO port_status_history "
                        "(port_id, status, changed_at, data_origin) "
                        "VALUES (:port_id, :status, :reported_at, 'synthetic') "
                        "ON CONFLICT (port_id, changed_at, simulation_run_id) DO NOTHING"
                    ),
                    {"port_id": port["port_id"], "status": status, "reported_at": reported_at},
                )
                inserted_statuses += 1

            result = connection.execute(
                text(
                    "INSERT INTO station_live_metrics "
                    "(station_id, queue_length, avg_session_duration_min, "
                    "reported_at, data_origin) "
                    "VALUES (:station_id, :queue_length, :duration, :reported_at, 'synthetic') "
                    "ON CONFLICT (station_id) DO NOTHING RETURNING station_id"
                ),
                {
                    "station_id": ports[0]["station_id"],
                    "queue_length": template["queue_length"],
                    "duration": template["avg_session_duration_min"],
                    "reported_at": reported_at,
                },
            )
            inserted_metrics += result.scalar_one_or_none() is not None

    return {
        "stations": len(by_station),
        "port_status": inserted_statuses,
        "station_live_metrics": inserted_metrics,
        "station_metadata": len(enriched_stations),
    }
