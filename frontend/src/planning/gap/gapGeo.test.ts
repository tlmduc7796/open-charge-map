import { expect, test } from "vitest";

import {
  cellBounds, cellFeatureCollection, cellOwnerId, cellPolygon, cellTooltipHtml, clusterIdsOf,
  escapeHtml, portRanges, stationFeatureCollection, stationPopupHtml,
} from "./gapGeo";
import type { GapCandidate, GapCellItem, GapStationItem } from "./gapTypes";

const cell: GapCellItem = {
  cell_id: "G1", unit_id: "u", unit_name: "Phường <U>", lat: 10.78, lon: 106.69,
  bounds: [10.779, 106.689, 10.781, 106.691], poi_count: 1, poi_weighted: 1, flow_vph: 100,
  rent_kvnd_m2_month: 200,
};

const station: GapStationItem = {
  station_id: "CMP-A-01", operator_id: "CMP-A", operator_name: "Đối thủ A", relationship: "OTHER_NETWORK",
  unit_id: "u", unit_name: "Phường U", lat: 10.78, lon: 106.69, site_type: "mall", opening_hours: "24/7",
  port_count: 4, dc_port_count: 4, ac_port_count: 0, total_power_kw: 240, max_port_power_kw: 60,
  port_groups: [{ charger_type: "DC", connector_type: "CCS2", port_count: 4, power_kw_per_port: 60 }],
  data_status: "synthetic",
};

function candidate(id: string, cluster: string[]): GapCandidate {
  return { cell_id: id, cluster_cell_ids: cluster } as GapCandidate;
}

test("cellPolygon is a closed ring in lon/lat order", () => {
  const ring = cellPolygon(cell)[0];
  expect(ring[0]).toEqual([106.689, 10.779]);
  expect(ring[2]).toEqual([106.691, 10.781]);
  expect(ring[ring.length - 1]).toEqual(ring[0]);
});

const road: GapCellItem = {
  ...cell, cell_id: "R1", road_name: "Lý Tự Trọng", road_names: ["Lý Tự Trọng", "Hàm Nghi"],
  road_length_m: 180, area_m2: 24_000, subdivided: false,
  polygon: [[[10.7795, 106.6895], [10.7795, 106.6915], [10.7805, 106.6915], [10.7805, 106.6895], [10.7795, 106.6895]]],
};

test("every cell, grid or along a road, becomes one closed Polygon feature", () => {
  const collection = cellFeatureCollection([cell, road], new Map(), "flow", [], null);
  expect(collection.features.map((f) => [f.properties.cell_id, f.geometry.type])).toEqual([
    ["G1", "Polygon"], ["R1", "Polygon"],
  ]);
  expect(collection.features[0].properties.in_cluster).toBe(false);
});

test("a street block is drawn from its own outline, a grid cell from its box", () => {
  expect(cellPolygon(road)[0].slice(0, 3)).toEqual([[106.6895, 10.7795], [106.6915, 10.7795], [106.6915, 10.7805]]);
  expect(cellPolygon(road)[0]).toHaveLength(5);
  expect(cellPolygon(cell)[0][0]).toEqual([106.689, 10.779]);
});

test("cellTooltipHtml names the roads that bound a block and its area", () => {
  const html = cellTooltipHtml(road, undefined);
  expect(html).toContain("R1 · Phường &lt;U&gt;");
  expect(html).toContain("Giới hạn bởi: Lý Tự Trọng, Hàm Nghi");
  expect(html).toContain("Diện tích 2,4 ha");
  expect(cellTooltipHtml({ ...road, subdivided: true }, undefined)).toContain("chia nhỏ từ vùng trống lớn");
  expect(cellTooltipHtml(cell, undefined)).not.toContain("Giới hạn bởi");
});

test("portRanges numbers ports across groups", () => {
  expect(portRanges([
    { charger_type: "DC", connector_type: "CCS2", port_count: 4, power_kw_per_port: 120 },
    { charger_type: "AC", connector_type: "TYPE2", port_count: 2, power_kw_per_port: 11 },
    { charger_type: "AC", connector_type: "TYPE2", port_count: 1, power_kw_per_port: 7.4 },
  ])).toEqual(["1–4", "5–6", "7"]);
});

test("cellBounds covers every cell as [lon, lat] corners", () => {
  expect(cellBounds([])).toBeNull();
  expect(cellBounds([cell, { ...cell, bounds: [10.8, 106.7, 10.81, 106.71] }])).toEqual([[106.689, 10.779], [106.71, 10.81]]);
});

test("cellOwnerId resolves a cluster member to its candidate, otherwise null", () => {
  const candidates = [candidate("A", ["B", "C"]), candidate("D", [])];
  expect(cellOwnerId("A", candidates)).toBe("A");
  expect(cellOwnerId("C", candidates)).toBe("A");
  expect(cellOwnerId("Z", candidates)).toBeNull();
});

test("clusterIdsOf returns the selected candidate and its cluster only", () => {
  const candidates = [candidate("A", ["B"]), candidate("D", ["E"])];
  expect([...clusterIdsOf(candidates, "D")].sort()).toEqual(["D", "E"]);
  expect(clusterIdsOf(candidates, null).size).toBe(0);
});

test("popup and tooltip HTML escape data before it reaches the map", () => {
  expect(escapeHtml(`<b>"x"&'y'</b>`)).toBe("&lt;b&gt;&quot;x&quot;&amp;&#39;y&#39;&lt;/b&gt;");
  expect(cellTooltipHtml(cell, undefined)).toContain("Phường &lt;U&gt;");
  const html = stationPopupHtml(station);
  expect(html).toContain("<strong>CMP-A-01</strong>");
  expect(html).toContain("Trạm đối thủ");
  expect(html).not.toContain("Mạng khác");
  // Where the station is
  expect(html).toContain("Trung tâm thương mại");
  expect(html).toContain("Phường U");
  expect(html).toContain("10.78000, 106.69000");
  expect(html).toContain("24/7");
  // The spec of its ports
  expect(html).toContain("4 cổng (4 DC, 0 AC)");
  expect(html).toContain("<td>1–4</td><td>DC · sạc nhanh</td><td>CCS2</td><td>4</td><td>60</td><td>240</td>");
  expect(html).toContain("Dữ liệu mô phỏng");
});

test("stations get one of two colours, own or competitor, and a port-based radius", () => {
  const [feature] = stationFeatureCollection([station]).features;
  expect(feature.geometry.coordinates).toEqual([106.69, 10.78]);
  expect(feature.properties.color).toBe("#c2410c");
  const [own] = stationFeatureCollection([{ ...station, relationship: "OWNED", operator_id: "OWN" }]).features;
  expect(own.properties.color).toBe("#0f766e");
  expect(feature.properties.radius).toBeCloseTo(4 + Math.sqrt(4) * 1.6);
});
