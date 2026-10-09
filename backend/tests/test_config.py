from backend.app.config import PROJECT_ROOT, load_settings


def test_default_paths_are_rooted_at_project(monkeypatch) -> None:
    for name in [
        "DATA_DIR",
        "MODEL_ARTIFACT_PATH",
        "MODEL_PREPROCESSOR_PATH",
        "MODEL_META_PATH",
        "WAIT_SCORING_CAP_MIN",
        "ROUTING_TIMEOUT_S",
        "RECOMMEND_MAX_DETOUR_MIN",
        "RECOMMEND_MAX_WAIT_MIN",
        "RECOMMEND_MAX_CHARGE_MIN",
        "RECOMMEND_SOC_RISK_BUFFER",
        "RECOMMEND_CANDIDATE_CORRIDOR_M",
        "STATION_STATUS_STALE_AFTER_S",
        "AVAILABILITY_GREEN_MIN",
        "SEARCH_RATE_LIMIT_PER_MIN",
        "INTERNAL_API_KEY",
        "CORS_ORIGINS",
        "GOONG_API_KEY",
        "DATABASE_URL",
        "CATALOG_STORAGE",
        "PLANNED_ARRIVALS_STORAGE",
    ]:
        monkeypatch.delenv(name, raising=False)
    settings = load_settings()

    assert settings.data_dir == PROJECT_ROOT / "data_platform" / "data"
    assert settings.model_artifact_path == (
        PROJECT_ROOT / "ml" / "artifacts" / "occupancy_model.joblib"
    )
    assert settings.model_preprocessor_path == (
        PROJECT_ROOT / "ml" / "artifacts" / "occupancy_preprocessor.joblib"
    )
    assert settings.model_meta_path == (
        PROJECT_ROOT / "ml" / "artifacts" / "occupancy_model_meta.json"
    )
    assert settings.wait_scoring_cap_min == 120
    assert settings.routing_timeout_s == 8
    assert settings.recommend_max_detour_min == 30
    assert settings.recommend_max_wait_min == 120
    assert settings.recommend_max_charge_min == 90
    assert settings.recommend_soc_risk_buffer == 0.20
    assert settings.recommend_candidate_corridor_m == 5_000
    assert settings.station_status_stale_after_s == 120
    assert settings.availability_green_min == 2
    assert settings.search_rate_limit_per_min == 30
    assert settings.internal_api_key is None
    assert settings.cors_origins == ("http://127.0.0.1:5173",)
    assert settings.goong_api_key is None
    assert settings.database_url.endswith("@127.0.0.1:5433/smart_ev_data")
    assert settings.catalog_storage == "database"
    assert settings.planned_arrivals_storage == "database"


def test_required_phase_data_exists() -> None:
    missing = [path for path in load_settings().required_data_paths() if not path.is_file()]

    assert missing == []
