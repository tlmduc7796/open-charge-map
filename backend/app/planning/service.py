"""Application orchestration for station-planning recommendation runs."""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from backend.app.planning.api_models import (
    PlanningRecommendationRequest,
    PlanningRecommendationResponse,
    PlanningRunStatus,
    ScenarioEcho,
)
from backend.app.planning.domain import (
    PlanningDataError,
    PlanningDataRepository,
    PlanningEngine,
    PlanningEngineError,
    PlanningInfrastructureError,
    PlanningRunConfig,
)


class PlanningApplicationService:
    def __init__(
        self,
        repository: PlanningDataRepository,
        engine: PlanningEngine | None = None,
    ) -> None:
        self._repository = repository
        self._engine = engine

    def recommend(
        self, request: PlanningRecommendationRequest
    ) -> PlanningRecommendationResponse:
        run_id = f"run_{uuid4().hex}"
        config = self._to_run_config(request)

        if not request.candidate_source.candidate_ids:
            return self._invalid_input(
                request,
                run_id,
                "candidate_source.candidate_ids must contain at least one candidate ID.",
            )

        if request.profile == "public_policy" and request.policy_package is None:
            return self._invalid_input(
                request,
                run_id,
                "public_policy requires a valid policy_package.",
            )
        if request.profile == "investor_economic" and request.finance_package is None:
            return self._invalid_input(
                request,
                run_id,
                "investor_economic requires a valid finance_package.",
            )

        if request.profile != "technical_opportunity":
            return self._invalid_input(
                request,
                run_id,
                f"The {request.profile} profile is not enabled until its package adapter is available.",
            )

        if request.policy_package is not None or request.finance_package is not None:
            return self._invalid_input(
                request,
                run_id,
                "Policy and finance package adapters are not available in this MVP build.",
            )

        if self._engine is not None:
            if request.run.config_version not in {None, self._engine.config_version}:
                return self._invalid_input(
                    request,
                    run_id,
                    f"Unsupported config_version: {request.run.config_version}.",
                )
            config = replace(
                config,
                config_version=request.run.config_version or self._engine.config_version,
            )
        elif request.run.config_version is not None:
            return self._invalid_input(
                request,
                run_id,
                "The requested config_version cannot be resolved until the M2 engine is installed.",
            )

        try:
            dataset = self._repository.load_dataset(config)
        except PlanningDataError as exc:
            return self._invalid_input(request, run_id, str(exc))
        except PlanningInfrastructureError:
            raise

        if self._engine is None:
            return self._failed(
                request,
                run_id,
                "The recommendation engine is not installed yet; M2 must provide it before a run can be computed.",
            )

        try:
            engine_output = self._engine.recommend(config, dataset)
        except PlanningEngineError as exc:
            return self._failed(request, run_id, str(exc))

        payload = {
            "contract_version": "0.1",
            "run_id": run_id,
            "status": engine_output["status"],
            "recommendations": engine_output["recommendations"],
            "unranked_candidates": engine_output["unranked_candidates"],
            "excluded_candidates": engine_output["excluded_candidates"],
            "warnings": engine_output["warnings"],
            "scenario": self._scenario_echo(
                request,
                algorithm_version=self._engine.algorithm_version,
                config_version=config.config_version,
            ),
        }
        return PlanningRecommendationResponse.model_validate(payload)

    @staticmethod
    def _to_run_config(request: PlanningRecommendationRequest) -> PlanningRunConfig:
        return PlanningRunConfig(
            city_id=request.study_area.city_id,
            boundary_version=request.study_area.boundary_version,
            pilot_extent_id=request.study_area.pilot_extent_id,
            as_of=request.run.as_of,
            horizon_years=request.run.horizon_years,
            data_snapshot_id=request.run.data_snapshot_id,
            seed=request.run.seed,
            config_version=request.run.config_version,
            candidate_ids=tuple(request.candidate_source.candidate_ids),
            profile=request.profile,
            coverage_minutes=request.technical.coverage_minutes,
            charger_options=tuple(
                option.model_dump(mode="python")
                for option in request.technical.charger_options
            ),
            budget_vnd=request.technical.budget_vnd,
        )

    @staticmethod
    def _scenario_echo(
        request: PlanningRecommendationRequest,
        *,
        algorithm_version: str | None,
        config_version: str | None,
    ) -> ScenarioEcho:
        return ScenarioEcho(
            profile=request.profile,
            as_of=request.run.as_of,
            horizon_years=request.run.horizon_years,
            seed=request.run.seed,
            data_snapshot_id=request.run.data_snapshot_id,
            algorithm_version=algorithm_version,
            config_version=config_version,
            policy_package_id=None,
            policy_package_version=None,
            finance_package_id=None,
            finance_package_version=None,
        )

    @classmethod
    def _invalid_input(
        cls,
        request: PlanningRecommendationRequest,
        run_id: str,
        reason: str,
    ) -> PlanningRecommendationResponse:
        return cls._empty_response(request, run_id, "invalid_input", reason)

    @classmethod
    def _failed(
        cls,
        request: PlanningRecommendationRequest,
        run_id: str,
        reason: str,
    ) -> PlanningRecommendationResponse:
        return cls._empty_response(request, run_id, "failed", reason)

    @classmethod
    def _empty_response(
        cls,
        request: PlanningRecommendationRequest,
        run_id: str,
        status: PlanningRunStatus,
        warning: str,
    ) -> PlanningRecommendationResponse:
        return PlanningRecommendationResponse(
            contract_version="0.1",
            run_id=run_id,
            status=status,
            scenario=cls._scenario_echo(
                request,
                algorithm_version=None,
                config_version=None,
            ),
            recommendations=[],
            unranked_candidates=[],
            excluded_candidates=[],
            warnings=[warning],
        )
