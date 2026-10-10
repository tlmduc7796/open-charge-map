"""PostgreSQL trip lifecycle and its linked planned arrival."""

from __future__ import annotations

import hmac
import json
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import Engine, text

from backend.app.api_v1_models import (
    ApiPoint,
    SearchRouteSummary,
    SearchStationOption,
    TripResponse,
)
from backend.app.domain.routing import _haversine_m

_TRIP_SELECT = """
    SELECT t.id, t.mode, t.phase, t.route_version, t.planned,
           t.last_reroute_at, t.declined_station_ids, t.created_at,
           ST_X(t.origin::geometry) AS origin_lng,
           ST_Y(t.origin::geometry) AS origin_lat,
           ST_X(t.destination::geometry) AS destination_lng,
           ST_Y(t.destination::geometry) AS destination_lat,
           ST_AsGeoJSON(t.route::geometry) AS route_geojson,
           s.code AS station_code,
           ARRAY(SELECT code FROM stations
                 WHERE id=ANY(t.declined_station_ids)) AS declined_station_codes,
           (SELECT max(recorded_at) FROM trip_positions WHERE trip_id=t.id)
               AS last_position_at,
           (SELECT ST_X(location::geometry) FROM trip_positions
            WHERE trip_id=t.id ORDER BY recorded_at DESC LIMIT 1) AS last_lng,
           (SELECT ST_Y(location::geometry) FROM trip_positions
            WHERE trip_id=t.id ORDER BY recorded_at DESC LIMIT 1) AS last_lat
    FROM trips t LEFT JOIN stations s ON s.id=t.station_id
    WHERE t.id=CAST(:trip_id AS uuid)
"""


class DatabaseTripRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _row(connection, trip_id: str, *, lock: bool = False):
        if lock:
            locked = connection.scalar(
                text("SELECT id FROM trips WHERE id=CAST(:trip_id AS uuid) FOR UPDATE"),
                {"trip_id": trip_id},
            )
            if locked is None:
                raise KeyError(trip_id)
        row = connection.execute(
            text(_TRIP_SELECT),
            {"trip_id": trip_id},
        ).mappings().one_or_none()
        if row is None:
            raise KeyError(trip_id)
        return row

    @staticmethod
    def _route(row) -> SearchRouteSummary:
        planned = row["planned"]
        geometry = json.loads(row["route_geojson"])["coordinates"]
        return SearchRouteSummary(
            route_id=planned["routeId"],
            provider=planned["routeProvider"],
            distance_km=planned["routeDistanceKm"],
            travel_min=planned["routeTravelMin"],
            geometry=tuple(tuple(point) for point in geometry),
        )

    @classmethod
    def _response(cls, row, *, accepted: bool | None = None) -> TripResponse:
        planned = row["planned"]
        return TripResponse(
            id=str(row["id"]),
            search_id=planned["searchId"],
            mode=row["mode"],
            vehicle_id=planned["vehicleId"],
            station_id=row["station_code"],
            phase=row["phase"],
            route_version=row["route_version"],
            route=cls._route(row),
            eta_at=(
                datetime.fromisoformat(planned["etaAt"])
                if planned.get("etaAt") else None
            ),
            battery_pct=planned["batteryPct"],
            distance_km=planned["distanceKm"],
            prediction_source=planned.get("predictionSource"),
            updated_at=datetime.fromisoformat(planned["updatedAt"]),
            position_accepted=accepted,
            reroute_reasons=tuple(planned.get("rerouteReasons", ())),
        )

    def get(self, trip_id: str) -> TripResponse:
        with self._engine.connect() as connection:
            return self._response(self._row(connection, trip_id))

    def snapshot(self, trip_id: str):
        with self._engine.connect() as connection:
            return self._row(connection, trip_id)

    def create(
        self,
        *,
        search_id: str,
        vehicle_id: str,
        origin: ApiPoint,
        destination: ApiPoint | None,
        battery_pct: float,
        battery_kwh: float,
        consumption_wh_km: float,
        target_battery_pct: float,
        route: SearchRouteSummary,
        option: SearchStationOption | None,
        auth_token_hash: str,
        created_at: datetime,
    ) -> TripResponse:
        trip_id = uuid4()
        mode = "route" if destination is not None else "find_station"
        phase = "to_station" if option is not None else "to_destination"
        eta_at = created_at + timedelta(
            minutes=option.travel_min if option is not None else route.travel_min
        )
        planned = {
            "searchId": search_id,
            "vehicleId": vehicle_id,
            "batteryPct": battery_pct,
            "batteryKwh": battery_kwh,
            "consumptionWhKm": consumption_wh_km,
            "targetBatteryPct": target_battery_pct,
            "distanceKm": 0.0,
            "etaAt": eta_at.isoformat(),
            "routeId": route.route_id,
            "routeProvider": route.provider,
            "routeDistanceKm": route.distance_km,
            "routeTravelMin": route.travel_min,
            "routeStartDistanceKm": 0.0,
            "predictionSource": option.prediction_source if option else None,
            "updatedAt": created_at.isoformat(),
            "arrivalId": f"TRIP_{trip_id.hex}" if option is not None else None,
        }
        geojson = json.dumps({"type": "LineString", "coordinates": route.geometry})
        with self._engine.begin() as connection:
            vehicle_uuid = connection.scalar(
                text("SELECT id FROM vehicle_models WHERE code=:code"),
                {"code": vehicle_id},
            )
            if vehicle_uuid is None:
                for row in connection.execute(
                    text("SELECT id, provenance FROM vehicle_models")
                ).mappings():
                    if row["provenance"].get("_legacy_demo", {}).get("vehicle_id") == vehicle_id:
                        vehicle_uuid = row["id"]
                        break
            if vehicle_uuid is None:
                raise KeyError(vehicle_id)
            station_uuid = None
            if option is not None:
                station_uuid = connection.scalar(
                    text("SELECT id FROM stations WHERE code=:code"),
                    {"code": option.station.id},
                )
                if station_uuid is None:
                    raise KeyError(option.station.id)
            connection.execute(
                text(
                    """
                    INSERT INTO trips
                    (id, mode, vehicle_model_id, origin, destination,
                     start_battery_pct, station_id, route, phase, planned,
                     auth_token_hash, created_at)
                    VALUES
                    (CAST(:trip_id AS uuid), :mode, :vehicle_uuid,
                     ST_SetSRID(ST_MakePoint(:origin_lng,:origin_lat),4326)::geography,
                     CASE WHEN CAST(:destination_lng AS double precision) IS NULL THEN NULL ELSE
                       ST_SetSRID(
                         ST_MakePoint(CAST(:destination_lng AS double precision),
                                      CAST(:destination_lat AS double precision)),
                         4326
                       )::geography
                     END,
                     :battery_pct, :station_uuid,
                     ST_GeomFromGeoJSON(:geojson)::geography,
                     :phase, CAST(:planned AS jsonb), :auth_token_hash, :created_at)
                    """
                ),
                {
                    "trip_id": str(trip_id), "mode": mode,
                    "vehicle_uuid": vehicle_uuid,
                    "origin_lng": origin.lng, "origin_lat": origin.lat,
                    "destination_lng": destination.lng if destination else None,
                    "destination_lat": destination.lat if destination else None,
                    "battery_pct": battery_pct, "station_uuid": station_uuid,
                    "geojson": geojson, "phase": phase,
                    "planned": json.dumps(planned), "created_at": created_at,
                    "auth_token_hash": auth_token_hash,
                },
            )
            if option is not None:
                self._planned_arrival(
                    connection, trip_id=trip_id, station_uuid=station_uuid,
                    vehicle_uuid=vehicle_uuid, option=option, created_at=created_at,
                    arrival_id=planned["arrivalId"],
                    expected_energy_kwh=max(
                        0.0,
                        (target_battery_pct - option.arrive_battery_pct)
                        / 100 * battery_kwh,
                    ),
                )
                self._event(
                    connection, trip_id, "station_accepted",
                    {"stationId": option.station.id},
                )
            return self._response(self._row(connection, str(trip_id)))

    def token_matches(self, trip_id: str, auth_token_hash: str) -> bool:
        with self._engine.connect() as connection:
            stored = connection.scalar(
                text(
                    "SELECT auth_token_hash FROM trips "
                    "WHERE id=CAST(:trip_id AS uuid)"
                ),
                {"trip_id": trip_id},
            )
        if stored is None:
            return False
        return hmac.compare_digest(stored, auth_token_hash)

    @staticmethod
    def _planned_arrival(
        connection, *, trip_id: UUID, station_uuid, vehicle_uuid,
        option: SearchStationOption, created_at: datetime,
        arrival_id: str,
        expected_energy_kwh: float,
    ) -> None:
        eta_at = created_at + timedelta(minutes=option.travel_min)
        connection.execute(
            text(
                """
                INSERT INTO planned_arrivals
                (arrival_id, station_id, vehicle_model_id, route_id, created_at,
                 eta_at, eta_window_start, eta_window_end,
                 expected_energy_kwh, expected_charge_duration_min,
                 arrival_probability, expires_at, status, data_source, provenance)
                VALUES
                (:arrival_id, :station_uuid, :vehicle_uuid, :route_id, :created_at,
                 :eta_at, :window_start, :window_end,
                 :energy_kwh, :charge_min, 1, :expires_at, 'planned', 'runtime',
                 CAST(:provenance AS jsonb))
                """
            ),
            {
                "arrival_id": arrival_id,
                "station_uuid": station_uuid,
                "vehicle_uuid": vehicle_uuid,
                "route_id": option.route.route_id,
                "created_at": created_at,
                "eta_at": eta_at,
                "window_start": eta_at - timedelta(minutes=10),
                "window_end": eta_at + timedelta(minutes=10),
                "charge_min": max(0.1, option.charge_min),
                "energy_kwh": expected_energy_kwh,
                "expires_at": eta_at + timedelta(minutes=30),
                "provenance": json.dumps({"tripId": str(trip_id)}),
            },
        )

    @staticmethod
    def _event(connection, trip_id: UUID | str, kind: str, payload: dict) -> None:
        connection.execute(
            text(
                "INSERT INTO trip_events (trip_id,type,payload) "
                "VALUES (CAST(:trip_id AS uuid),:kind,CAST(:payload AS jsonb))"
            ),
            {"trip_id": str(trip_id), "kind": kind, "payload": json.dumps(payload)},
        )

    def record_position(
        self, trip_id: str, *, location: ApiPoint, recorded_at: datetime,
        battery_pct: float | None, speed_kmh: float | None,
        heading: float | None, near_station_m: int, arrival_m: int,
        allow_station_arrival: bool = True,
    ) -> TripResponse:
        with self._engine.begin() as connection:
            row = self._row(connection, trip_id, lock=True)
            if row["phase"] in {"arrived", "cancelled"}:
                raise ValueError(f"trip is {row['phase']}")
            if recorded_at <= row["created_at"] or (
                row["last_position_at"] is not None
                and recorded_at <= row["last_position_at"]
            ):
                return self._response(row, accepted=False)
            previous_lng = row["last_lng"] if row["last_lng"] is not None else row["origin_lng"]
            previous_lat = row["last_lat"] if row["last_lat"] is not None else row["origin_lat"]
            segment_km = _haversine_m(
                previous_lat, previous_lng, location.lat, location.lng
            ) / 1000
            planned = row["planned"]
            total_distance = planned["distanceKm"] + segment_km
            if battery_pct is None:
                battery_pct = max(
                    0.0,
                    planned["batteryPct"]
                    - segment_km * planned["consumptionWhKm"]
                    / 1000 / planned["batteryKwh"] * 100,
                )
            phase = row["phase"]
            if phase == "to_station" and row["station_code"] is not None:
                station = connection.execute(
                    text(
                        "SELECT ST_X(location::geometry) AS lng, "
                        "ST_Y(location::geometry) AS lat FROM stations "
                        "WHERE code=:code"
                    ),
                    {"code": row["station_code"]},
                ).mappings().one()
                station_distance = _haversine_m(
                    location.lat, location.lng, station["lat"], station["lng"]
                )
                if allow_station_arrival and station_distance <= near_station_m:
                    phase = "at_station"
                    self._event(connection, trip_id, "arrived_station", {})
                    self._set_arrival_status(connection, trip_id, "arrived")
            elif phase == "to_destination":
                destination = connection.execute(
                    text(
                        "SELECT ST_X(destination::geometry) AS lng, "
                        "ST_Y(destination::geometry) AS lat FROM trips "
                        "WHERE id=CAST(:trip_id AS uuid)"
                    ),
                    {"trip_id": trip_id},
                ).mappings().one()
                destination_distance = _haversine_m(
                    location.lat, location.lng, destination["lat"], destination["lng"]
                )
                if destination_distance <= arrival_m:
                    phase = "arrived"
                    self._event(connection, trip_id, "arrived", {})
            route_remaining_min = max(
                0.0,
                planned["routeTravelMin"] *
                (1 - min(
                    1.0,
                    (total_distance - planned.get("routeStartDistanceKm", 0.0))
                    / max(planned["routeDistanceKm"], 0.001),
                )),
            )
            eta_at = recorded_at + timedelta(minutes=route_remaining_min)
            if phase == "to_station" and planned.get("arrivalId") is not None:
                connection.execute(
                    text(
                        "UPDATE planned_arrivals SET eta_at=:eta_at, "
                        "eta_window_start=:start_at, eta_window_end=:end_at, "
                        "expires_at=:expires_at WHERE arrival_id=:arrival_id "
                        "AND status='planned'"
                    ),
                    {
                        "arrival_id": planned["arrivalId"],
                        "eta_at": eta_at,
                        "start_at": eta_at - timedelta(minutes=10),
                        "end_at": eta_at + timedelta(minutes=10),
                        "expires_at": eta_at + timedelta(minutes=30),
                    },
                )
            patch = {
                "batteryPct": battery_pct,
                "distanceKm": total_distance,
                "etaAt": (
                    recorded_at if phase in {"at_station", "arrived"} else eta_at
                ).isoformat(),
                "updatedAt": recorded_at.isoformat(),
            }
            connection.execute(
                text(
                    """
                    INSERT INTO trip_positions
                    (trip_id, recorded_at, location, speed_kmh, heading, battery_pct, distance_km)
                    VALUES
                    (CAST(:trip_id AS uuid), :recorded_at,
                     ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography,
                     :speed_kmh, :heading, :battery_pct, :distance_km)
                    """
                ),
                {
                    "trip_id": trip_id, "recorded_at": recorded_at,
                    "lng": location.lng, "lat": location.lat,
                    "speed_kmh": speed_kmh, "heading": heading,
                    "battery_pct": battery_pct, "distance_km": total_distance,
                },
            )
            connection.execute(
                text(
                    "UPDATE trips SET phase=:phase, planned=planned || CAST(:patch AS jsonb), "
                    "ended_at=CASE WHEN :phase='arrived' THEN :recorded_at ELSE ended_at END "
                    "WHERE id=CAST(:trip_id AS uuid)"
                ),
                {"phase": phase, "patch": json.dumps(patch),
                 "recorded_at": recorded_at, "trip_id": trip_id},
            )
            return self._response(self._row(connection, trip_id), accepted=True)

    @staticmethod
    def _set_arrival_status(connection, trip_id: str, status: str) -> None:
        connection.execute(
            text(
                "UPDATE planned_arrivals SET status=:status "
                "WHERE arrival_id=(SELECT planned->>'arrivalId' FROM trips "
                "WHERE id=CAST(:trip_id AS uuid)) AND status='planned'"
            ),
            {"trip_id": trip_id, "status": status},
        )

    def transition(
        self, trip_id: str, *, action: str, now: datetime,
        battery_pct: float | None = None,
    ) -> TripResponse:
        with self._engine.begin() as connection:
            row = self._row(connection, trip_id, lock=True)
            phase = row["phase"]
            if phase in {"arrived", "cancelled"}:
                raise ValueError(f"trip is {phase}")
            patch: dict[str, object] = {"updatedAt": now.isoformat()}
            if action == "cancel":
                phase = "cancelled"
                self._set_arrival_status(connection, trip_id, "cancelled")
                self._event(connection, trip_id, "cancelled", {})
            elif action == "depart":
                if phase != "at_station" or row["mode"] != "route":
                    raise ValueError("trip cannot depart station in this phase")
                phase = "to_destination"
            elif action == "correctBattery":
                if battery_pct is None:
                    raise ValueError("batteryPct is required")
                patch["batteryPct"] = battery_pct
                self._event(connection, trip_id, "battery_corrected", {"batteryPct": battery_pct})
            else:
                raise ValueError(f"unsupported action: {action}")
            connection.execute(
                text(
                    "UPDATE trips SET phase=:phase, planned=planned || CAST(:patch AS jsonb), "
                    "ended_at=CASE WHEN :phase='cancelled' THEN :now ELSE ended_at END "
                    "WHERE id=CAST(:trip_id AS uuid)"
                ),
                {"phase": phase, "patch": json.dumps(patch), "now": now,
                 "trip_id": trip_id},
            )
            return self._response(self._row(connection, trip_id))

    def change_route(
        self, trip_id: str, *, route: SearchRouteSummary,
        option: SearchStationOption | None, evaluated_at: datetime,
        cooldown_sec: int, declined_station_id: str | None = None,
    ) -> TripResponse:
        with self._engine.begin() as connection:
            row = self._row(connection, trip_id, lock=True)
            if row["phase"] not in {"to_station", "to_destination"}:
                raise ValueError(f"cannot reroute trip in phase {row['phase']}")
            if (
                row["last_reroute_at"] is not None
                and evaluated_at - row["last_reroute_at"] < timedelta(seconds=cooldown_sec)
            ):
                return self._response(row)
            selected_station = option.station.id if option is not None else None
            if selected_station in {
                connection.scalar(
                    text("SELECT code FROM stations WHERE id=:id"), {"id": station_id}
                )
                for station_id in row["declined_station_ids"]
            }:
                raise ValueError("station was already declined")
            if (
                selected_station == row["station_code"]
                and route.geometry == self._route(row).geometry
            ):
                return self._response(row)
            station_uuid = None
            if option is not None:
                station_uuid = connection.scalar(
                    text("SELECT id FROM stations WHERE code=:code"),
                    {"code": selected_station},
                )
                if station_uuid is None:
                    raise KeyError(selected_station)
            current_station_uuid = None
            if row["station_code"] is not None:
                current_station_uuid = connection.scalar(
                    text("SELECT id FROM stations WHERE code=:code"),
                    {"code": row["station_code"]},
                )
            declined_uuid = None
            if declined_station_id is not None:
                if declined_station_id != row["station_code"]:
                    raise ValueError("only the current station can be declined")
                declined_uuid = current_station_uuid
                self._event(
                    connection, trip_id, "station_declined",
                    {"stationId": declined_station_id},
                )
            planned = row["planned"]
            version = row["route_version"] + 1
            eta_at = evaluated_at + timedelta(
                minutes=option.travel_min if option is not None else route.travel_min
            )
            arrival_id = planned.get("arrivalId")
            if selected_station != row["station_code"]:
                self._set_arrival_status(connection, trip_id, "cancelled")
                arrival_id = f"TRIP_{UUID(trip_id).hex}_V{version}" if option else None
                if option is not None:
                    vehicle_uuid = connection.scalar(
                        text("SELECT vehicle_model_id FROM trips WHERE id=CAST(:id AS uuid)"),
                        {"id": trip_id},
                    )
                    self._planned_arrival(
                        connection, trip_id=UUID(trip_id), station_uuid=station_uuid,
                        vehicle_uuid=vehicle_uuid, option=option,
                        created_at=evaluated_at, arrival_id=arrival_id,
                        expected_energy_kwh=max(
                            0.0,
                            (planned["targetBatteryPct"] - option.arrive_battery_pct)
                            / 100 * planned["batteryKwh"],
                        ),
                    )
            elif option is not None and arrival_id is not None:
                connection.execute(
                    text(
                        "UPDATE planned_arrivals SET route_id=:route_id, eta_at=:eta_at, "
                        "eta_window_start=:start_at, eta_window_end=:end_at, "
                        "expires_at=:expires_at WHERE arrival_id=:arrival_id "
                        "AND status='planned'"
                    ),
                    {
                        "route_id": option.route.route_id,
                        "eta_at": eta_at,
                        "start_at": eta_at - timedelta(minutes=10),
                        "end_at": eta_at + timedelta(minutes=10),
                        "expires_at": eta_at + timedelta(minutes=30),
                        "arrival_id": arrival_id,
                    },
                )
            patch = {
                "routeId": route.route_id,
                "routeProvider": route.provider,
                "routeDistanceKm": route.distance_km,
                "routeTravelMin": route.travel_min,
                "routeStartDistanceKm": planned["distanceKm"],
                "etaAt": eta_at.isoformat(),
                "predictionSource": option.prediction_source if option else None,
                "arrivalId": arrival_id,
                "updatedAt": evaluated_at.isoformat(),
            }
            geojson = json.dumps({"type": "LineString", "coordinates": route.geometry})
            connection.execute(
                text(
                    """
                    UPDATE trips SET station_id=:station_uuid,
                        phase=:phase, route=ST_GeomFromGeoJSON(:geojson)::geography,
                        route_version=:version, last_reroute_at=:evaluated_at,
                        declined_station_ids=CASE WHEN CAST(:declined_uuid AS uuid) IS NULL
                            THEN declined_station_ids
                            ELSE array_append(declined_station_ids, CAST(:declined_uuid AS uuid))
                        END,
                        planned=planned || CAST(:patch AS jsonb)
                    WHERE id=CAST(:trip_id AS uuid)
                    """
                ),
                {
                    "trip_id": trip_id,
                    "station_uuid": station_uuid,
                    "phase": "to_station" if option is not None else "to_destination",
                    "geojson": geojson,
                    "version": version,
                    "evaluated_at": evaluated_at,
                    "declined_uuid": str(declined_uuid) if declined_uuid else None,
                    "patch": json.dumps(patch),
                },
            )
            self._event(
                connection, trip_id, "reroute",
                {"fromStationId": row["station_code"],
                 "toStationId": selected_station, "routeVersion": version},
            )
            if selected_station is not None and selected_station != row["station_code"]:
                self._event(
                    connection, trip_id, "station_accepted",
                    {"stationId": selected_station},
                )
            return self._response(self._row(connection, trip_id))
