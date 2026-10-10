"""Guard the public backend response models against frontend type drift."""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

from backend.app.domain.models import (
    Connector,
    PlannedArrival,
    StationOccupancyForecast,
    StationOccupancyObservation,
    StationProperties,
    StationStatus,
    Vehicle,
)
from backend.app.domain.phase7_models import (
    CandidateExclusion,
    GeoPoint,
    JourneyRecommendationRequest,
    JourneyRecommendationResult,
    ModelStatus,
    PlannedArrivalCommitRequest,
    RecommendationItem,
    RouteLeg,
    RouteRequest,
    RouteResult,
    RouteWaypoint,
    StationIncidentReport,
    StationIncidentReportRequest,
    TripPositionRequest,
    UnreachableStationFallback,
)

FRONTEND_TYPES = (
    Path(__file__).resolve().parents[2] / "frontend" / "src" / "types.ts"
).read_text(encoding="utf-8")


def parse_fields(block: str) -> dict[str, tuple[str, bool]]:
    return {
        match.group(1): (match.group(3).strip(), match.group(2) is not None)
        for match in re.finditer(
            r"^\s*(\w+)(\?)?:\s*(.*?);[ \t]*(?=\r?\n|$)",
            block,
            re.MULTILINE | re.DOTALL,
        )
    }


def interface_fields(name: str) -> dict[str, tuple[str, bool]]:
    match = re.search(
        rf"export interface {re.escape(name)}(?: extends (\w+))? \{{(.*?)\n\}}",
        FRONTEND_TYPES,
        re.DOTALL,
    )
    assert match is not None, f"frontend interface {name} is missing"
    fields = parse_fields(match.group(2))
    if match.group(1):
        fields.update(
            {
                parent_name: declaration
                for parent_name, declaration in interface_fields(match.group(1)).items()
                if parent_name not in fields
            }
        )
    return fields


def station_property_fields() -> dict[str, tuple[str, bool]]:
    station = re.search(
        r"export interface Station \{(.*?)\n\}", FRONTEND_TYPES, re.DOTALL
    )
    assert station is not None
    properties_start = station.group(1).index("properties: {") + len("properties: ")
    depth = 0
    properties_end = properties_start
    for properties_end in range(properties_start, len(station.group(1))):
        char = station.group(1)[properties_end]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                break
    properties = station.group(1)[properties_start : properties_end + 1]
    return parse_fields(properties)


def test_frontend_response_interfaces_cover_backend_fields() -> None:
    models_and_interfaces = {
        "StationStatus": StationStatus,
        "StationOccupancyForecast": StationOccupancyForecast,
        "StationOccupancyObservation": StationOccupancyObservation,
        "PlannedArrival": PlannedArrival,
        "Vehicle": Vehicle,
        "StationConnector": Connector,
        "GeoPoint": GeoPoint,
        "RouteWaypoint": RouteWaypoint,
        "RouteLeg": RouteLeg,
        "RouteResult": RouteResult,
        "RecommendationItem": RecommendationItem,
        "CandidateExclusion": CandidateExclusion,
        "UnreachableStationFallback": UnreachableStationFallback,
        "JourneyRecommendation": JourneyRecommendationResult,
        "ModelStatus": ModelStatus,
        "StationIncidentReport": StationIncidentReport,
    }
    for interface, model in models_and_interfaces.items():
        frontend_fields = interface_fields(interface)
        backend_fields = set(model.model_fields)
        if interface == "StationStatus":
            backend_fields -= {"port_runtime_statuses", "queue_connector_types"}
        assert backend_fields <= frontend_fields.keys(), (
            f"{interface} is missing backend fields: "
            f"{sorted(backend_fields - frontend_fields.keys())}"
        )
        allowed_frontend_only_fields = (
            {"journey_access_token"} if interface == "JourneyRecommendation" else set()
        )
        assert frontend_fields.keys() - backend_fields == allowed_frontend_only_fields, (
            f"{interface} has unexpected frontend fields: "
            f"{sorted(frontend_fields.keys() - backend_fields)}"
        )
        optional_input_fields = {
            "GeoPoint": {"label"},
            "RouteWaypoint": {"label", "station_id"},
        }.get(interface, set())
        for field_name in backend_fields:
            field = model.model_fields[field_name]
            field_type, is_optional = frontend_fields[field_name]
            assert is_optional == (field_name in optional_input_fields), (
                f"{interface}.{field_name} optionality does not match its API contract"
            )
            backend_nullable = type(None) in get_args(field.annotation)
            frontend_nullable = re.search(r"\bnull\b", field_type) is not None
            assert backend_nullable == frontend_nullable, (
                f"{interface}.{field_name} nullability does not match its API contract"
            )

    station_fields = station_property_fields()
    assert set(StationProperties.model_fields) == station_fields.keys()
    for field_name, field in StationProperties.model_fields.items():
        field_type, is_optional = station_fields[field_name]
        assert not is_optional, f"Station.properties.{field_name} must always be present"
        backend_nullable = type(None) in get_args(field.annotation)
        frontend_nullable = re.search(r"\bnull\b", field_type) is not None
        assert backend_nullable == frontend_nullable, (
            f"Station.properties.{field_name} nullability does not match its API contract"
        )


