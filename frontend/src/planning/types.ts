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
    demand_scenario: "low" | "base" | "high";
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
    demand_scenario: "low" | "base" | "high";
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

export interface PlanningLoadInputs {
  version: "peak-load-demo-v1";
  interval_minutes: number;
  nearby_drive_minutes: number;
  circuity_factor: number;
  speed_kmh: number;
  fixed_access_minutes: number;
  energy_per_session_kwh: number;
  grid_delivery_efficiency: number;
  minimum_service_minutes: number;
  comfortable_utilization: number;
  peak_by_scenario: Record<"low" | "base" | "high", {
    interval_start: string;
    sessions_by_node: Record<string, number>;
  }>;
}

export interface PlanningDemoSnapshotResponse {
  load_simulation?: PlanningLoadInputs | null;
  contract_version: "0.1";
  study_area: {
    city_id: string;
    boundary_version: string;
    pilot_extent_id: string;
  };
  snapshot: {
    data_snapshot_id: string;
    prepared_on: string;
    dataset_contract_version: string;
    boundary_id: string;
    geometry: {
      type: "Polygon" | "MultiPolygon";
      coordinates: number[][][][] | number[][][];
    };
    properties: Record<string, unknown>;
  };
  defaults: {
    horizon_years: number;
    seed: number;
    config_version: string;
    demand_scenario: "low" | "base" | "high";
    coverage_minutes: number;
    charger_option: {
      charger_type: "AC" | "DC";
      port_count: number;
      power_kw_per_port: number;
    };
    budget_vnd: number | null;
    portfolio_budget_vnd: number | null;
  };
  candidates: {
    candidate_id: string;
    unit_id?: string | null;
    unit_name?: string | null;
    label: string;
    candidate_type: string;
    eligibility: "eligible" | "conditional";
    is_synthetic: boolean;
    location: { lat: number; lon: number };
    source_ref: string | null;
  }[];
  existing_sites: {
    site_id: string;
    unit_id?: string | null;
    unit_name?: string | null;
    label: string;
    site_type: string;
    charger_type: string;
    port_count: number | null;
    power_kw: number | null;
    is_synthetic: boolean;
    location: { lat: number; lon: number };
    source_ref: string | null;
  }[];
  demand_nodes: {
    demand_node_id: string;
    unit_id: string;
    location: { lat: number; lon: number };
    nearest_existing_access_minutes_proxy: number;
    is_synthetic: boolean;
    weekly_expected_sessions: Record<"low" | "base" | "high", number>;
  }[];
  warnings: string[];
}
