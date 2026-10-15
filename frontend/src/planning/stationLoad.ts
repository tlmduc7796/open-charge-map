import type { PlanningDemoSnapshotResponse, PlanningLoadInputs, PlanningRecommendation, PlanningRequest } from "./types";

type Location = { lat: number; lon: number };
type ChargerOption = PlanningRequest["technical"]["charger_options"][number];
export type LoadLevel = "normal" | "busy" | "overloaded" | "severe" | "unknown";
export const LOAD_STYLES = {
  normal: { color: "#16a34a", label: "Trong khả năng phục vụ" },
  busy: { color: "#d97706", label: "Gần đầy tải" },
  overloaded: { color: "#ef4444", label: "Quá tải" },
  severe: { color: "#991b1b", label: "Quá tải cao" },
  unknown: { color: "#94a3b8", label: "Chưa xác định" },
} as const;

export interface StationLoad {
  id: string;
  kind: "existing" | "candidate";
  sessions: number;
  capacity: number | null;
  utilization: number | null;
  excess: number;
  level: LoadLevel;
}
interface LoadSite {
  id: string;
  kind: StationLoad["kind"];
  location: Location;
  ports: number | null;
  powerKw: number | null;
  unitId: string | null;
}
interface Allocation { nodeId: string; siteId: string | null; sessions: number }
export interface LoadTransfer {
  wardId: string;
  nodeId: string;
  fromSiteId: string | null;
  toCandidateId: string;
  sessions: number;
  driveMinutes: number;
}
export interface NetworkLoad {
  transfers: LoadTransfer[];
  stations: Record<string, StationLoad>;
  totalDemand: number;
  unassigned: number;
  existingOverloaded: number;
  existingExcess: number;
  totalExcess: number;
}
export interface LoadSimulation {
  modelVersion: "ward-relief-v3";
  baseline: NetworkLoad;
  proposed: NetworkLoad;
  addedIds: string[];
  inputs: PlanningLoadInputs;
  intervalStart: string;
  scenario: "low" | "base" | "high";
}

export function driveMinutes(from: Location, to: Location, inputs: PlanningLoadInputs): number {
  const radians = (value: number) => value * Math.PI / 180;
  const dLat = radians(to.lat - from.lat);
  const dLon = radians(to.lon - from.lon);
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(radians(from.lat)) * Math.cos(radians(to.lat)) * Math.sin(dLon / 2) ** 2;
  const km = 6371.0088 * 2 * Math.asin(Math.min(1, Math.sqrt(a)));
  return km * inputs.circuity_factor / inputs.speed_kmh * 60;
}

export function loadLevel(utilization: number | null, comfortable = 0.8): LoadLevel {
  if (utilization === null || !Number.isFinite(utilization)) return "unknown";
  if (utilization <= comfortable + 1e-9) return "normal";
  if (utilization <= 1 + 1e-9) return "busy";
  if (utilization <= 1.25 + 1e-9) return "overloaded";
  return "severe";
}

function capacity(site: LoadSite, inputs: PlanningLoadInputs): number | null {
  if (!site.ports || site.ports <= 0 || !site.powerKw || site.powerKw <= 0) return null;
  const serviceMinutes = Math.max(inputs.minimum_service_minutes,
    inputs.energy_per_session_kwh / (site.powerKw / site.ports * inputs.grid_delivery_efficiency) * 60);
  return site.ports * inputs.interval_minutes / serviceMinutes;
}

function summarize(stations: Record<string, StationLoad>, totalDemand: number, unassigned: number,
  inputs: PlanningLoadInputs): NetworkLoad {
  let existingOverloaded = 0;
  let existingExcess = 0;
  let totalExcess = 0;
  for (const station of Object.values(stations)) {
    if (station.capacity === null) continue;
    station.utilization = station.sessions / station.capacity;
    station.excess = Math.max(0, station.sessions - station.capacity);
    station.level = loadLevel(station.utilization, inputs.comfortable_utilization);
    totalExcess += station.excess;
    if (station.kind === "existing") {
      existingExcess += station.excess;
      if (station.utilization > 1 + 1e-9) existingOverloaded++;
    }
  }
  return { stations, totalDemand, unassigned, existingOverloaded, existingExcess, totalExcess, transfers: [] };
}

