"""Versioned API that preserves the existing demo endpoints during migration."""

from __future__ import annotations

import hmac
from datetime import UTC, datetime, timedelta
from math import ceil
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request

from backend.app.api_v1_models import (
    ApiPoint,
    AvailabilityResponse,
    ConfigResponse,
    ConnectorDetail,
    ConnectorNow,
    PortResponse,
    PortStatusBatchRequest,
    PortStatusBatchResponse,
    SearchRouteRequest,
    SearchRouteResponse,
    SearchStationsRequest,
    SearchStationsResponse,
    StationAvailability,
    StationDetail,
    StationSummary,
    TripActionRequest,
    TripCreateRequest,
    TripPositionRequest,
    TripResponse,
)

router = APIRouter(prefix="/api/v1")


def _bbox(value: str | None) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    try:
        min_lng, min_lat, max_lng, max_lat = (float(item) for item in value.split(","))
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "VALIDATION_ERROR", "message": "bbox must contain four numbers"},
        ) from exc
    if not (-180 <= min_lng < max_lng <= 180 and -90 <= min_lat < max_lat <= 90):
        raise HTTPException(
            status_code=400,
            detail={"code": "VALIDATION_ERROR", "message": "bbox bounds are invalid"},
        )
    return min_lng, min_lat, max_lng, max_lat


def _color(available: int, total: int, unknown: int, green_min: int) -> str:
    if total == 0 or unknown == total:
        return "grey"
    if available == 0:
        return "red"
    if available < green_min:
        return "yellow"
    return "green"


def _stations(request: Request, bbox: str | None):
    bounds = _bbox(bbox)
    repository = request.app.state.station_repository
    return repository.within_bbox(*bounds) if bounds is not None else repository.all()


def _summary(request: Request, station, *, green_min: int) -> StationSummary:
    try:
        status = request.app.state.station_status_repository.get(station.station_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="station status not found") from exc
    lon, lat = station.geometry.coordinates
    return StationSummary(
        id=station.station_id,
        name=station.properties.name,
        address=station.properties.address,
        location=ApiPoint(lat=lat, lng=lon),
        color=_color(
            status.available_ports,
            status.total_ports,
            status.unknown_ports,
            green_min,
        ),
        available_ports=status.available_ports,
        total_ports=status.total_ports,
        connectors=tuple(connector.type for connector in station.properties.connectors),
        updated_at=status.timestamp,
    )


def _require_internal_key(request: Request, supplied: str | None) -> None:
    expected = request.app.state.settings.internal_api_key
    if expected is None:
        raise HTTPException(status_code=503, detail="internal API is not configured")
    if supplied is None or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="invalid internal API key")


def _limit_search(request: Request) -> None:
    client_id = request.client.host if request.client is not None else "unknown"
    if not request.app.state.search_rate_limiter.allow(client_id):
        raise HTTPException(
            status_code=429,
            detail={"code": "RATE_LIMITED", "message": "search rate limit exceeded"},
        )


@router.get("/config", response_model=ConfigResponse, tags=["v1-config"])
def config(request: Request) -> ConfigResponse:
    values = request.app.state.app_config_repository.read().__dict__
    return ConfigResponse.model_validate(
        {key: values[key] for key in ConfigResponse.model_fields}
    )


@router.get("/stations", response_model=tuple[StationSummary, ...], tags=["v1-stations"])
def list_stations(request: Request, bbox: str | None = None) -> tuple[StationSummary, ...]:
    green_min = request.app.state.app_config_repository.read().availability_green_min
    return tuple(
        _summary(request, station, green_min=green_min)
        for station in _stations(request, bbox)
    )


