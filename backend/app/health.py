"""Startup/readiness checks for demo hardening (Phase 11).

`/health` stays a minimal liveness probe. These checks answer "is this instance
ready to demo?": required data files, route-cache coverage, occupancy model artifact
and external API configuration. A missing model or Goong key only *degrades* the demo
(persistence forecast / route cache still work); missing data files are a failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from backend.app.config import Settings
from backend.app.domain.forecasting import OccupancyForecastService
from backend.app.domain.repositories import DomainData

CheckStatus = Literal["ok", "warn", "fail"]
OverallStatus = Literal["ok", "degraded", "fail"]


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: CheckStatus
    detail: str
    flags: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "flags": list(self.flags),
        }


def _check_data_files(settings: Settings) -> CheckResult:
    # The UrbanEV raw archive is ML source data, not needed to run the demo.
    required = [
        path
        for path in settings.required_data_paths()
        if "ml" not in path.relative_to(settings.data_dir).parts
    ]
    missing = [str(path.relative_to(settings.data_dir)) for path in required if not path.is_file()]
    if missing:
        return CheckResult(
            "data_files",
            "fail",
            f"{len(missing)} required data file(s) missing: {', '.join(missing)}",
            ("DATA_FILES_MISSING",),
        )
    return CheckResult("data_files", "ok", f"{len(required)} required data files present")


def _check_route_cache(data: DomainData) -> CheckResult:
    uncovered = [
        station.station_id
        for station in data.stations.all()
        if station.properties.access == "public"
        and data.routes.find_by_station(station.station_id) is None
    ]
    if uncovered:
        return CheckResult(
            "route_cache_coverage",
            "warn",
            "public stations without a cached route (need live routing): "
            + ", ".join(uncovered),
            ("ROUTE_CACHE_INCOMPLETE",),
        )
    return CheckResult(
        "route_cache_coverage", "ok", "every public station has a cached route"
    )


def _check_model(settings: Settings, forecasting: OccupancyForecastService) -> CheckResult:
    artifacts = {
        "model": settings.model_artifact_path.is_file(),
        "preprocessor": settings.model_preprocessor_path.is_file(),
        "metadata": settings.model_meta_path.is_file(),
    }
    if not all(artifacts.values()):
        missing = ", ".join(name for name, present in artifacts.items() if not present)
        return CheckResult(
            "occupancy_model",
            "warn",
            f"artifact missing ({missing}); using persistence forecast",
            ("PHASE_04_ARTIFACTS_UNAVAILABLE",),
        )
    if not forecasting.model_loaded:
        return CheckResult(
            "occupancy_model",
            "warn",
            "artifacts present but no model adapter is loaded; using persistence forecast",
            ("MODEL_ADAPTER_NOT_LOADED",),
        )
    return CheckResult("occupancy_model", "ok", "model adapter loaded")


def _check_goong(settings: Settings) -> CheckResult:
    if settings.goong_api_key:
        return CheckResult("goong_api", "ok", "GOONG_API_KEY configured")
    return CheckResult(
        "goong_api",
        "warn",
        "GOONG_API_KEY not set; fixed scenarios use route cache, custom places use demo fallback",
        ("GOONG_NOT_CONFIGURED",),
    )


def run_startup_checks(
    settings: Settings,
    data: DomainData,
    forecasting: OccupancyForecastService,
) -> dict[str, object]:
    checks = (
        _check_data_files(settings),
        _check_route_cache(data),
        _check_model(settings, forecasting),
        _check_goong(settings),
    )
    overall: OverallStatus
    if any(check.status == "fail" for check in checks):
        overall = "fail"
    elif any(check.status == "warn" for check in checks):
        overall = "degraded"
    else:
        overall = "ok"
    return {
        "status": overall,
        "service": settings.app_name,
        "demo_ready": overall != "fail",
        "checks": [check.as_dict() for check in checks],
    }