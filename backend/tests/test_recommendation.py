from backend.app.main import app


def test_normal_recommendation_is_explainable_and_excludes_private_station() -> None:
    app.state.runtime_state.reset()
    app.state.planned_arrival_store.reset()

    result = app.state.recommendation_service.recommend("SCN_NORMAL")

    assert len(result.recommendations) == 15
    assert result.recommendations[0].station_id == "ST_VF_LA_VELA"
    assert [item.rank for item in result.recommendations] == list(range(1, 16))
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

    assert before.recommendations[0].station_id == "ST_VF_LA_VELA"
    assert after.recommendations[0].station_id != "ST_VF_LA_VELA"
    exclusions = {
        item.station_id: item.reason_codes for item in after.excluded_candidates
    }
    assert exclusions["ST_VF_LA_VELA"] == ("STATION_OFFLINE",)


def test_low_soc_scenario_keeps_safe_options_and_excludes_unreachable_stations() -> None:
    app.state.runtime_state.reset()
    result = app.state.recommendation_service.recommend("SCN_LOW_SOC")

    assert result.recommendations
    assert all(item.arrival_soc >= 0.1 for item in result.recommendations)
    assert any(
        "INSUFFICIENT_SOC_RESERVE" in exclusion.reason_codes
        for exclusion in result.excluded_candidates
    )


def test_congestion_increases_wait_and_changes_top_recommendation() -> None:
    app.state.runtime_state.reset()
    service = app.state.recommendation_service

    before = service.recommend("SCN_CONGESTION_REROUTE")
    app.state.runtime_state.reset()
    after = service.recommend(
        "SCN_CONGESTION_REROUTE", apply_scenario_events=True
    )

    before_la_vela = next(
        item for item in before.recommendations if item.station_id == "ST_VF_LA_VELA"
    )
    after_la_vela = next(
        item for item in after.recommendations if item.station_id == "ST_VF_LA_VELA"
    )
    assert before.recommendations[0].station_id == "ST_VF_LA_VELA"
    assert after.recommendations[0].station_id != "ST_VF_LA_VELA"
    assert after_la_vela.estimated_wait_min > before_la_vela.estimated_wait_min


def test_fixed_scenarios_cache_routes_for_every_public_station() -> None:
    public_station_ids = {
        station.station_id
        for station in app.state.domain_data.stations.all()
        if station.properties.access == "public"
    }

    for scenario in app.state.domain_data.demo_scenarios.all():
        cached_station_ids = {
            waypoint.station_id
            for route_id in scenario.route_ids
            for waypoint in app.state.domain_data.routes.get(route_id).waypoints
        }
        assert cached_station_ids == public_station_ids
