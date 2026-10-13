export type PlanningProfile = "technical_opportunity" | "public_policy" | "investor_economic";

export type PlanningDataStatus =
  | "observed"
  | "proxy"
  | "synthetic"
  | "scenario"
  | "unknown"
  | "not_applicable";

export type PlanningConstraintStatus =
  | "pass"
  | "fail"
  | "conditional"
  | "unknown"
  | "not_applicable";

export type PlanningRunStatus =
  | "completed"
  | "completed_with_unknowns"
  | "invalid_input"
  | "no_feasible_candidates"
  | "failed";

export interface PlanningPackageInput {
  package_id: string;
  version: string;
  [key: string]: unknown;
}

export interface PlanningRequest {
  contract_version: "0.1";
  study_area: {
    city_id: string;
    boundary_version: string;
    pilot_extent_id: string;
  };
  run: {
    as_of: string;
    horizon_years: number;
    data_snapshot_id: string;
    seed: number;
    config_version: string | null;
  };
  candidate_source: {
    mode: "provided";
    candidate_ids: string[];
  };
  profile: PlanningProfile;
  technical: {
    coverage_minutes: number;
    charger_options: { charger_type: "AC" | "DC"; port_count: number; power_kw_per_port: number }[];
    budget_vnd: number | null;
  };
  policy_package: PlanningPackageInput | null;
  finance_package: PlanningPackageInput | null;
}

export interface PlanningMetric {
  value: number | string | null;
  unit: string;
  status: PlanningDataStatus;
}

export interface PlanningConstraint {
  id: string;
  status: PlanningConstraintStatus;
  reason: string;
}

export interface PlanningScoreComponent {
  component_id: string;
  score: number | null;
  weight_percent: number | null;
  contribution_points: number | null;
  status: PlanningDataStatus;
  reason: string;
}

export interface PlanningProvenance {
  field: string;
  source_id: string | null;
  source_ref: string | null;
  status: PlanningDataStatus;
  is_synthetic: boolean;
  observed_at: string | null;
  note: string | null;
}

export interface PlanningRecommendation {
  rank: number;
  candidate_id: string;
  location: { lat: number; lon: number };
  eligibility: "eligible" | "conditional";
  technical_score: number;
  evidence_coverage: number;
  metrics: Record<string, PlanningMetric>;
  constraints: PlanningConstraint[];
  score_breakdown: PlanningScoreComponent[];
  provenance: PlanningProvenance[];
}

export interface PlanningRecommendationResponse {
  contract_version: "0.1";
  run_id: string;
  status: PlanningRunStatus;
  scenario: {
    profile: PlanningProfile;
    as_of: string;
    horizon_years: number;
    seed: number;
    data_snapshot_id: string;
    algorithm_version: string | null;
    config_version: string | null;
    policy_package_id: string | null;
    policy_package_version: string | null;
    finance_package_id: string | null;
    finance_package_version: string | null;
  };
  recommendations: PlanningRecommendation[];
  unranked_candidates: { candidate_id: string; reason: string }[];
  excluded_candidates: { candidate_id: string; constraints: PlanningConstraint[] }[];
  warnings: string[];
}
