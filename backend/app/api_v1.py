"""Versioned API that preserves the existing demo endpoints during migration."""

from __future__ import annotations

import hmac
import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.app.api_v1_models import (
    ApiErrorResponse,
    ApiPoint,
    AvailabilityPoint,
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
    StationAvailabilityForecast,
    StationDetail,
    StationOccupancyBatchRequest,
    StationOccupancyBatchResponse,
    StationSummary,
    TripActionRequest,
    TripCreatedResponse,
    TripCreateRequest,
    TripPositionRequest,
    TripResponse,
)
from backend.app.domain.forecasting import available_ports

logger = logging.getLogger("smart_ev.api_v1")

router = APIRouter(
    prefix="/api/v1",
    responses={
        status: {"model": ApiErrorResponse}
        for status in (400, 401, 403, 404, 409, 422, 429, 503)
    },
)
trip_bearer = HTTPBearer(auto_error=False, scheme_name="TripBearer")


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
    synthetic_fields = set(station.properties.synthetic_fields)
    if any(connector.source.endswith(":synthetic") for connector in station.properties.connectors):
        synthetic_fields.add("connectors")
    synthetic_fields.update(status.synthetic_fields)
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
        synthetic_fields=tuple(sorted(synthetic_fields)),
    )


def _available_at(request: Request, status, offset: int) -> tuple[int, str, tuple[str, ...]]:
    """Free ports, source and flags at `offset` minutes; offset 0 is the live reading."""
    if offset == 0:
        return status.available_ports, status.data_source, ()
    forecast = request.app.state.occupancy_forecast_service.forecast_occupancy(
        status, horizon_min=offset
    )
    available = available_ports(status.operational_ports, forecast.predicted_occupied_ports)
    return available, forecast.prediction_source, forecast.flags


