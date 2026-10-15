import { expect, test } from "vitest";
import { driveMinutes, loadLevel, simulateStationLoad } from "./stationLoad";
import type { PlanningDemoSnapshotResponse, PlanningLoadInputs, PlanningRecommendation } from "./types";

const location = { lat: 10.8, lon: 106.7 };
const inputs: PlanningLoadInputs = {
  version: "peak-load-demo-v1", interval_minutes: 30, nearby_drive_minutes: 2,
  circuity_factor: 1.3, speed_kmh: 20, fixed_access_minutes: 2,
  energy_per_session_kwh: 26, grid_delivery_efficiency: 0.93,
  minimum_service_minutes: 30, comfortable_utilization: 0.8,
  peak_by_scenario: {
    low: { interval_start: "2025-07-12T18:00:00+07:00", sessions_by_node: { node: 2.4 } },
    base: { interval_start: "2025-07-12T18:00:00+07:00", sessions_by_node: { node: 4 } },
    high: { interval_start: "2025-07-12T18:00:00+07:00", sessions_by_node: { node: 6.4 } },
  },
};
function fixture() {
  return {
    load_simulation: structuredClone(inputs),
    existing_sites: [{ site_id: "existing", unit_id: "ward", label: "Trạm cũ", site_type: "urban", charger_type: "DC",
      port_count: 1, power_kw: 80, is_synthetic: true, location, source_ref: null }],
    candidates: [{ candidate_id: "new", unit_id: "ward", label: "Trạm mới", candidate_type: "parcel", eligibility: "conditional" as const,
      is_synthetic: true, location, source_ref: null }],
    demand_nodes: [{ demand_node_id: "node", unit_id: "ward", location, is_synthetic: true,
      nearest_existing_access_minutes_proxy: 2, weekly_expected_sessions: { low: 24, base: 40, high: 64 } }],
  } satisfies Pick<PlanningDemoSnapshotResponse, "load_simulation" | "existing_sites" | "candidates" | "demand_nodes">;
}
const recommendation: PlanningRecommendation = {
  rank: 1, candidate_id: "new", location, eligibility: "conditional", technical_score: 70, evidence_coverage: 0.65,
  metrics: {}, constraints: [], score_breakdown: [], provenance: [],
};
function run(demo = fixture(), recommendations: PlanningRecommendation[] = [recommendation], portCount = 4) {
  return simulateStationLoad({ demo, scenario: "base", coverageMinutes: 15, recommendations,
    chargerOption: { charger_type: "DC", port_count: portCount, power_kw_per_port: 80 } })!;
}

test("conserves demand and reduces overload through shared capacity, not ranking score", () => {
  const simulation = run();
  expect(simulation.baseline.stations.existing.utilization).toBeCloseTo(4);
  expect(simulation.proposed.stations.existing.utilization).toBeCloseTo(0.8);
  expect(simulation.proposed.stations.new.utilization).toBeCloseTo(0.8);
  for (const network of [simulation.baseline, simulation.proposed]) {
    expect(Object.values(network.stations).reduce((sum, site) => sum + site.sessions, network.unassigned)).toBeCloseTo(network.totalDemand);
  }
  expect(simulation.baseline.existingOverloaded).toBe(1);
  expect(simulation.proposed.existingOverloaded).toBe(0);
  expect(simulation.proposed.totalExcess).toBe(0);
  expect(run(fixture(), [{ ...recommendation, technical_score: 0 }]).proposed).toEqual(simulation.proposed);
});

test("unranked candidates add no capacity; duplicate recommendations never duplicate ports", () => {
  const noProposal = run(fixture(), []);
  expect(noProposal.addedIds).toEqual([]);
  expect(noProposal.baseline).toEqual(noProposal.proposed);
  expect(run(fixture(), [recommendation, recommendation]).addedIds).toEqual(["new"]);
});

test("a small proposal cannot hide excess or overload a new station beyond its reserve target", () => {
  const simulation = run(fixture(), [recommendation], 1);
  expect(simulation.proposed.stations.new.utilization).toBeCloseTo(0.8);
  expect(simulation.proposed.stations.existing.utilization).toBeCloseTo(3.2);
  expect(simulation.proposed.totalExcess).toBeCloseTo(2.2);
});

test("a candidate beyond the access threshold cannot relieve an old station", () => {
  const demo = fixture();
  demo.candidates[0].location = { lat: 10.85, lon: 106.7 };
  expect(run(demo).proposed.stations.existing.sessions).toBe(4);
  expect(run(demo).proposed.stations.new.sessions).toBe(0);
});

test("a same-ward candidate beyond 2 minutes can relieve load when within the access threshold", () => {
  const demo = fixture();
  demo.candidates[0].location = { lat: 10.82, lon: 106.7 };
  const travel = driveMinutes(location, demo.candidates[0].location, inputs);
  expect(travel).toBeGreaterThan(inputs.nearby_drive_minutes);
  expect(travel + inputs.fixed_access_minutes).toBeLessThan(15);
  const simulation = run(demo);
  expect(simulation.proposed.stations.existing.utilization).toBeCloseTo(0.8);
  expect(simulation.proposed.stations.new.sessions).toBeCloseTo(3.2);
  expect(simulation.proposed.transfers[0].wardId).toBe("ward");
  expect(simulation.proposed.transfers[0].driveMinutes).toBeGreaterThan(2);
});