function assignDemand(sites: LoadSite[], nodes: PlanningDemoSnapshotResponse["demand_nodes"],
  sessions: Record<string, number>, inputs: PlanningLoadInputs, coverageMinutes: number) {
  const stations: Record<string, StationLoad> = Object.fromEntries(sites.map((site) => [site.id, {
    id: site.id, kind: site.kind, sessions: 0, capacity: capacity(site, inputs),
    utilization: null, excess: 0, level: "unknown" as LoadLevel,
  }]));
  let totalDemand = 0;
  let unassigned = 0;
  const allocations: Allocation[] = [];
  for (const node of nodes) {
    const demand = sessions[node.demand_node_id];
    if (!Number.isFinite(demand) || demand < 0) throw new Error("Invalid peak demand input");
    totalDemand += demand;
    const reachable = sites.map((site) => ({ site, minutes: driveMinutes(node.location, site.location, inputs) }))
      .filter(({ site, minutes }) => stations[site.id].capacity !== null
        && minutes + inputs.fixed_access_minutes <= coverageMinutes + 1e-9);
    const nearby = reachable.filter(({ minutes }) => minutes <= inputs.nearby_drive_minutes + 1e-9);
    const choices = nearby.length ? nearby : reachable;
    // Capacity and distance influence choice, but demand is not capped: excess stays visible.
    const weights = choices.map(({ site, minutes }) => stations[site.id].capacity! / (minutes + 0.5) ** 2);
    const totalWeight = weights.reduce((sum, value) => sum + value, 0);
    if (totalWeight === 0) {
      unassigned += demand;
      allocations.push({ nodeId: node.demand_node_id, siteId: null, sessions: demand });
      continue;
    }
    choices.forEach(({ site }, index) => {
      const share = demand * weights[index] / totalWeight;
      stations[site.id].sessions += share;
      allocations.push({ nodeId: node.demand_node_id, siteId: site.id, sessions: share });
    });
  }
  return { network: summarize(stations, totalDemand, unassigned, inputs), allocations };
}

