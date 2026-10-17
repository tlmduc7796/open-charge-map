import { expect, test } from "vitest";

import {
  EXCLUDED_COLOR, RAMP, candidatesToCsv, formatDistance, layerRange, layerValue, rampColor,
  type CellView,
} from "./gapFormat";
import type { GapCandidate, GapCellItem, GapCellResult } from "./gapTypes";

function item(id: string, flow: number, rent: number | null): GapCellItem {
  return {
    cell_id: id, unit_id: "u", unit_name: "Phường U", lat: 10.78, lon: 106.69,
    bounds: [10.779, 106.689, 10.781, 106.691], poi_count: 3, poi_weighted: 5, flow_vph: flow,
    rent_kvnd_m2_month: rent,
  };
}

function result(id: string, gap: number, excluded: GapCellResult["excluded_reason"] = null): GapCellResult {
  return {
    cell_id: id, flow_norm: 0.5, poi_norm: 0.5, demand: 0.5, supply: 1, supply_own: 0.5,
    supply_competitor: 0.5, gap, rent_norm: 0.5, rent_missing: false, score: gap * 2,
    d_own_m: 900, d_competitor_m: 400, own_overlap: false, excluded_reason: excluded, rank: excluded ? null : 1,
  };
}

test("rampColor spreads values over the ramp and greys out missing ones", () => {
  expect(rampColor(0, 0, 10)).toBe(RAMP[0]);
  expect(rampColor(10, 0, 10)).toBe(RAMP[RAMP.length - 1]);
  expect(rampColor(null, 0, 10)).toBe(EXCLUDED_COLOR);
  expect(rampColor(5, 3, 3)).toBe(RAMP[0]);
});

test("rampColor blends between stops, so values between two stops get distinct colours", () => {
  const colours = [0.1, 0.2, 0.3, 0.4, 0.6].map((value) => rampColor(value, 0, 1));
  expect(new Set(colours).size).toBe(colours.length);
  expect(rampColor(0.125, 0, 1)).toBe("#ffde86"); // halfway between the first two stops
});

test("layerRange ignores excluded cells for the gap and score layers only", () => {
  const views: CellView[] = [
    { item: item("A", 100, 200), result: result("A", 0.1) },
    { item: item("B", 900, 300), result: result("B", 0.9, "rent_above_limit") },
  ];
  expect(layerRange("gap", views)).toEqual([0.1, 0.1]);
  expect(layerRange("flow", views)).toEqual([100, 900]);
  expect(layerValue("rent", views[1])).toBe(300);
});

test("layerRange falls back to zero when no cell has a value", () => {
  expect(layerRange("gap", [])).toEqual([0, 0]);
  expect(layerRange("rent", [{ item: item("A", 1, null), result: undefined }])).toEqual([0, 0]);
});

test("formatDistance switches to kilometres", () => {
  expect(formatDistance(420)).toBe("420 m");
  expect(formatDistance(2300)).toBe("2,3 km");
  expect(formatDistance(null)).toBe("—");
});

test("candidatesToCsv writes a BOM, quoted cells and keeps legal status unverified", () => {
  const base = result("G1", 0.02);
  const candidate: GapCandidate = {
    ...base, selection_order: 1, unit_id: "u", unit_name: 'Phường "U"', lat: 10.78, lon: 106.69,
    flow_vph: 1200, poi_count: 4, poi_weighted: 6, rent_kvnd_m2_month: 250, cluster_cell_ids: [],
    cluster_size: 1,
    nearby: { radius_m: 800, cell_count: 3, flow_mean_vph: 500, flow_max_vph: 900, flow_max_roads: null, flow_percentile: 50, rent_mean_kvnd: 300, rent_min_kvnd: 250, rent_max_kvnd: 350, rent_percentile: 40 },
    nearest_own: null, nearest_competitor: null, top_supply_stations: [],
    stability: 0.78, stability_label: "stable", legal_status: "unknown", pending_legal_checks: ["x"],
  };
  const csv = candidatesToCsv([candidate]);
  expect(csv.startsWith("﻿")).toBe(true);
  expect(csv).toContain('"Phường ""U"""');
  expect(csv).toContain('"Chưa xác minh"');
  expect(csv.trim().split("\r\n")).toHaveLength(2);
});
