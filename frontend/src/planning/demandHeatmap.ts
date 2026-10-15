import type { PlanningDemoSnapshotResponse } from "./types";

export type DemandScenario = "low" | "base" | "high";
export type DemandNode = PlanningDemoSnapshotResponse["demand_nodes"][number];
export const DEMAND_COLORS = ["#facc15", "#fb923c", "#f97316", "#dc2626"] as const;
export const DEMAND_LABELS = ["Thấp", "Vừa", "Cao", "Rất cao"] as const;
export const DEMAND_SCENARIO_LABELS: Record<DemandScenario, string> = {
  low: "Nhu cầu thấp", base: "Nhu cầu thông thường", high: "Nhu cầu cao",
};

export function weeklyDemand(node: DemandNode, scenario: DemandScenario): number | null {
  const value = node.weekly_expected_sessions?.[scenario];
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
}

export function demandAccessSummary(nodes: DemandNode[], scenario: DemandScenario, coverageMinutes: number) {
  let total = 0;
  let outside = 0;
  let missingDemand = 0;
  let unknownAccessDemand = 0;
  for (const node of nodes) {
    const value = weeklyDemand(node, scenario);
    if (value === null) { missingDemand += 1; continue; }
    total += value;
    const access = node.nearest_existing_access_minutes_proxy;
    if (!Number.isFinite(access) || access < 0) unknownAccessDemand += value;
    else if (access > coverageMinutes) outside += value;
  }
  return { total, outside, outsidePercent: total > 0 ? outside / total * 100 : null, missingDemand, unknownAccessDemand };
}

export function visibleDemandNodes(nodes: DemandNode[], scenario: DemandScenario, coverageMinutes: number, onlyUncovered: boolean) {
  return nodes.filter((node) => {
    const value = weeklyDemand(node, scenario);
    if (value === null || value <= 0) return false;
    const access = node.nearest_existing_access_minutes_proxy;
    return !onlyUncovered || (Number.isFinite(access) && access > coverageMinutes);
  });
}

function quantile(values: number[], fraction: number): number {
  if (!values.length) return 0;
  const position = (values.length - 1) * fraction;
  const lower = Math.floor(position);
  return values[lower] + (values[Math.ceil(position)] - values[lower]) * (position - lower);
}

// Keep the base-scenario thresholds fixed when switching scenarios. A uniform increase
// in demand then changes the colors rather than being canceled by a new normalization.
export function demandScale(nodes: DemandNode[]) {
  const baseline = nodes.map((node) => weeklyDemand(node, "base"))
    .filter((value): value is number => value !== null).sort((a, b) => a - b);
  const thresholds = [0.25, 0.5, 0.75].map((fraction) => quantile(baseline, fraction));
  const maximum = Math.max(1, ...nodes.flatMap((node) =>
    (["low", "base", "high"] as const).map((scenario) => weeklyDemand(node, scenario) ?? 0)));
  return { thresholds, maximum };
}

export function demandLevel(value: number | null, thresholds: number[]): number | null {
  if (value === null) return null;
  const index = thresholds.findIndex((threshold) => value <= threshold);
  return index < 0 ? 3 : index;
}

export function demandColor(value: number | null, thresholds: number[]): string {
  const level = demandLevel(value, thresholds);
  return level === null ? "#94a3b8" : DEMAND_COLORS[level];
}

export function demandFeature(node: DemandNode, scenario: DemandScenario, coverageMinutes: number,
  scale: ReturnType<typeof demandScale>) {
  const value = weeklyDemand(node, scenario);
  const level = demandLevel(value, scale.thresholds);
  return {
    type: "Feature" as const,
    geometry: { type: "Point" as const, coordinates: [node.location.lon, node.location.lat] },
    properties: {
      demand_node_id: node.demand_node_id,
      weekly_sessions: value,
      heat_weight: (value ?? 0) / scale.maximum,
      demand_color: demandColor(value, scale.thresholds),
      demand_label: level === null ? "Chưa có dữ liệu" : DEMAND_LABELS[level],
      covered: node.nearest_existing_access_minutes_proxy <= coverageMinutes,
      access_minutes: node.nearest_existing_access_minutes_proxy,
    },
  };
}
