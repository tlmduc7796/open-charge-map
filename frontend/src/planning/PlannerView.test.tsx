import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import { api } from "../api";
import type {
  PlanningDemoSnapshotResponse,
  PlanningRecommendation,
  PlanningRecommendationResponse,
  PlanningRequest,
} from "./types";
import PlannerView from "./PlannerView";
import { downloadPlannerReport } from "./plannerReport";

vi.mock("../api", () => ({
  api: {
    planningDemoSnapshot: vi.fn(),
    planningRecommendations: vi.fn(),
  },
}));

vi.mock("./plannerReport", async (importOriginal) => ({
  ...await importOriginal<typeof import("./plannerReport")>(),
  downloadPlannerReport: vi.fn(),
}));

vi.mock("./PlannerMap", () => ({
  default: ({
    candidates,
    existingSites,
    demandNodes,
    boundaryGeometry,
    demandScenario,
  }: {
    candidates: PlanningDemoSnapshotResponse["candidates"];
    existingSites: PlanningDemoSnapshotResponse["existing_sites"];
    demandNodes: PlanningDemoSnapshotResponse["demand_nodes"];
    boundaryGeometry: PlanningDemoSnapshotResponse["snapshot"]["geometry"] | null;
    demandScenario: "low" | "base" | "high";
  }) => (
    <div
      data-testid="planner-map"
      data-candidate-count={candidates.length}
      data-existing-site-count={existingSites.length}
      data-demand-node-count={demandNodes.length}
      data-has-boundary={String(boundaryGeometry !== null)}
      data-demand-scenario={demandScenario}
    />
  ),
}));

const candidateIds = [
  "cand-hcm_2025_26911-02",
  "cand-hcm_2025_26929-01",
  "cand-hcm_2025_27073-01",
];

function demoSnapshot(): PlanningDemoSnapshotResponse {
  return {
    contract_version: "0.1",
    study_area: {
      city_id: "VN-HCMC",
      boundary_version: "ADMINISTRATIVE_2025",
      pilot_extent_id: "hcmc-nine-wards-demo-v3",
    },
    snapshot: {
      data_snapshot_id: "hcmc-nine-wards-demo-v3",
      prepared_on: "2026-10-13",
      dataset_contract_version: "1.0",
      boundary_id: "HCMC_PILOT_9_WARDS",
      geometry: { type: "Polygon", coordinates: [[[[106.6, 10.6], [106.7, 10.6], [106.7, 10.7], [106.6, 10.6]]]] },
      properties: {},
    },
    defaults: {
      horizon_years: 3,
      seed: 20261013,
      config_version: "technical-demo-v1",
      demand_scenario: "base",
      coverage_minutes: 15,
      charger_option: { charger_type: "DC", port_count: 4, power_kw_per_port: 80 },
      budget_vnd: null,
      portfolio_budget_vnd: 10_000_000_000,
    },
    candidates: candidateIds.map((candidate_id) => ({
      candidate_id,
      label: `Candidate ${candidate_id}`,
      candidate_type: "parcel",
      eligibility: "conditional",
      is_synthetic: true,
      location: { lat: 10.65, lon: 106.65 },
      source_ref: "candidate_sites.csv",
    })),
    existing_sites: [{
      site_id: "existing-1",
      label: "Existing site",
      site_type: "charging_station",
      charger_type: "DC",
      port_count: 4,
      power_kw: 320,
      is_synthetic: true,
      location: { lat: 10.64, lon: 106.64 },
      source_ref: "existing_sites.csv",
    }],
    demand_nodes: [{
      demand_node_id: "demand-1",
      unit_id: "WARD-1",
      location: { lat: 10.66, lon: 106.66 },
      nearest_existing_access_minutes_proxy: 12,
      is_synthetic: true,
      weekly_expected_sessions: { low: 240, base: 400, high: 640 },
    }],
    warnings: [],
  };
}

