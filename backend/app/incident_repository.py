"""Persistence for user reports tied to an authorized journey recommendation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from hmac import compare_digest
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, bindparam, text

from backend.app.domain.phase7_models import (
    StationIncidentReportRequest,
    StationIncidentReviewRequest,
)


class DatabaseIncidentRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _authorized(access_token: str, token_hash: str | None, expires_at: datetime | None) -> bool:
        if token_hash is None or expires_at is None or expires_at <= datetime.now(UTC):
            return False
        return compare_digest(
            sha256(access_token.encode("utf-8")).hexdigest(), token_hash
        )

    def report(
        self,
        journey_id: UUID,
        station_id: str,
        payload: StationIncidentReportRequest,
        *,
        access_token: str,
    ) -> dict[str, Any]:
        if payload.journey_id != journey_id:
            raise ValueError("path and payload journey IDs do not match")
        with self._engine.begin() as connection:
            latest = connection.execute(
                text(
                    "SELECT t.access_token_hash, t.access_token_expires_at, COALESCE(("
                    "SELECT jsonb_agg(jr.response) FROM journey_recommendations jr "
                    "WHERE jr.journey_id=t.id), '[]'::jsonb) AS responses "
                    "FROM trips t WHERE t.id=:journey_id "
                    "FOR UPDATE OF t"
                ),
                {"journey_id": journey_id},
            ).mappings().one_or_none()
            if latest is None:
                raise KeyError(str(journey_id))
            if not self._authorized(
                access_token,
                latest["access_token_hash"],
                latest["access_token_expires_at"],
            ):
                raise PermissionError("journey access denied")

            previous_report = connection.execute(
                text(
                    "SELECT si.incident_id, si.incident_type, si.description, si.status, "
                    "si.created_at, s.code AS station_code "
                    "FROM station_incidents si JOIN stations s ON s.id=si.station_id "
                    "WHERE si.journey_id=:journey_id AND si.idempotency_key=:key"
                ),
                {"journey_id": journey_id, "key": payload.idempotency_key},
            ).mappings().one_or_none()
            if previous_report is not None:
                if (
                    previous_report["station_code"] != station_id
                    or previous_report["incident_type"] != payload.incident_type
                    or previous_report["description"] != payload.description
                ):
                    raise ValueError("idempotency key was already used for another report")
                return self._serialize(
                    previous_report,
                    previous_report["incident_id"],
                    journey_id,
                    station_id,
                )

            responses = latest["responses"]
            if isinstance(responses, str):
                responses = json.loads(responses)
            recommended_station_ids: set[str] = set()
            for response in responses:
                if isinstance(response, str):
                    response = json.loads(response)
                recommended_station_ids.update(
                    item.get("station_id")
                    for item in response.get("recommendations", ())
                )
            if station_id not in recommended_station_ids:
                raise ValueError("station is not part of this journey recommendation")

            station_db_id = connection.scalar(
                text("SELECT id FROM stations WHERE code=:station_id"),
                {"station_id": station_id},
            )
            if station_db_id is None:
                raise KeyError(station_id)
            incident_id = connection.execute(
                text(
                    "INSERT INTO station_incidents "
                    "(journey_id, station_id, idempotency_key, incident_type, description) "
                    "VALUES (:journey_id, :station_id, :idempotency_key, "
                    ":incident_type, :description) "
                    "ON CONFLICT (journey_id, idempotency_key) DO NOTHING "
                    "RETURNING incident_id"
                ),
                {
                    "journey_id": journey_id,
                    "station_id": station_db_id,
                    "idempotency_key": payload.idempotency_key,
                    "incident_type": payload.incident_type,
                    "description": payload.description,
                },
            ).scalar_one_or_none()
            if incident_id is None:
                existing = connection.execute(
                    text(
                        "SELECT incident_id, station_id, incident_type, description, "
                        "status, created_at FROM station_incidents "
                        "WHERE journey_id=:journey_id AND idempotency_key=:key"
                    ),
                    {"journey_id": journey_id, "key": payload.idempotency_key},
                ).mappings().one()
                if (
                    existing["station_id"] != station_db_id
                    or existing["incident_type"] != payload.incident_type
                    or existing["description"] != payload.description
                ):
                    raise ValueError("idempotency key was already used for another report")
                return self._serialize(
                    existing, existing["incident_id"], journey_id, station_id
                )

            row = connection.execute(
                text(
                    "SELECT status, created_at FROM station_incidents "
                    "WHERE incident_id=:incident_id"
                ),
                {"incident_id": incident_id},
            ).mappings().one()
            return {
                "incident_id": str(incident_id),
                "journey_id": str(journey_id),
                "station_id": station_id,
                "incident_type": payload.incident_type,
                "description": payload.description,
                "status": row["status"],
                "created_at": row["created_at"],
                "data_source": "user_report",
            }

    def list_for_review(
        self, *, status: str | None = None, limit: int = 100
    ) -> tuple[dict[str, Any], ...]:
        if not 1 <= limit <= 200:
            raise ValueError("incident review limit must be between 1 and 200")
        query = (
            "SELECT si.incident_id, si.journey_id, s.code AS station_id, "
            "si.incident_type, si.description, si.status, si.created_at, "
            "si.updated_at, si.reviewed_at, si.review_note, si.data_source "
            "FROM station_incidents si JOIN stations s ON s.id=si.station_id "
        )
        if status is not None:
            query += "WHERE si.status=:status "
        query += "ORDER BY si.created_at ASC, si.incident_id ASC LIMIT :limit"
        parameters = {"status": status, "limit": limit} if status else {"limit": limit}
        with self._engine.connect() as connection:
            rows = connection.execute(text(query), parameters).mappings().all()
        return tuple(self._serialize_admin(row) for row in rows)

    def active_ranking_impacts(
        self, station_ids: tuple[str, ...]
    ) -> tuple[dict[str, str], ...]:
        """Return only operator-triaged safety/access issues for candidate stations."""
        if not station_ids:
            return ()
        statement = text(
            "SELECT DISTINCT s.code AS station_id, si.incident_type "
            "FROM station_incidents si JOIN stations s ON s.id=si.station_id "
            "WHERE s.code IN :station_ids AND si.status='triaged' "
            "AND si.incident_type IN ('safety_concern', 'access_problem') "
            "ORDER BY s.code, si.incident_type"
        ).bindparams(bindparam("station_ids", expanding=True))
        with self._engine.connect() as connection:
            rows = connection.execute(
                statement, {"station_ids": tuple(sorted(set(station_ids)))}
            ).mappings().all()
        return tuple(
            {
                "station_id": row["station_id"],
                "incident_type": row["incident_type"],
            }
            for row in rows
        )

    def review(
        self,
        incident_id: UUID,
        payload: StationIncidentReviewRequest,
    ) -> dict[str, Any]:
        with self._engine.begin() as connection:
            row = connection.execute(
                text(
                    "SELECT si.incident_id, si.journey_id, s.code AS station_id, "
                    "si.incident_type, si.description, si.status, si.created_at, "
                    "si.updated_at, si.reviewed_at, si.review_note, si.data_source "
                    "FROM station_incidents si JOIN stations s ON s.id=si.station_id "
                    "WHERE si.incident_id=:incident_id FOR UPDATE OF si"
                ),
                {"incident_id": incident_id},
            ).mappings().one_or_none()
            if row is None:
                raise KeyError(str(incident_id))
            current_status = row["status"]
            if current_status in {"resolved", "rejected"}:
                if (
                    current_status != payload.status
                    or row["review_note"] != payload.review_note
                ):
                    raise ValueError("final incident review cannot be changed")
                return self._serialize_admin(row)

            connection.execute(
                text(
                    "UPDATE station_incidents SET status=:status, review_note=:review_note, "
                    "reviewed_at=now() WHERE incident_id=:incident_id"
                ),
                {
                    "status": payload.status,
                    "review_note": payload.review_note,
                    "incident_id": incident_id,
                },
            )
            updated = connection.execute(
                text(
                    "SELECT si.incident_id, si.journey_id, s.code AS station_id, "
                    "si.incident_type, si.description, si.status, si.created_at, "
                    "si.updated_at, si.reviewed_at, si.review_note, si.data_source "
                    "FROM station_incidents si JOIN stations s ON s.id=si.station_id "
                    "WHERE si.incident_id=:incident_id"
                ),
                {"incident_id": incident_id},
            ).mappings().one()
            return self._serialize_admin(updated)

    @staticmethod
    def _serialize_admin(row: Any) -> dict[str, Any]:
        return {
            "incident_id": str(row["incident_id"]),
            "journey_id": str(row["journey_id"]),
            "station_id": row["station_id"],
            "incident_type": row["incident_type"],
            "description": row["description"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "reviewed_at": row["reviewed_at"],
            "review_note": row["review_note"],
            "data_source": row["data_source"],
        }

    @staticmethod
    def _serialize(
        row: Any, incident_id: UUID, journey_id: UUID, station_id: str
    ) -> dict[str, Any]:
        return {
            "incident_id": str(incident_id),
            "journey_id": str(journey_id),
            "station_id": station_id,
            "incident_type": row["incident_type"],
            "description": row["description"],
            "status": row["status"],
            "created_at": row["created_at"],
            "data_source": "user_report",
        }
