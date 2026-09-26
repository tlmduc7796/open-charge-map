"""Environment-backed application settings and canonical project paths."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env", override=False)


def _resolve_from_root(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _read_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")


def _read_positive_float(name: str, default: float) -> float:
    value = float(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _read_csv(name: str, default: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in os.getenv(name, default).split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_env: str
    log_level: str
    demo_mode: bool
    goong_api_key: str | None
    data_dir: Path
    model_artifact_path: Path
    model_preprocessor_path: Path
    model_meta_path: Path
    wait_scoring_cap_min: float
    routing_timeout_s: float
    recommend_max_detour_min: float
    recommend_max_wait_min: float
    recommend_max_charge_min: float
    recommend_soc_risk_buffer: float
    cors_origins: tuple[str, ...]

    def required_data_paths(self) -> tuple[Path, ...]:
        return (
            self.data_dir / "static" / "stations.geojson",
            self.data_dir / "static" / "vehicles.json",
            self.data_dir / "runtime" / "station_status.json",
            self.data_dir / "runtime" / "planned_arrivals.json",
            self.data_dir / "demo" / "demo_events.json",
            self.data_dir / "demo" / "demo_scenarios.json",
            self.data_dir / "demo" / "queue_assumptions.json",
            self.data_dir / "routes" / "route_base_direct.json",
            self.data_dir / "routes" / "route_via_lavida.json",
            self.data_dir / "routes" / "route_via_deutsches_haus.json",
            self.data_dir / "ml" / "urbanev" / "source_manifest.json",
            self.data_dir / "ml" / "urbanev" / "raw" / "UrbanEVDataset.zip",
        )


def load_settings() -> Settings:
    key = os.getenv("GOONG_API_KEY", "").strip() or None
    return Settings(
        app_name="Smart EV Journey API",
        app_env=os.getenv("APP_ENV", "development"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        demo_mode=_read_bool("DEMO_MODE", True),
        goong_api_key=key,
        data_dir=_resolve_from_root(os.getenv("DATA_DIR", "data")),
        model_artifact_path=_resolve_from_root(
            os.getenv("MODEL_ARTIFACT_PATH", "ml/artifacts/occupancy_model.joblib")
        ),
        model_preprocessor_path=_resolve_from_root(
            os.getenv(
                "MODEL_PREPROCESSOR_PATH",
                "ml/artifacts/occupancy_preprocessor.joblib",
            )
        ),
        model_meta_path=_resolve_from_root(
            os.getenv("MODEL_META_PATH", "ml/artifacts/occupancy_model_meta.json")
        ),
        wait_scoring_cap_min=_read_positive_float("WAIT_SCORING_CAP_MIN", 120),
        routing_timeout_s=_read_positive_float("ROUTING_TIMEOUT_S", 8),
        recommend_max_detour_min=_read_positive_float(
            "RECOMMEND_MAX_DETOUR_MIN", 30
        ),
        recommend_max_wait_min=_read_positive_float("RECOMMEND_MAX_WAIT_MIN", 120),
        recommend_max_charge_min=_read_positive_float(
            "RECOMMEND_MAX_CHARGE_MIN", 90
        ),
        recommend_soc_risk_buffer=_read_positive_float(
            "RECOMMEND_SOC_RISK_BUFFER", 0.20
        ),
        cors_origins=_read_csv("CORS_ORIGINS", "http://127.0.0.1:5173"),
    )