@router.get(
    "/stations/availability",
    response_model=AvailabilityResponse,
    tags=["v1-stations"],
)
def availability(
    request: Request,
    bbox: str | None = None,
    offset: int = Query(default=0),
) -> AvailabilityResponse:
    if offset not in {0, 5, 10, 15, 20, 25, 30}:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "VALIDATION_ERROR",
                "message": "offset must be one of 0,5,10,15,20,25,30",
            },
        )
    stations = _stations(request, bbox)
    green_min = request.app.state.app_config_repository.read().availability_green_min
    items: list[StationAvailability] = []
    for station in stations:
        status = request.app.state.station_status_repository.get(station.station_id)
        if offset == 0:
            available_ports = status.available_ports
            source = status.data_source
        else:
            forecast = request.app.state.occupancy_forecast_service.forecast_occupancy(
                status, horizon_min=offset
            )
            available_ports = max(
                0,
                status.operational_ports - ceil(forecast.predicted_occupied_ports),
            )
            source = forecast.prediction_source
        items.append(
            StationAvailability(
                station_id=station.station_id,
                color=_color(
                    available_ports,
                    status.total_ports,
                    status.unknown_ports,
                    green_min,
                ),
                available_ports=available_ports,
                total_ports=status.total_ports,
                prediction_source=source,
                updated_at=status.timestamp,
            )
        )
    updated_at = max((item.updated_at for item in items), default=datetime.now(UTC))
    return AvailabilityResponse(
        offset=offset,
        is_prediction=offset > 0,
        items=tuple(items),
        updated_at=updated_at,
    )


@router.get("/stations/{station_id}", response_model=StationDetail, tags=["v1-stations"])
def station_detail(station_id: str, request: Request) -> StationDetail:
    try:
        station = request.app.state.station_repository.get(station_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="station not found") from exc
    green_min = request.app.state.app_config_repository.read().availability_green_min
    summary = _summary(request, station, green_min=green_min)
    ports = station_ports(station_id, request)
    groups: list[ConnectorDetail] = []
    for connector in station.properties.connectors:
        matching = tuple(port for port in ports if port.connector == connector.type)
        available = sum(port.status == "available" for port in matching)
        charging = sum(port.status == "charging" for port in matching)
        offline = sum(port.status == "out_of_service" for port in matching)
        unknown = sum(port.status == "unknown" for port in matching)
        groups.append(
            ConnectorDetail(
                code=connector.type,
                max_power_kw=connector.max_power_kw,
                now=ConnectorNow(
                    color=_color(available, len(matching), unknown, green_min),
                    available=available,
                    charging=charging,
                    out_of_service=offline,
                    unknown=unknown,
                    total=len(matching),
                ),
            )
        )
    return StationDetail.model_validate(
        {
            **summary.model_dump(),
            "opening_hours": station.properties.opening_hours,
            "by_connector": tuple(groups),
        }
    )


@router.get(
    "/stations/{station_id}/ports",
    response_model=tuple[PortResponse, ...],
    tags=["v1-stations"],
)
def station_ports(station_id: str, request: Request) -> tuple[PortResponse, ...]:
    repository = request.app.state.station_state_repository
    if repository is None:
        station = request.app.state.station_repository.get(station_id)
        status = request.app.state.station_status_repository.get(station_id)
        items: list[PortResponse] = []
        index = 0
        remaining_available = status.available_ports
        remaining_charging = status.occupied_ports
        remaining_offline = status.offline_ports
        for connector in station.properties.connectors:
            for connector_index in range(connector.count):
                index += 1
                if remaining_available:
                    port_status = "available"
                    remaining_available -= 1
                elif remaining_charging:
                    port_status = "charging"
                    remaining_charging -= 1
                elif remaining_offline:
                    port_status = "out_of_service"
                    remaining_offline -= 1
                else:
                    port_status = "unknown"
                items.append(
                    PortResponse(
                        id=f"{station_id}:{index}",
                        label=f"{connector.type}-{connector_index + 1}",
                        connector=connector.type,
                        status=port_status,
                        updated_at=status.timestamp,
                    )
                )
        return tuple(items)
    try:
        rows = repository.ports(station_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="station not found") from exc
    now = datetime.now(UTC)
    return tuple(
        PortResponse(
            id=row["id"],
            label=row["label"],
            connector=row["connector_code"],
            status=row["status"],
            minutes_to_finish=(
                max(0, ceil((row["estimated_finish_at"] - now).total_seconds() / 60))
                if row["estimated_finish_at"] is not None
                else None
            ),
            updated_at=row["updated_at"],
        )
        for row in rows
    )