function recommendation(candidateId: string, rank: number): PlanningRecommendation {
  return {
    rank,
    candidate_id: candidateId,
    location: { lat: 10.65, lon: 106.65 },
    eligibility: "conditional",
    technical_score: 72 - rank,
    evidence_coverage: 0.6,
    metrics: {
      demand_potential: { value: 1073, unit: "sessions/week", status: "synthetic" },
      coverage_gain: { value: 3.55, unit: "percent_total_demand", status: "synthetic" },
      recommended_capacity: { value: 320, unit: "kW", status: "scenario" },
      overload_risk: { value: null, unit: "ratio", status: "unknown" },
      estimated_cost: { value: 1_500_000_000, unit: "VND", status: "synthetic" },
    },
    constraints: [{ id: "grid_capacity", status: "unknown", reason: "Chưa có dữ liệu đấu nối." }],
    score_breakdown: [{
      component_id: "demand_coverage",
      score: 72,
      weight_percent: 30,
      contribution_points: 21.6,
      status: "synthetic",
      reason: "Nhu cầu theo kịch bản demo.",
    }, {
      component_id: "grid_site_readiness", score: null, weight_percent: 20,
      contribution_points: null, status: "unknown", reason: "No source-backed site/grid readiness evidence is available.",
    }],
    provenance: [{
      field: "demand_potential",
      source_id: "demand-1",
      source_ref: "demand_intervals.csv",
      status: "synthetic",
      is_synthetic: true,
      observed_at: null,
      note: "Tuần mô phỏng.",
    }],
  };
}

function planningResponse(): PlanningRecommendationResponse {
  return {
    contract_version: "0.1",
    run_id: "run-test-1",
    status: "completed_with_unknowns",
    scenario: {
      profile: "technical_opportunity",
      as_of: "2026-10-13T00:00:00Z",
      horizon_years: 3,
      seed: 20261013,
      data_snapshot_id: "hcmc-nine-wards-demo-v3",
      demand_scenario: "low",
      algorithm_version: "technical-opportunity-v1",
      config_version: "technical-demo-v1",
      policy_package_id: null,
      policy_package_version: null,
      finance_package_id: null,
      finance_package_version: null,
    },
    recommendations: [recommendation(candidateIds[0], 1), recommendation(candidateIds[1], 2)],
    unranked_candidates: [],
    excluded_candidates: [],
    warnings: ["Grid feasibility is unknown."],
  };
}

const mockedApi = vi.mocked(api);

beforeEach(() => {
  vi.mocked(downloadPlannerReport).mockClear();
  mockedApi.planningDemoSnapshot.mockResolvedValue(demoSnapshot());
  mockedApi.planningRecommendations.mockResolvedValue(planningResponse());
});

test("runs the selected planner scenario and shows map, ranking, explanation and comparison", async () => {
  render(<PlannerView onModeChange={vi.fn()} />);

  await waitFor(() => expect(screen.getByTestId("planner-map")).toHaveAttribute("data-candidate-count", "3"));
  expect(await screen.findByTestId("planner-map")).toHaveAttribute("data-candidate-count", "3");
  expect(screen.getByTestId("planner-map")).toHaveAttribute("data-existing-site-count", "1");
  expect(screen.getByTestId("planner-map")).toHaveAttribute("data-demand-node-count", "1");
  expect(screen.getByTestId("planner-map")).toHaveAttribute("data-has-boundary", "true");

  fireEvent.change(screen.getByLabelText(/Mức nhu cầu sạc/), { target: { value: "low" } });
  expect(screen.getByTestId("planner-map")).toHaveAttribute("data-demand-scenario", "low");
  expect(mockedApi.planningRecommendations).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText(/Thời gian đến trạm tối đa/), { target: { value: "5" } });
  fireEvent.click(screen.getByRole("button", { name: /Đánh giá địa điểm/ }));

  await waitFor(() => expect(mockedApi.planningRecommendations).toHaveBeenCalledTimes(1));
  const request = mockedApi.planningRecommendations.mock.calls[0][0] as PlanningRequest;
  expect(request.run).toEqual(expect.objectContaining({
    data_snapshot_id: "hcmc-nine-wards-demo-v3",
    demand_scenario: "low",
  }));
  expect(request.candidate_source.candidate_ids).toEqual(candidateIds);
  expect(request.technical).toEqual(expect.objectContaining({ coverage_minutes: 5, budget_vnd: null }));

  expect(await screen.findByText("Đã đánh giá")).toBeInTheDocument();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(screen.queryByText(/Cần xác minh|Chưa chấm|No source-backed|Chưa có dữ liệu đấu nối/)).not.toBeInTheDocument();
  expect(screen.getByRole("region", { name: `Giải thích ${candidateIds[0]}` })).toHaveTextContent("Điểm đánh giá");
  fireEvent.click(screen.getByRole("button", { name: "Tải báo cáo" }));
  const [markdown, reportId] = vi.mocked(downloadPlannerReport).mock.calls.at(-1)!;
  expect(reportId).toBe("run-test-1");
  expect(markdown).toContain("Grid feasibility is unknown.");
  expect(markdown).toContain("No source-backed");
  expect(markdown).toContain("Chưa có dữ liệu đấu nối.");
  expect(markdown).toContain("demand-1");
  expect(markdown).toContain('"coverage_minutes": 5');

  const compareButtons = screen.getAllByRole("button", { name: "So sánh" });
  fireEvent.click(compareButtons[0]);
  fireEvent.click(compareButtons[1]);
  expect(screen.getByRole("region", { name: "So sánh hai phương án" })).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "So sánh hai phương án" })).not.toHaveTextContent("No source-backed");
});

