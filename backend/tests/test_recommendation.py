from backend.app.main import app


def test_normal_recommendation_is_explainable_and_excludes_private_station() -> None:
    app.state.runtime_state.reset()
    app.state.planned_arrival_store.reset()

    result = app.state.recommendation_service.recommend("SCN_NORMAL")

    assert len(result.recommendations) == 2
    assert result.recommendations[0].station_id == "ST_EVO_LAVIDA_Q7"
    assert [item.rank for item in result.recommendations] == [1, 2]
    assert all(0 <= item.final_score <= 1 for item in result.recommendations)
    assert all(item.prediction_source == "persistence" for item in result.recommendations)
    assert "cost" not in result.model_dump_json().lower()
    exclusions = {
        item.station_id: item.reason_codes for item in result.excluded_candidates
    }
    assert exclusions["ST_EVO_AUDI_HCM"] == ("NON_PUBLIC_ACCESS",)


def test_incompatible_and_unreachable_candidates_are_filtered() -> None:
    service = app.state.recommendation_service
    base = app.state.domain_data.demo_scenarios.get("SCN_NORMAL")

    incompatible = base.model_copy(
        update={"scenario_id": "TEST_GBT", "vehicle_id": "EV_GBT_CITY_DEMO"}
    )
    incompatible_result = service.recommend_scenario(incompatible)
    assert incompatible_result.recommendations == ()
    incompatible_reasons = {
        reason
        for exclusion in incompatible_result.excluded_candidates
        for reason in exclusion.reason_codes
    }
    assert "NO_COMPATIBLE_CONNECTOR" in incompatible_reasons

    unreachable = base.model_copy(
        update={"scenario_id": "TEST_LOW_SOC", "initial_soc": 0.10}
    )
    unreachable_result = service.recommend_scenario(unreachable)
    assert unreachable_result.recommendations == ()
    unreachable_reasons = {
        reason
        for exclusion in unreachable_result.excluded_candidates
        for reason in exclusion.reason_codes
    }
    assert "INSUFFICIENT_SOC_RESERVE" in unreachable_reasons


def test_port_outage_event_changes_recommendation() -> None:
    app.state.runtime_state.reset()
    app.state.planned_arrival_store.reset()
    service = app.state.recommendation_service

    before = service.recommend("SCN_PORT_OUTAGE_REROUTE")
    after = service.recommend(
        "SCN_PORT_OUTAGE_REROUTE", apply_scenario_events=True
    )

    assert before.recommendations[0].station_id == "ST_EVO_LAVIDA_Q7"
    assert after.recommendations[0].station_id == "ST_EVO_DEUTSCHES_HAUS"
    exclusions = {
        item.station_id: item.reason_codes for item in after.excluded_candidates
    }
    assert exclusions["ST_EVO_LAVIDA_Q7"] == ("STATION_OFFLINE",)