def _apportion(total: int, capacities: Sequence[int]) -> list[int]:
    """Split `total` over groups in proportion to `capacities` (largest remainder).

    The parts sum to `min(total, sum(capacities))` and never exceed a group's capacity.
    """
    capacity = sum(capacities)
    total = max(0, min(total, capacity))
    if total == 0:
        return [0] * len(capacities)
    parts = [total * size // capacity for size in capacities]
    by_remainder = sorted(
        range(len(capacities)), key=lambda i: (-(total * capacities[i] % capacity), i)
    )
    for i in by_remainder[: total - sum(parts)]:
        parts[i] += 1
    return parts


def infer_connector_statuses(
    groups: Sequence[tuple[str, int]], *, occupied: int, offline: int, unknown: int
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Per connector group, the port statuses implied by station-level counts.

    Each state is spread over the groups' remaining free slots proportionally, so a station with
    10 CCS2 and 2 Type2 ports and 6 busy ports shows 5 and 1 charging rather than all 6 on the
    first connector. Whatever is left is `available`.
    """
    remaining = [count for _, count in groups]
    columns: list[tuple[str, list[int]]] = []
    for status_name, amount in (
        ("charging", occupied),
        ("out_of_service", offline),
        ("unknown", unknown),
    ):
        parts = _apportion(amount, remaining)
        remaining = [free - part for free, part in zip(remaining, parts, strict=True)]
        columns.append((status_name, parts))
    result: list[tuple[str, tuple[str, ...]]] = []
    for i, (code, _) in enumerate(groups):
        statuses = ["available"] * remaining[i]
        for status_name, parts in columns:
            statuses.extend([status_name] * parts[i])
        result.append((code, tuple(statuses)))
    return tuple(result)


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
        {key: values[key] for key in ConfigResponse.model_fields if key in values}
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
        available_ports, source, _ = _available_at(request, status, offset)
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
                synthetic_fields=status.synthetic_fields,
            )
        )
    updated_at = max((item.updated_at for item in items), default=datetime.now(UTC))
    return AvailabilityResponse(
        offset=offset,
        is_prediction=offset > 0,
        items=tuple(items),
        updated_at=updated_at,
        generated_at=datetime.now(UTC),
    )


@router.get(
    "/stations/{station_id}/availability",
    response_model=StationAvailabilityForecast,
    tags=["v1-stations"],
)
def station_availability(station_id: str, request: Request) -> StationAvailabilityForecast:
    try:
        status = request.app.state.station_status_repository.get(station_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="station not found") from exc
    green_min = request.app.state.app_config_repository.read().availability_green_min
    points: list[AvailabilityPoint] = []
    for offset in (0, 5, 10, 15, 20, 25, 30):
        available, source, flags = _available_at(request, status, offset)
        points.append(
            AvailabilityPoint(
                offset=offset,
                available_ports=available,
                color=_color(available, status.total_ports, status.unknown_ports, green_min),
                prediction_source=source,
                flags=flags,
            )
        )
    return StationAvailabilityForecast(
        station_id=station_id,
        total_ports=status.total_ports,
        operational_ports=status.operational_ports,
        points=tuple(points),
        updated_at=status.timestamp,
        generated_at=datetime.now(UTC),
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
    """Ports of a station, derived from its station-level counts.

    The feed reports only how many ports are in use, never which ones, so the per-port list is
    inferred: the busy/offline/unknown counts are spread over the connector groups in proportion
    to their size and always add up to the station status.
    """
    try:
        station = request.app.state.station_repository.get(station_id)
        status = request.app.state.station_status_repository.get(station_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="station not found") from exc
    data_source = {"synthetic": "synthetic", "database": "inferred"}.get(
        status.data_source, "unknown"
    )
    groups = tuple(
        (connector.type, connector.count) for connector in station.properties.connectors
    )
    items: list[PortResponse] = []
    index = 0
    for connector_code, statuses in infer_connector_statuses(
        groups,
        occupied=status.occupied_ports,
        offline=status.offline_ports,
        unknown=status.unknown_ports,
    ):
        for connector_index, port_status in enumerate(statuses, start=1):
            index += 1
            items.append(
                PortResponse(
                    id=f"{station_id}:{index}",
                    label=f"{connector_code}-{connector_index}",
                    connector=connector_code,
                    status=port_status,
                    updated_at=status.timestamp,
                    data_source=data_source,
                )
            )
    return tuple(items)


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


@router.post(
    "/internal/station-occupancy",
    response_model=StationOccupancyBatchResponse,
    tags=["v1-internal"],
)
def update_station_occupancy(
    payload: StationOccupancyBatchRequest,
    request: Request,
    x_api_key: str | None = Header(default=None),
) -> StationOccupancyBatchResponse:
    """Record, per station, how many ports are in use (the 5-minute occupancy feed)."""
    _require_internal_key(request, x_api_key)
    repository = request.app.state.station_state_repository
    if repository is None:
        raise HTTPException(status_code=503, detail="database station state is unavailable")
    try:
        updated = repository.record_occupancy(payload.updates)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail=f"station not found: {exc.args[0]}"
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)}
        ) from exc
    request.app.state.runtime_state.refresh()
    writer = request.app.state.prediction_writer
    if writer is not None:
        # The ingest already succeeded; a forecast failure must not turn it into an error.
        try:
            writer.refresh(item.station_id for item in payload.updates)
        except Exception:
            logger.exception("prediction_refresh_failed")
    return StationOccupancyBatchResponse(updated=updated, updated_at=datetime.now(UTC))


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


def _trip_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(trip_bearer),
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail={"code": "TRIP_TOKEN_REQUIRED", "message": "trip bearer token required"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


@router.post(
    "/trips", response_model=TripCreatedResponse, status_code=201, tags=["v1-trips"]
)
def create_trip(payload: TripCreateRequest, request: Request) -> TripCreatedResponse:
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
def get_trip(
    trip_id: UUID, request: Request, token: str = Depends(_trip_token)
) -> TripResponse:
    try:
        return _trip_service(request).get(str(trip_id), token)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="trip not found") from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "TRIP_TOKEN_INVALID", "message": str(exc)},
        ) from exc


@router.post("/trips/{trip_id}/position", response_model=TripResponse, tags=["v1-trips"])
def trip_position(
    trip_id: UUID,
    payload: TripPositionRequest,
    request: Request,
    token: str = Depends(_trip_token),
) -> TripResponse:
    try:
        return _trip_service(request).position(str(trip_id), payload, token)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="trip not found") from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=409, detail={"code": "TRIP_CONFLICT", "message": str(exc)}
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "TRIP_TOKEN_INVALID", "message": str(exc)},
        ) from exc


@router.patch("/trips/{trip_id}", response_model=TripResponse, tags=["v1-trips"])
def update_trip(
    trip_id: UUID,
    payload: TripActionRequest,
    request: Request,
    token: str = Depends(_trip_token),
) -> TripResponse:
    try:
        return _trip_service(request).action(str(trip_id), payload, token)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="trip not found") from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=409, detail={"code": "TRIP_CONFLICT", "message": str(exc)}
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "TRIP_TOKEN_INVALID", "message": str(exc)},
        ) from exc