test("shows a recoverable error when a planning run fails", async () => {
  mockedApi.planningRecommendations.mockRejectedValueOnce(new Error("Planning API unavailable"));
  render(<PlannerView onModeChange={vi.fn()} />);

  fireEvent.click(await screen.findByRole("button", { name: /Đánh giá địa điểm/ }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Planning API unavailable");
  expect(screen.queryByText("run-test-1")).not.toBeInTheDocument();
});

test("shows excluded candidates when the scenario has no feasible option", async () => {
  mockedApi.planningRecommendations.mockResolvedValueOnce({
    ...planningResponse(),
    run_id: "run-no-feasible",
    status: "no_feasible_candidates",
    recommendations: [],
    excluded_candidates: candidateIds.map((candidate_id) => ({
      candidate_id,
      constraints: [{
        id: "individual_budget",
        status: "fail",
        reason: "CAPEX giả định vượt ngân sách kịch bản đã nhập.",
      }],
    })),
  });
  render(<PlannerView onModeChange={vi.fn()} />);

  await waitFor(() => expect(screen.getByTestId("planner-map")).toHaveAttribute("data-candidate-count", "3"));
  fireEvent.change(screen.getByLabelText(/Chi phí xây mỗi trạm tối đa/), { target: { value: "1" } });
  fireEvent.click(await screen.findByRole("button", { name: /Đánh giá địa điểm/ }));

  expect(await screen.findByText("Không có kết quả với thiết lập này")).toBeInTheDocument();
  expect(screen.queryByText("Không đáp ứng điều kiện · 3")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Tải báo cáo" }));
  const [markdown] = vi.mocked(downloadPlannerReport).mock.calls.at(-1)!;
  expect(markdown).toContain("CAPEX giả định vượt ngân sách kịch bản đã nhập.");
  for (const candidateId of candidateIds) expect(markdown).toContain(candidateId);

  const request = mockedApi.planningRecommendations.mock.calls.at(-1)?.[0] as PlanningRequest;
  expect(request.technical.budget_vnd).toBe(1);
});


test("map focus mode preserves input state and can be closed with Escape", async () => {
  render(<PlannerView onModeChange={vi.fn()} />);
  await waitFor(() => expect(screen.getByTestId("planner-map")).toHaveAttribute("data-candidate-count", "3"));
  fireEvent.change(screen.getByLabelText(/Thời gian đến trạm tối đa/), { target: { value: "5" } });
  fireEvent.click(screen.getByRole("button", { name: "Phóng to bản đồ" }));
  expect(screen.getByRole("button", { name: "Thu gọn bản đồ" })).toHaveAttribute("aria-pressed", "true");
  fireEvent.keyDown(window, { key: "Escape" });
  expect(screen.getByRole("button", { name: "Phóng to bản đồ" })).toHaveAttribute("aria-pressed", "false");
  expect(screen.getByLabelText(/Thời gian đến trạm tối đa/)).toHaveValue(5);
});

test("searching candidates does not clear the existing selection", async () => {
  const snapshot = demoSnapshot();
  snapshot.candidates[0].label = "Vị trí ứng viên A – Thạnh Mỹ Tây";
  mockedApi.planningDemoSnapshot.mockResolvedValueOnce(snapshot);
  render(<PlannerView onModeChange={vi.fn()} />);
  await waitFor(() => expect(screen.getByTestId("planner-map")).toHaveAttribute("data-candidate-count", "3"));
  fireEvent.change(screen.getByRole("searchbox", { name: "Tìm địa điểm" }), { target: { value: "thanh my tay" } });
  expect(screen.getAllByRole("checkbox")).toHaveLength(1);
  expect(screen.getByRole("checkbox", { name: "Vị trí ứng viên A – Thạnh Mỹ Tây" })).toBeChecked();
  fireEvent.click(screen.getByRole("button", { name: /Đánh giá địa điểm/ }));
  await waitFor(() => expect(mockedApi.planningRecommendations).toHaveBeenCalled());
  expect(mockedApi.planningRecommendations.mock.calls.at(-1)?.[0].candidate_source.candidate_ids).toEqual(candidateIds);
});
