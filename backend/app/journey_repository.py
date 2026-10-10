"""Atomic persistence for user journeys and immutable recommendation results."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from hmac import compare_digest
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, text

from backend.app.domain.numeric import database_numeric_values_match
from backend.app.domain.phase7_models import (
    JourneyRecommendationRequest,
    JourneyRecommendationResult,
    TripPositionRequest,
)


class IdempotencyConflict(ValueError):
    """An idempotency key was reused with a different journey request."""


class DatabaseJourneyRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _vehicle_model_id(connection: Any, vehicle_id: str) -> Any:
        rows = connection.execute(
            text("SELECT id, code, provenance FROM vehicle_models WHERE is_active")
        ).mappings()
        matches = []
        for row in rows:
            provenance = row["provenance"] or {}
            legacy_vehicle_id = (provenance.get("_legacy_demo") or {}).get("vehicle_id")
            if vehicle_id in {row["code"], legacy_vehicle_id}:
                matches.append(row["id"])
        if not matches:
            raise KeyError(vehicle_id)
        if len(matches) > 1:
            raise ValueError(f"ambiguous vehicle reference: {vehicle_id}")
        return matches[0]

    def save(
        self,
        request: JourneyRecommendationRequest,
        result: JourneyRecommendationResult,
        *,
        access_token: str,
        access_token_ttl_days: int,
        idempotency_key: str | None = None,
        idempotency_request: JourneyRecommendationRequest | None = None,
    ) -> JourneyRecommendationResult:
        if result.journey_id is None:
            raise ValueError("a persisted recommendation requires journey_id")
        journey_id = UUID(result.journey_id)
        origin = request.origin
        destination = request.destination
        if origin is None or destination is None or request.initial_soc is None:
            raise ValueError("dynamic journey request is missing required trip inputs")

        selected = result.recommendations[0] if result.recommendations else None
        active_route = selected.route if selected else result.direct_route
        request_hash = self._request_hash(idempotency_request or request)
        key_hash = (
            sha256(idempotency_key.encode("utf-8")).hexdigest()
            if idempotency_key is not None
            else None
        )
        access_token_hash = sha256(access_token.encode("utf-8")).hexdigest()
        expires_at = datetime.now(UTC) + timedelta(days=access_token_ttl_days)
        with self._engine.begin() as connection:
            if key_hash is not None:
                existing = connection.execute(
                    text(
                        "SELECT request_hash, journey_id, capability_revoked "
                        "FROM journey_idempotency "
                        "WHERE key_hash=:key_hash FOR UPDATE"
                    ),
                    {"key_hash": key_hash},
                ).mappings().one_or_none()
                if existing is not None:
                    if existing["request_hash"] != request_hash:
                        raise IdempotencyConflict(
                            "Idempotency-Key was already used for a different request"
                        )
                    if existing["capability_revoked"]:
                        raise IdempotencyConflict(
                            "journey access was revoked for this idempotency key"
                        )
                    connection.execute(
                        text(
                            "UPDATE trips SET access_token_hash=:token_hash, "
                            "access_token_expires_at=:expires_at "
                            "WHERE id=:journey_id"
                        ),
                        {
                            "token_hash": access_token_hash,
                            "expires_at": expires_at,
                            "journey_id": existing["journey_id"],
                        },
                    )
                    return self._original_recommendation(
                        connection, existing["journey_id"]
                    )

            vehicle_model_id = self._vehicle_model_id(connection, result.vehicle_id)
            station_db_id = None
            if selected is not None:
                station_db_id = connection.scalar(
                    text("SELECT id FROM stations WHERE code=:station_id"),
                    {"station_id": selected.station_id},
                )
                if station_db_id is None:
                    raise KeyError(selected.station_id)
            connection.execute(
                text(
                    "INSERT INTO trips "
                    "(id, mode, vehicle_model_id, origin, destination, start_battery_pct, "
                    "route, station_id, phase, planned, access_token_hash, "
                    "access_token_expires_at) VALUES ("
                    ":id, 'route', :vehicle_model_id, "
                    "ST_SetSRID(ST_MakePoint(:origin_lon, :origin_lat),4326)::geography, "
                    "ST_SetSRID(ST_MakePoint(:destination_lon,:destination_lat),4326)::geography, "
                    ":start_battery_pct, ST_GeomFromGeoJSON(:route)::geography, "
                    ":station_id, :phase, CAST(:planned AS jsonb), :access_token_hash, "
                    ":access_token_expires_at)"
                ),
                {
                    "id": journey_id,
                    "vehicle_model_id": vehicle_model_id,
                    "origin_lon": origin.lon,
                    "origin_lat": origin.lat,
                    "destination_lon": destination.lon,
                    "destination_lat": destination.lat,
                    "start_battery_pct": request.initial_soc * 100,
                    "route": active_route.geometry.model_dump_json(),
                    "station_id": station_db_id,
                    "phase": "to_station" if selected else "to_destination",
                    "planned": request.model_dump_json(),
                    "access_token_hash": access_token_hash,
                    "access_token_expires_at": expires_at,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO journey_recommendations "
                    "(journey_id, generated_at, ranking_policy_version, scoring_method, "
                    "outcome, request, response) VALUES ("
                    ":journey_id, :generated_at, :ranking_policy_version, :scoring_method, "
                    ":outcome, CAST(:request AS jsonb), CAST(:response AS jsonb))"
                ),
                {
                    "journey_id": journey_id,
                    "generated_at": result.generated_at,
                    "ranking_policy_version": result.ranking_policy_version,
                    "scoring_method": result.scoring_method,
                    "outcome": result.outcome,
                    "request": request.model_dump_json(),
                    "response": result.model_dump_json(),
                },
            )
            if key_hash is not None:
                inserted = connection.execute(
                    text(
                        "INSERT INTO journey_idempotency "
                        "(key_hash, request_hash, journey_id) VALUES "
                        "(:key_hash, :request_hash, :journey_id) "
                        "ON CONFLICT DO NOTHING RETURNING journey_id"
                    ),
                    {
                        "key_hash": key_hash,
                        "request_hash": request_hash,
                        "journey_id": journey_id,
                    },
                ).scalar_one_or_none()
                if inserted is None:
                    existing = connection.execute(
                        text(
                            "SELECT request_hash, journey_id, capability_revoked "
                            "FROM journey_idempotency "
                            "WHERE key_hash=:key_hash FOR UPDATE"
                        ),
                        {"key_hash": key_hash},
                    ).mappings().one()
                    if existing["request_hash"] != request_hash:
                        raise IdempotencyConflict(
                            "Idempotency-Key was already used for a different request"
                        )
                    if existing["capability_revoked"]:
                        raise IdempotencyConflict(
                            "journey access was revoked for this idempotency key"
                        )
                    connection.execute(
                        text("DELETE FROM trips WHERE id=:journey_id"),
                        {"journey_id": journey_id},
                    )
                    connection.execute(
                        text(
                            "UPDATE trips SET access_token_hash=:token_hash, "
                            "access_token_expires_at=:expires_at "
                            "WHERE id=:journey_id"
                        ),
                        {
                            "token_hash": access_token_hash,
                            "expires_at": expires_at,
                            "journey_id": existing["journey_id"],
                        },
                    )
                    return self._original_recommendation(
                        connection, existing["journey_id"]
                    )
        return result

    @staticmethod
    def _request_hash(request: JourneyRecommendationRequest) -> str:
        canonical_request = json.dumps(
            request.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(canonical_request.encode("utf-8")).hexdigest()

    def lookup_idempotent(
        self,
        request: JourneyRecommendationRequest,
        idempotency_key: str,
        *,
        access_token: str,
        access_token_ttl_days: int,
    ) -> JourneyRecommendationResult | None:
        """Return a persisted retry before recalculating routes or recommendations."""
        key_hash = sha256(idempotency_key.encode("utf-8")).hexdigest()
        request_hash = self._request_hash(request)
        expires_at = datetime.now(UTC) + timedelta(days=access_token_ttl_days)
        access_token_hash = sha256(access_token.encode("utf-8")).hexdigest()
        with self._engine.begin() as connection:
            existing = connection.execute(
                text(
                    "SELECT request_hash, journey_id, capability_revoked "
                    "FROM journey_idempotency WHERE key_hash=:key_hash FOR UPDATE"
                ),
                {"key_hash": key_hash},
            ).mappings().one_or_none()
            if existing is None:
                return None
            if existing["request_hash"] != request_hash:
                raise IdempotencyConflict(
                    "Idempotency-Key was already used for a different request"
                )
            if existing["capability_revoked"]:
                raise IdempotencyConflict(
                    "journey access was revoked for this idempotency key"
                )
            updated = connection.execute(
                text(
                    "UPDATE trips SET access_token_hash=:token_hash, "
                    "access_token_expires_at=:expires_at WHERE id=:journey_id"
                ),
                {
                    "token_hash": access_token_hash,
                    "expires_at": expires_at,
                    "journey_id": existing["journey_id"],
                },
            )
            if updated.rowcount != 1:
                raise RuntimeError("idempotent journey record is missing")
            return self._original_recommendation(connection, existing["journey_id"])

    @staticmethod
    def _original_recommendation(connection: Any, journey_id: UUID) -> JourneyRecommendationResult:
        response = connection.execute(
            text(
                "SELECT response FROM journey_recommendations "
                "WHERE journey_id=:journey_id "
                "ORDER BY created_at, recommendation_id LIMIT 1"
            ),
            {"journey_id": journey_id},
        ).scalar_one_or_none()
        if response is None:
            raise RuntimeError("idempotent journey has no stored recommendation")
        return JourneyRecommendationResult.model_validate(response)

    def record_position(
        self,
        journey_id: UUID,
        position: TripPositionRequest,
        *,
        access_token: str,
        deviation_threshold_m: float,
        min_reroute_interval_min: float,
    ) -> dict[str, Any]:
        if deviation_threshold_m <= 0 or min_reroute_interval_min <= 0:
            raise ValueError("re-plan thresholds must be positive")
        with self._engine.begin() as connection:
            trip = connection.execute(
                text(
                    "SELECT phase, ended_at, route_version, last_reroute_at, "
                    "access_token_hash, access_token_expires_at, "
                    "CASE WHEN route IS NULL THEN NULL ELSE ST_Distance("
                    "route, ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography) END "
                    "AS distance_to_route_m "
                    "FROM trips WHERE id=:journey_id FOR UPDATE"
                ),
                {
                    "journey_id": journey_id,
                    "lon": position.location.lon,
                    "lat": position.location.lat,
                },
            ).mappings().one_or_none()
            if trip is None:
                raise KeyError(str(journey_id))
            if not self._token_matches(
                access_token, trip["access_token_hash"], trip["access_token_expires_at"]
            ):
                raise PermissionError("journey access denied")
            if trip["ended_at"] is not None or trip["phase"] in {"arrived", "cancelled"}:
                raise ValueError("cannot add a position to a completed journey")

            latest = connection.execute(
                text(
                    "SELECT recorded_at, ST_X(location::geometry) AS lon, "
                    "ST_Y(location::geometry) AS lat, speed_kmh, heading, "
                    "battery_pct, distance_km FROM trip_positions "
                    "WHERE trip_id=:journey_id ORDER BY recorded_at DESC LIMIT 1"
                ),
                {"journey_id": journey_id},
            ).mappings().one_or_none()
            duplicate = False
            if latest is not None:
                if position.recorded_at < latest["recorded_at"]:
                    raise ValueError("position timestamp is older than the stored position")
                if position.recorded_at == latest["recorded_at"]:
                    same_values = (
                        abs(float(latest["lon"]) - position.location.lon) < 1e-7
                        and abs(float(latest["lat"]) - position.location.lat) < 1e-7
                        and database_numeric_values_match(
                            latest["speed_kmh"],
                            position.speed_kmh,
                            decimal_places=2,
                        )
                        and database_numeric_values_match(
                            latest["heading"], position.heading, decimal_places=2
                        )
                        and database_numeric_values_match(
                            latest["battery_pct"],
                            position.battery_pct,
                            decimal_places=2,
                        )
                        and database_numeric_values_match(
                            latest["distance_km"],
                            position.distance_km,
                            decimal_places=3,
                        )
                    )
                    if not same_values:
                        raise ValueError("position timestamp already has different data")
                    duplicate = True

            if not duplicate:
                connection.execute(
                    text(
                        "INSERT INTO trip_positions "
                        "(trip_id, recorded_at, location, speed_kmh, heading, "
                        "battery_pct, distance_km) VALUES ("
                        ":journey_id, :recorded_at, "
                        "ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography, "
                        ":speed_kmh, :heading, :battery_pct, :distance_km)"
                    ),
                    {
                        "journey_id": journey_id,
                        "recorded_at": position.recorded_at,
                        "lon": position.location.lon,
                        "lat": position.location.lat,
                        "speed_kmh": position.speed_kmh,
                        "heading": position.heading,
                        "battery_pct": position.battery_pct,
                        "distance_km": position.distance_km,
                    },
                )

            distance = trip["distance_to_route_m"]
            off_route = distance is None or float(distance) > deviation_threshold_m
            last_reroute_at = trip["last_reroute_at"]
            interval_elapsed = (
                last_reroute_at is None
                or (position.recorded_at - last_reroute_at)
                >= timedelta(minutes=min_reroute_interval_min)
            )
            return {
                "journey_id": str(journey_id),
                "recorded_at": position.recorded_at,
                "duplicate": duplicate,
                "distance_to_route_m": float(distance) if distance is not None else None,
                "off_route": off_route,
                "replan_suggested": off_route and interval_elapsed,
                "route_version": int(trip["route_version"]),
            }

    def save_replan(
        self,
        journey_id: UUID,
        request: JourneyRecommendationRequest,
        result: JourneyRecommendationResult,
    ) -> None:
        selected = result.recommendations[0] if result.recommendations else None
        route = selected.route if selected else result.direct_route
        station_id = selected.station_id if selected else None
        if request.origin is None or request.destination is None:
            raise ValueError("re-plan request requires origin and destination")
        with self._engine.begin() as connection:
            if station_id is not None:
                station_db_id = connection.scalar(
                    text("SELECT id FROM stations WHERE code=:station_id"),
                    {"station_id": station_id},
                )
                if station_db_id is None:
                    raise KeyError(station_id)
            else:
                station_db_id = None
            previous_version = connection.execute(
                text("SELECT route_version FROM trips WHERE id=:journey_id FOR UPDATE"),
                {"journey_id": journey_id},
            ).scalar_one_or_none()
            if previous_version is None:
                raise KeyError(str(journey_id))
            connection.execute(
                text(
                    "UPDATE trips SET origin="
                    "ST_SetSRID(ST_MakePoint(:origin_lon,:origin_lat),4326)::geography, "
                    "destination="
                    "ST_SetSRID(ST_MakePoint(:destination_lon,:destination_lat),4326)::geography, "
                    "route=ST_GeomFromGeoJSON(:route)::geography, station_id=:station_id, "
                    "phase=:phase, route_version=route_version+1, "
                    "last_reroute_at=:reroute_at, planned=CAST(:planned AS jsonb) "
                    "WHERE id=:journey_id"
                ),
                {
                    "origin_lon": request.origin.lon,
                    "origin_lat": request.origin.lat,
                    "destination_lon": request.destination.lon,
                    "destination_lat": request.destination.lat,
                    "route": route.geometry.model_dump_json(),
                    "station_id": station_db_id,
                    "phase": "to_station" if selected else "to_destination",
                    "reroute_at": request.departure_at,
                    "planned": request.model_dump_json(),
                    "journey_id": journey_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO trip_events (trip_id, type, payload) VALUES ("
                    ":journey_id, 'reroute', CAST(:payload AS jsonb))"
                ),
                {
                    "journey_id": journey_id,
                    "payload": json.dumps(
                        {
                            "from_route_version": previous_version,
                            "to_route_version": previous_version + 1,
                            "trigger": "gps_deviation",
                        }
                    ),
                },
            )
            connection.execute(
                text(
                    "INSERT INTO journey_recommendations "
                    "(journey_id, generated_at, ranking_policy_version, scoring_method, "
                    "outcome, request, response) VALUES ("
                    ":journey_id, :generated_at, :ranking_policy_version, :scoring_method, "
                    ":outcome, CAST(:request AS jsonb), CAST(:response AS jsonb))"
                ),
                {
                    "journey_id": journey_id,
                    "generated_at": result.generated_at,
                    "ranking_policy_version": result.ranking_policy_version,
                    "scoring_method": result.scoring_method,
                    "outcome": result.outcome,
                    "request": request.model_dump_json(),
                    "response": result.model_dump_json(),
                },
            )

    @staticmethod
    def _token_matches(
        access_token: str,
        token_hash: str | None,
        expires_at: datetime | None,
    ) -> bool:
        if token_hash is None or expires_at is None or expires_at <= datetime.now(UTC):
            return False
        candidate = sha256(access_token.encode("utf-8")).hexdigest()
        return compare_digest(candidate, token_hash)

    def get(self, journey_id: UUID, *, access_token: str) -> dict[str, Any]:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT t.id, t.phase, t.created_at, t.ended_at, t.access_token_hash, "
                    "t.access_token_expires_at, "
                    "jr.generated_at, jr.ranking_policy_version, jr.outcome, "
                    "jr.request, jr.response "
                    "FROM trips t JOIN journey_recommendations jr ON jr.journey_id=t.id "
                    "WHERE t.id=:journey_id "
                    "ORDER BY jr.created_at DESC LIMIT 1"
                ),
                {"journey_id": journey_id},
            ).mappings().one_or_none()
        if row is None:
            raise KeyError(str(journey_id))
        if not self._token_matches(
            access_token, row["access_token_hash"], row["access_token_expires_at"]
        ):
            raise PermissionError("journey access denied")
        return {
            "journey_id": str(row["id"]),
            "phase": row["phase"],
            "created_at": row["created_at"],
            "ended_at": row["ended_at"],
            "generated_at": row["generated_at"],
            "ranking_policy_version": row["ranking_policy_version"],
            "outcome": row["outcome"],
            "request": row["request"],
            "recommendation": row["response"],
        }

    def revoke_access(self, journey_id: UUID, *, access_token: str) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "SELECT key_hash FROM journey_idempotency "
                    "WHERE journey_id=:journey_id FOR UPDATE"
                ),
                {"journey_id": journey_id},
            ).first()
            row = connection.execute(
                text(
                    "SELECT access_token_hash, access_token_expires_at "
                    "FROM trips WHERE id=:journey_id FOR UPDATE"
                ),
                {"journey_id": journey_id},
            ).mappings().one_or_none()
            if row is None:
                raise KeyError(str(journey_id))
            if not self._token_matches(
                access_token, row["access_token_hash"], row["access_token_expires_at"]
            ):
                raise PermissionError("journey access denied")
            connection.execute(
                text(
                    "UPDATE trips SET access_token_hash=NULL, access_token_expires_at=now() "
                    "WHERE id=:journey_id"
                ),
                {"journey_id": journey_id},
            )
            connection.execute(
                text(
                    "UPDATE journey_idempotency SET capability_revoked=true "
                    "WHERE journey_id=:journey_id"
                ),
                {"journey_id": journey_id},
            )