def test_frontend_journey_request_matches_backend_input_contract() -> None:
    assert_request_interface_compatible(
        "JourneyRequest",
        JourneyRecommendationRequest,
        {
            "scenario_id": "string",
            "apply_scenario_events": "boolean",
            "vehicle_id": "string",
            "initial_soc": "number",
            "target_soc": "number",
            "origin": "GeoPoint",
            "destination": "GeoPoint",
            "departure_at": "string",
        },
    )


def test_frontend_position_request_matches_backend_input_contract() -> None:
    assert_request_interface_compatible(
        "JourneyPositionRequest",
        TripPositionRequest,
        {
            "recorded_at": "string",
            "location": "GeoPoint",
            "speed_kmh": "number",
            "heading": "number",
            "battery_pct": "number",
            "distance_km": "number",
        },
    )


def test_frontend_incident_request_matches_backend_input_contract() -> None:
    assert_request_interface_compatible(
        "StationIncidentCreateRequest",
        StationIncidentReportRequest,
        {
            "journey_id": "string",
            "idempotency_key": "string",
            "incident_type": "StationIncidentType",
            "description": "string",
        },
    )


def test_frontend_route_request_matches_backend_input_contract() -> None:
    assert_request_interface_compatible(
        "RouteRequest",
        RouteRequest,
        {
            "origin": "GeoPoint",
            "destination": "GeoPoint",
            "waypoints": "RouteWaypoint[]",
            "preferred_route_id": "string",
        },
    )


def test_frontend_planned_arrival_request_matches_backend_input_contract() -> None:
    assert_request_interface_compatible(
        "PlannedArrivalCommitRequest",
        PlannedArrivalCommitRequest,
        {
            "arrival_id": "string",
            "journey_id": "string",
            "station_id": "string",
            "vehicle_id": "string",
            "departure_at": "string",
            "route_id": "string",
            "route_duration_to_station_s": "number",
            "expected_energy_kwh": "number",
            "expected_charge_duration_min": "number",
        },
    )


def assert_request_interface_compatible(
    interface_name: str,
    model: type,
    expected_types: dict[str, str],
) -> None:
    frontend_fields = interface_fields(interface_name)
    backend_fields = model.model_fields
    assert frontend_fields.keys() == backend_fields.keys(), (
        f"{interface_name} fields do not match the backend input model"
    )

    for field_name, backend_field in backend_fields.items():
        frontend_type, is_optional = frontend_fields[field_name]
        base_types = {
            value.strip()
            for value in frontend_type.split("|")
            if value.strip() != "null"
        }
        assert base_types == {expected_types[field_name]}, (
            f"{interface_name}.{field_name} has an incompatible frontend type"
        )
        assert not is_optional or not backend_field.is_required(), (
            f"{interface_name}.{field_name} is optional in TypeScript but required by the API"
        )
        frontend_nullable = re.search(r"\bnull\b", frontend_type) is not None
        backend_nullable = type(None) in get_args(backend_field.annotation)
        assert not frontend_nullable or backend_nullable, (
            f"{interface_name}.{field_name} allows null outside the API contract"
        )
