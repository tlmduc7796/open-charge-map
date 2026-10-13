"""HTTP routes for station-planning runs."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from backend.app.api_v1_models import ApiErrorResponse
from backend.app.planning.api_models import (
    PlanningRecommendationRequest,
    PlanningRecommendationResponse,
)
from backend.app.planning.domain import PlanningInfrastructureError

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
