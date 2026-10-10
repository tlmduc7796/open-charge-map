from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.app.api import (
    _authorize_planned_arrival_owner,
    _require_planned_arrival_admin_key,
)


def _request(*, demo_mode: bool, admin_key: str | None = None, journey_repository=None):
    settings = SimpleNamespace(
        demo_mode=demo_mode,
        planned_arrival_admin_api_key=admin_key,
    )
    state = SimpleNamespace(
        settings=settings,
        journey_repository=journey_repository,
    )
    return SimpleNamespace(app=SimpleNamespace(state=state))


def test_planned_arrival_admin_key_is_required_in_release() -> None:
    request = _request(demo_mode=False, admin_key="ops-secret")

    _require_planned_arrival_admin_key(request, "ops-secret")
    with pytest.raises(HTTPException) as error:
        _require_planned_arrival_admin_key(request, None)
    assert error.value.status_code == 401


def test_planned_arrival_admin_operations_fail_closed_without_key() -> None:
    request = _request(demo_mode=False)

    with pytest.raises(HTTPException) as error:
        _require_planned_arrival_admin_key(request, None)
    assert error.value.status_code == 503


def test_planned_arrival_owner_requires_matching_journey_and_capability() -> None:
    journey_id = uuid4()

    class JourneyRepository:
        def get(self, requested_id, *, access_token: str):
            if requested_id != journey_id or access_token != "journey-secret":
                raise PermissionError("denied")
            return {"journey_id": str(journey_id)}

    request = _request(
        demo_mode=False,
        journey_repository=JourneyRepository(),
    )
    arrival = SimpleNamespace(journey_id=str(journey_id))

    _authorize_planned_arrival_owner(
        request,
        arrival,
        journey_id,
        "Bearer journey-secret",
    )
    with pytest.raises(HTTPException) as error:
        _authorize_planned_arrival_owner(
            request,
            arrival,
            uuid4(),
            "Bearer journey-secret",
        )
    assert error.value.status_code == 404
