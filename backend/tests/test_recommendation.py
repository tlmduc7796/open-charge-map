from datetime import datetime

from backend.app.domain.phase7_models import (
    GeoPoint,
    JourneyQuery,
    RecommendationPreference,
)
from backend.app.main import app

ORIGIN = GeoPoint(lat=10.7075, lon=106.705)
DESTINATION = GeoPoint(lat=10.806, lon=106.687)


def _query(**updates) -> JourneyQuery:
    values = {
        "vehicle_id": "EV_VF7_ECO",
        "initial_soc": 0.55,
        "target_soc": 0.8,
        "origin": ORIGIN,
        "destination": DESTINATION,
        "departure_at": datetime.fromisoformat("2026-09-25T18:00:00+07:00"),
        "preference": RecommendationPreference(
            wait_weight=0.25,
            detour_weight=0.25,
            charging_time_weight=0.25,
            soc_risk_weight=0.25,
        ),
    }
    values.update(updates)
    return JourneyQuery(**values)


def test_recommendation_is_ranked_explainable_and_excludes_private_station() -> None:
    result = app.state.recommendation_service.recommend(_query())

    assert result.recommendations
    assert [item.rank for item in result.recommendations] == list(
        range(1, len(result.recommendations) + 1)
    )
    scores = [item.final_score for item in result.recommendations]
    assert scores == sorted(scores, reverse=True)
    assert all(0 <= item.final_score <= 1 for item in result.recommendations)
    assert all(item.prediction_source == "default" for item in result.recommendations)
    assert all(item.matched_connectors for item in result.recommendations)
    assert all(item.effective_power_kw <= 100 for item in result.recommendations)
    assert "cost" not in result.model_dump_json().lower()
    exclusions = {
        item.station_id: item.reason_codes for item in result.excluded_candidates
    }
    assert exclusions["ST_EVO_AUDI_HCM"] == ("NON_PUBLIC_ACCESS",)


def test_incompatible_and_unreachable_candidates_are_filtered() -> None:
    service = app.state.recommendation_service

    incompatible = service.recommend(_query(vehicle_id="EV_GBT_CITY_DEMO"))
    assert incompatible.recommendations == ()
    reasons = {
        reason
        for exclusion in incompatible.excluded_candidates
        for reason in exclusion.reason_codes
    }
    assert "NO_COMPATIBLE_CONNECTOR" in reasons

    unreachable = service.recommend(_query(initial_soc=0.10))
    assert unreachable.recommendations == ()
    reasons = {
        reason
        for exclusion in unreachable.excluded_candidates
        for reason in exclusion.reason_codes
    }
    assert "INSUFFICIENT_SOC_RESERVE" in reasons


def test_low_soc_keeps_safe_options_and_excludes_unreachable_stations() -> None:
    result = app.state.recommendation_service.recommend(
        _query(vehicle_id="EV_VF5_PLUS", initial_soc=0.14)
    )

    assert all(item.arrival_soc >= 0.1 for item in result.recommendations)
    assert any(
        "INSUFFICIENT_SOC_RESERVE" in exclusion.reason_codes
        for exclusion in result.excluded_candidates
    )
