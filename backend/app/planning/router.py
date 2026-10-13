"""HTTP routes for station-planning runs."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from backend.app.api_v1_models import ApiErrorResponse
from backend.app.planning.api_models import (
    PlanningDemoSnapshotResponse,
    PlanningRecommendationRequest,
    PlanningRecommendationResponse,
)
from backend.app.planning.domain import PlanningDataError, PlanningInfrastructureError

router = APIRouter(prefix="/api/v1/planning", tags=["station-planning"])


@router.post(
    "/recommendations",
    response_model=PlanningRecommendationResponse,
    responses={
        422: {"model": ApiErrorResponse, "description": "Request validation error"},
        503: {
            "model": ApiErrorResponse,
            "description": "Planning data repository unavailable",
        },
    },
)
def planning_recommendations(
    payload: PlanningRecommendationRequest, request: Request
) -> PlanningRecommendationResponse:
    try:
        return request.app.state.planning_service.recommend(payload)
    except PlanningInfrastructureError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "SERVICE_UNAVAILABLE", "message": str(exc)},
        ) from exc


@router.get(
    "/demo-snapshot",
    response_model=PlanningDemoSnapshotResponse,
    responses={
        503: {
            "model": ApiErrorResponse,
            "description": "Pinned planning demo snapshot unavailable",
        }
    },
)
def planning_demo_snapshot(request: Request) -> PlanningDemoSnapshotResponse:
    """Expose the pinned M1 catalog and map layers used by the Planner scenario form."""
    try:
        payload = request.app.state.planning_service.demo_catalog()
        return PlanningDemoSnapshotResponse.model_validate(payload)
    except (PlanningDataError, PlanningInfrastructureError) as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "PLANNING_SNAPSHOT_UNAVAILABLE", "message": str(exc)},
        ) from exc