test("a nearby candidate can relieve local load without changing total demand", () => {
  const demo = fixture();
  demo.candidates[0].location = { lat: 10.803, lon: 106.7 };
  expect(driveMinutes(location, demo.candidates[0].location, inputs)).toBeLessThan(2);
  const simulation = run(demo);
  expect(simulation.proposed.stations.existing.utilization).toBeCloseTo(0.8);
  expect(simulation.proposed.transfers).toHaveLength(1);
  expect(simulation.proposed.transfers[0].driveMinutes).toBeLessThan(2);
});

test("a nearby candidate in another ward cannot receive existing station load", () => {
  const demo = fixture();
  demo.candidates[0].unit_id = "other-ward";
  const simulation = run(demo);
  expect(simulation.proposed.stations.existing.sessions).toBe(4);
  expect(simulation.proposed.transfers).toEqual([]);
});

test("the receiving ward matches the old station even when the originating node crosses a ward border", () => {
  const demo = fixture();
  demo.demand_nodes[0].unit_id = "border-ward";
  expect(run(demo).proposed.stations.existing.utilization).toBeCloseTo(0.8);
  demo.candidates[0].unit_id = "border-ward";
  expect(run(demo).proposed.transfers).toEqual([]);
});

test("unknown ward IDs never match each other and no ward is inferred from an ID", () => {
  const demo = fixture();
  demo.candidates[0].unit_id = "unknown";
  demo.existing_sites[0].unit_id = "unknown";
  expect(run(demo).proposed.transfers).toEqual([]);
  const missing = { ...fixture(), candidates: fixture().candidates.map((site) => ({ ...site, unit_id: undefined })) };
  expect(simulateStationLoad({ demo: missing, scenario: "base", coverageMinutes: 15, recommendations: [recommendation],
    chargerOption: { charger_type: "DC", port_count: 4, power_kw_per_port: 80 } })!.proposed.transfers).toEqual([]);
});

test("unassigned demand uses the node ward rather than the ward of a station with unknown capacity", () => {
  const demo = fixture();
  demo.existing_sites[0].port_count = 0;
  demo.existing_sites[0].unit_id = "other-ward";
  const served = run(demo);
  expect(served.baseline.unassigned).toBe(4);
  expect(served.proposed.unassigned).toBeCloseTo(0.8);
  expect(served.proposed.transfers[0].fromSiteId).toBeNull();
  expect(served.proposed.transfers[0].wardId).toBe("ward");
  demo.candidates[0].unit_id = "other-ward";
  expect(run(demo).proposed.unassigned).toBe(4);
});

test("missing capacity stays unknown and unmet demand is conserved", () => {
  const demo = fixture();
  const incomplete: Parameters<typeof simulateStationLoad>[0]["demo"] = {
    ...demo, existing_sites: [{ ...demo.existing_sites[0], port_count: null }],
  };
  const simulation = simulateStationLoad({ demo: incomplete, scenario: "base", coverageMinutes: 15,
    recommendations: [], chargerOption: { charger_type: "DC", port_count: 4, power_kw_per_port: 80 } })!;
  expect(simulation.baseline.stations.existing.utilization).toBeNull();
  expect(simulation.baseline.stations.existing.level).toBe("unknown");
  expect(simulation.baseline.unassigned).toBe(4);
});

test("travel time excludes the fixed entry time, which still gates reachability", () => {
  expect(driveMinutes(location, location, inputs)).toBe(0);
  const simulation = simulateStationLoad({ demo: fixture(), scenario: "base", coverageMinutes: 1,
    recommendations: [], chargerOption: { charger_type: "DC", port_count: 4, power_kw_per_port: 80 } })!;
  expect(simulation.baseline.unassigned).toBe(4);
});

test("lower power decreases service capacity and higher demand increases load", () => {
  const demo = fixture();
  demo.existing_sites[0].power_kw = 7;
  expect(run(demo, []).baseline.stations.existing.capacity).toBeCloseTo(0.1251923);
  const high = simulateStationLoad({ demo: fixture(), scenario: "high", coverageMinutes: 15,
    recommendations: [], chargerOption: { charger_type: "DC", port_count: 4, power_kw_per_port: 80 } })!;
  expect(high.baseline.stations.existing.utilization).toBeCloseTo(6.4);
});

test("handles zero demand, missing simulation and classification boundaries", () => {
  const demo = fixture();
  demo.load_simulation.peak_by_scenario.base.sessions_by_node.node = 0;
  expect(run(demo).baseline.stations.existing.utilization).toBe(0);
  expect(simulateStationLoad({ demo: { ...demo, load_simulation: null }, scenario: "base", coverageMinutes: 15,
    recommendations: [], chargerOption: { charger_type: "DC", port_count: 4, power_kw_per_port: 80 } })).toBeNull();
  expect([0.8, 1, 1.25, 1.26, null].map((value) => loadLevel(value))).toEqual(["normal", "busy", "overloaded", "severe", "unknown"]);
});