function relieveLoad(baseline: NetworkLoad, allocations: Allocation[], existing: LoadSite[], added: LoadSite[],
  nodes: PlanningDemoSnapshotResponse["demand_nodes"], inputs: PlanningLoadInputs, coverageMinutes: number): NetworkLoad {
  const stations = Object.fromEntries(Object.entries(baseline.stations).map(([id, site]) => [id, { ...site }]));
  const remaining = Object.fromEntries(Object.values(baseline.stations).map((site) => [site.id,
    site.capacity === null ? 0 : Math.max(0, site.sessions - site.capacity * inputs.comfortable_utilization)]));
  const nodeLocations = new Map(nodes.map((node) => [node.demand_node_id, node.location]));
  const nodeWards = new Map(nodes.map((node) => [node.demand_node_id, wardId(node.unit_id)]));
  const siteWards = new Map(existing.map((site) => [site.id, site.unitId]));
  const sourceWard = (flow: Allocation) => flow.siteId === null ? nodeWards.get(flow.nodeId) : siteWards.get(flow.siteId);
  for (const site of added) stations[site.id] = { id: site.id, kind: "candidate", sessions: 0,
    capacity: capacity(site, inputs), utilization: null, excess: 0, level: "unknown" };
  const flows = allocations.map((allocation) => ({ ...allocation }));
  const links = flows.flatMap((flow) => added.map((site, rank) => ({
    flow, site, rank, minutes: driveMinutes(nodeLocations.get(flow.nodeId)!, site.location, inputs),
  }))).filter(({ flow, site, minutes }) => stations[site.id].capacity !== null
    && minutes + inputs.fixed_access_minutes <= coverageMinutes + 1e-9
    // Existing load can only move to a new site in the old station's ward.
    // Unassigned demand uses its origin node's ward. Unknown wards never match.
    && site.unitId !== null && site.unitId === sourceWard(flow));
  // Greedy relief plan: uncovered demand first, then the most pressured old station;
  // shortest drive next. Ranking is only a tie breaker, never a reduction multiplier.
  links.sort((a, b) => {
    const priority = (flow: Allocation) => flow.siteId === null ? Number.MAX_VALUE : baseline.stations[flow.siteId].utilization ?? 0;
    return priority(b.flow) - priority(a.flow) || a.minutes - b.minutes || a.rank - b.rank
      || a.flow.nodeId.localeCompare(b.flow.nodeId) || a.site.id.localeCompare(b.site.id);
  });
  let unassigned = baseline.unassigned;
  const transfers: LoadTransfer[] = [];
  for (const { flow, site, minutes } of links) {
    const receiving = stations[site.id];
    const spare = Math.max(0, receiving.capacity! * inputs.comfortable_utilization - receiving.sessions);
    const transfer = Math.min(flow.sessions, flow.siteId === null ? flow.sessions : remaining[flow.siteId], spare);
    if (transfer <= 0) continue;
    transfers.push({ wardId: site.unitId!, nodeId: flow.nodeId, fromSiteId: flow.siteId,
      toCandidateId: site.id, sessions: transfer, driveMinutes: minutes });
    flow.sessions -= transfer;
    receiving.sessions += transfer;
    if (flow.siteId === null) unassigned -= transfer;
    else {
      stations[flow.siteId].sessions -= transfer;
      remaining[flow.siteId] -= transfer;
    }
  }
  return { ...summarize(stations, baseline.totalDemand, Math.max(0, unassigned), inputs), transfers };
}

function wardId(value: string | null | undefined): string | null {
  const id = value?.trim();
  return id && id !== "unknown" ? id : null;
}

export function simulateStationLoad({ demo, scenario, coverageMinutes, recommendations, chargerOption }: {
  demo: Pick<PlanningDemoSnapshotResponse, "load_simulation" | "existing_sites" | "candidates" | "demand_nodes">;
  scenario: "low" | "base" | "high";
  coverageMinutes: number;
  recommendations: PlanningRecommendation[];
  chargerOption: ChargerOption;
}): LoadSimulation | null {
  const inputs = demo.load_simulation;
  if (!inputs) return null;
  const peak = inputs.peak_by_scenario[scenario];
  const existing: LoadSite[] = demo.existing_sites.map((site) => ({ id: site.site_id, kind: "existing",
    location: site.location, ports: site.port_count, powerKw: site.power_kw, unitId: wardId(site.unit_id) }));
  const accepted = new Set(recommendations.map((item) => item.candidate_id));
  const ranks = new Map(recommendations.map((item) => [item.candidate_id, item.rank]));
  const added: LoadSite[] = demo.candidates.filter((site) => accepted.has(site.candidate_id))
    .sort((a, b) => (ranks.get(a.candidate_id) ?? 0) - (ranks.get(b.candidate_id) ?? 0) || a.candidate_id.localeCompare(b.candidate_id)).map((site) => ({
    id: site.candidate_id, kind: "candidate", location: site.location,
    ports: chargerOption.port_count, powerKw: chargerOption.port_count * chargerOption.power_kw_per_port,
    unitId: wardId(site.unit_id),
  }));
  const baseline = assignDemand(existing, demo.demand_nodes, peak.sessions_by_node, inputs, coverageMinutes);
  return {
    modelVersion: "ward-relief-v3",
    baseline: baseline.network,
    proposed: relieveLoad(baseline.network, baseline.allocations, existing, added, demo.demand_nodes, inputs, coverageMinutes),
    addedIds: added.map((site) => site.id), inputs, intervalStart: peak.interval_start, scenario,
  };
}

export function loadPercent(value: number | null): string {
  return value === null ? "—" : `${(value * 100).toLocaleString("vi-VN", { maximumFractionDigits: 0 })}%`;
}
