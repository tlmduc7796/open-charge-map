import { expect, test } from "vitest";
import { demandAccessSummary, demandColor, demandFeature, demandScale, visibleDemandNodes, weeklyDemand, type DemandNode } from "./demandHeatmap";

function node(base: number): DemandNode {
  return {
    demand_node_id: `node-${base}`, unit_id: "ward", location: { lat: 10.7, lon: 106.7 },
    nearest_existing_access_minutes_proxy: 12, is_synthetic: true,
    weekly_expected_sessions: { low: base * 0.6, base, high: base * 1.6 },
  };
}

test("scenario changes demand colors and weights against a fixed baseline scale", () => {
  const nodes = [100, 200, 400, 800].map(node);
  const scale = demandScale(nodes);
  expect(scale.thresholds).toEqual([175, 300, 500]);
  const low = demandFeature(nodes[2], "low", 15, scale);
  const high = demandFeature(nodes[2], "high", 15, scale);
  expect(low.properties.weekly_sessions).toBe(240);
  expect(high.properties.weekly_sessions).toBe(640);
  expect(high.properties.heat_weight).toBeGreaterThan(low.properties.heat_weight);
  expect(high.properties.demand_color).not.toBe(low.properties.demand_color);
});

test("access coverage does not determine the demand heat color", () => {
  const nodes = [100, 200, 400, 800].map(node);
  const scale = demandScale(nodes);
  const near = demandFeature(nodes[2], "base", 15, scale);
  const far = demandFeature(nodes[2], "base", 5, scale);
  expect(near.properties.covered).toBe(true);
  expect(far.properties.covered).toBe(false);
  expect(near.properties.demand_color).toBe(far.properties.demand_color);
  expect(near.properties.weekly_sessions).toBe(far.properties.weekly_sessions);
});

test("missing demand stays unknown while zero demand is a valid zero weight", () => {
  const zero = node(0);
  const missing = { ...zero, weekly_expected_sessions: undefined } as unknown as DemandNode;
  const scale = demandScale([zero]);
  expect(weeklyDemand(missing, "base")).toBeNull();
  expect(demandFeature(missing, "base", 15, scale).properties.demand_label).toBe("Chưa có dữ liệu");
  expect(demandFeature(zero, "base", 15, scale).properties.heat_weight).toBe(0);
  expect(demandColor(null, scale.thresholds)).not.toBe(demandColor(0, scale.thresholds));
});

test("access summary weights demand rather than counting nodes and includes the time threshold", () => {
  const nodes = [
    { ...node(100), nearest_existing_access_minutes_proxy: 5 },
    { ...node(300), nearest_existing_access_minutes_proxy: 10 },
    { ...node(600), nearest_existing_access_minutes_proxy: 20 },
  ];
  expect(demandAccessSummary(nodes, "base", 10)).toMatchObject({ total: 1000, outside: 600, outsidePercent: 60 });
  expect(visibleDemandNodes(nodes, "base", 10, true)).toEqual([nodes[2]]);
  expect(visibleDemandNodes(nodes, "base", 20, true)).toEqual([]);
  expect(visibleDemandNodes(nodes, "base", 1, false)).toEqual(nodes);
});

test("missing demand or access is not presented as zero demand or confirmed outside coverage", () => {
  const unknownDemand = { ...node(100), weekly_expected_sessions: undefined } as unknown as DemandNode;
  const unknownAccess = { ...node(100), nearest_existing_access_minutes_proxy: NaN };
  expect(demandAccessSummary([unknownDemand, unknownAccess], "base", 10)).toMatchObject({
    total: 100, outside: 0, missingDemand: 1, unknownAccessDemand: 100,
  });
  expect(visibleDemandNodes([unknownDemand, unknownAccess, node(0)], "base", 10, true)).toEqual([]);
  expect(demandAccessSummary([node(0)], "base", 10).outsidePercent).toBeNull();
});