@router.post(
    "/internal/port-status",
    response_model=PortStatusBatchResponse,
    tags=["v1-internal"],
)
def update_port_status(
    payload: PortStatusBatchRequest,
    request: Request,
    x_api_key: str | None = Header(default=None),
) -> PortStatusBatchResponse:
    _require_internal_key(request, x_api_key)
    repository = request.app.state.station_state_repository
    if repository is None:
        raise HTTPException(status_code=503, detail="database station state is unavailable")
    now = datetime.now(UTC)
    try:
        updated, ignored = repository.update_batch(payload.updates, ingested_at=now)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"port not found: {exc.args[0]}") from exc
    request.app.state.runtime_state.refresh()
    return PortStatusBatchResponse(updated=updated, ignored=ignored, updated_at=now)


@router.post("/internal/port-status/mark-stale", tags=["v1-internal"])
def mark_stale_port_status(
    request: Request,
    x_api_key: str | None = Header(default=None),
) -> dict[str, int | str]:
    _require_internal_key(request, x_api_key)
    repository = request.app.state.station_state_repository
    if repository is None:
        raise HTTPException(status_code=503, detail="database station state is unavailable")
    now = datetime.now(UTC)
    stale_after = request.app.state.app_config_repository.read().station_status_stale_after_sec
    count = repository.mark_stale(
        stale_before=now - timedelta(seconds=stale_after),
        changed_at=now,
    )
    request.app.state.runtime_state.refresh()
    return {"markedUnknown": count, "updatedAt": now.isoformat()}


@router.post(
    "/search/stations",
    response_model=SearchStationsResponse,
    tags=["v1-search"],
)
def search_stations(
    payload: SearchStationsRequest, request: Request
) -> SearchStationsResponse:
    _limit_search(request)
    try:
        result = request.app.state.search_service.search_stations(payload)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "VEHICLE_NOT_FOUND", "message": str(exc.args[0])},
        ) from exc
    if not result.stations:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "OUT_OF_RANGE",
                "message": "no reachable compatible station was found",
                "nearestStation": (
                    result.nearest_station.model_dump(by_alias=True, mode="json")
                    if result.nearest_station else None
                ),
                "missingKm": result.missing_km,
                "excludedCandidates": [
                    item.model_dump(by_alias=True)
                    for item in result.excluded_candidates
                ],
            },
        )
    return result


@router.post(
    "/search/route",
    response_model=SearchRouteResponse,
    tags=["v1-search"],
)
def search_route(payload: SearchRouteRequest, request: Request) -> SearchRouteResponse:
    _limit_search(request)
    try:
        return request.app.state.search_service.search_route(payload)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "VEHICLE_NOT_FOUND", "message": str(exc.args[0])},
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "NO_ROUTE", "message": str(exc)},
        ) from exc


def _trip_service(request: Request):
    service = request.app.state.trip_service
    if service is None:
        raise HTTPException(status_code=503, detail="trip database is unavailable")
    return service


@router.post("/trips", response_model=TripResponse, status_code=201, tags=["v1-trips"])
def create_trip(payload: TripCreateRequest, request: Request) -> TripResponse:
    try:
        return _trip_service(request).create(payload)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "SEARCH_EXPIRED", "message": str(exc.args[0])},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail={"code": "INVALID_TRIP", "message": str(exc)}
        ) from exc


@router.get("/trips/{trip_id}", response_model=TripResponse, tags=["v1-trips"])
def get_trip(trip_id: UUID, request: Request) -> TripResponse:
    try:
        return _trip_service(request).get(str(trip_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="trip not found") from exc


@router.post("/trips/{trip_id}/position", response_model=TripResponse, tags=["v1-trips"])
def trip_position(
    trip_id: UUID, payload: TripPositionRequest, request: Request
) -> TripResponse:
    try:
        return _trip_service(request).position(str(trip_id), payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="trip not found") from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=409, detail={"code": "TRIP_CONFLICT", "message": str(exc)}
        ) from exc


@router.patch("/trips/{trip_id}", response_model=TripResponse, tags=["v1-trips"])
def update_trip(
    trip_id: UUID, payload: TripActionRequest, request: Request
) -> TripResponse:
    try:
        return _trip_service(request).action(str(trip_id), payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="trip not found") from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=409, detail={"code": "TRIP_CONFLICT", "message": str(exc)}
        ) from exc
