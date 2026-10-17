import type {
  GapCandidate, GapCellItem, GapCellResult, GapExcludedReason, GapRoadItem, GapStationItem,
} from "./gapTypes";

export type GapLayer = "score" | "gap" | "demand" | "supply" | "flow" | "poi" | "rent";

/** The three modes the map can show. */
export const GAP_LAYERS: { id: GapLayer; label: string; hint: string }[] = [
  { id: "flow", label: "Lưu lượng tuyến đường", hint: "xe/giờ cao điểm (mô phỏng)" },
  { id: "rent", label: "Giá nhà", hint: "giá thuê, nghìn đồng/m²/tháng (mô phỏng)" },
  { id: "score", label: "Điểm dự đoán", hint: "Gap sau bước giá thuê" },
];
export const CANDIDATE_LIMIT = 5;

export const GAP_SCENARIOS: { id: string; label: string; w_flow: number; lambda_m: number }[] = [
  { id: "default", label: "Mặc định (cân bằng)", w_flow: 0.5, lambda_m: 1000 },
  { id: "corridor", label: "Sạc nhanh dọc đường", w_flow: 0.7, lambda_m: 1500 },
  { id: "destination", label: "Điểm đến (TTTM, văn phòng)", w_flow: 0.3, lambda_m: 800 },
  { id: "residential", label: "Khu chung cư", w_flow: 0.3, lambda_m: 700 },
];

export const RAMP = ["#fff7bc", "#fec44f", "#fe9929", "#d95f0e", "#993404"] as const;
export const EXCLUDED_COLOR = "#cbd5d1";

/** Congestion colours, free-flowing green to dark red, like the traffic layer of a map app. */
export const TRAFFIC_RAMP = ["#2eab4f", "#f4c20d", "#ee7b19", "#d7261e", "#7b0d0d"] as const;

export const ROAD_TYPE_LABELS: Record<string, string> = {
  motorway: "Đường cao tốc", trunk: "Đường trục chính", primary: "Đường chính",
  secondary: "Đường liên khu vực", tertiary: "Đường khu vực", unclassified: "Đường nội khu",
  residential: "Đường nội khu",
};

const ROAD_WIDTHS: Record<string, number> = {
  motorway: 5, trunk: 4.5, primary: 4, secondary: 3.2, tertiary: 2.6, unclassified: 2, residential: 1.8,
};

export function roadWidth(roadType: string): number {
  return ROAD_WIDTHS[roadType] ?? 2;
}

export function roadFlowRange(roads: GapRoadItem[]): [number, number] {
  if (!roads.length) return [0, 0];
  let low = Infinity;
  let high = -Infinity;
  for (const road of roads) {
    low = Math.min(low, road.flow_vph);
    high = Math.max(high, road.flow_vph);
  }
  return [low, high];
}

/** Share of the flow range (0 = freest road, 1 = busiest). */
export function flowShare(value: number, low: number, high: number): number {
  return high > low ? Math.min(Math.max((value - low) / (high - low), 0), 1) : 0;
}

export function congestionLabel(share: number): string {
  if (share < 0.2) return "Thông thoáng";
  if (share < 0.45) return "Khá đông";
  if (share < 0.7) return "Đông";
  return "Rất đông, dễ kẹt";
}

export const DIVISION_LABELS: Record<"route" | "grid", { name: string; unit: string; units: string }> = {
  route: { name: "Theo tuyến đường (khối đường)", unit: "khối", units: "khối" },
  grid: { name: "Lưới vuông 300 m (theo tọa độ)", unit: "ô", units: "ô" },
};

export const SITE_TYPE_LABELS: Record<string, string> = {
  mall: "Trung tâm thương mại",
  supermarket: "Siêu thị",
  parking: "Bãi xe",
  hotel: "Khách sạn",
  transit: "Bến xe, trạm dừng",
  fuel_station: "Trạm xăng",
  hospital: "Bệnh viện",
  campus: "Trường đại học",
  tourism: "Khu du lịch",
  other: "Vị trí đặt tay (chưa rõ loại)",
};

export function siteTypeLabel(siteType: string): string {
  return SITE_TYPE_LABELS[siteType] ?? siteType;
}

export const EXCLUDED_LABELS: Record<GapExcludedReason, string> = {
  rent_above_limit: "Giá thuê vượt ngưỡng",
  own_station_nearby: "Gần trạm của mình",
  demand_below_floor: "Nhu cầu quá thấp",
};

export interface CellView {
  item: GapCellItem;
  result: GapCellResult | undefined;
}

export function layerValue(layer: GapLayer, view: CellView): number | null {
  const { item, result } = view;
  switch (layer) {
    case "flow": return item.flow_vph;
    case "poi": return item.poi_weighted;
    case "rent": return item.rent_kvnd_m2_month;
    case "score": return result ? result.score : null;
    case "gap": return result ? result.gap : null;
    case "demand": return result ? result.demand : null;
    case "supply": return result ? result.supply : null;
  }
}

/** Layers where an excluded cell is greyed out instead of coloured by its value. */
export function greysOutExcluded(layer: GapLayer): boolean {
  return layer === "score" || layer === "gap";
}

export function layerRange(layer: GapLayer, views: CellView[]): [number, number] {
  let low = Infinity;
  let high = -Infinity;
  for (const view of views) {
    if (greysOutExcluded(layer) && view.result?.excluded_reason) continue;
    const value = layerValue(layer, view);
    if (value === null || !Number.isFinite(value)) continue;
    low = Math.min(low, value);
    high = Math.max(high, value);
  }
  return Number.isFinite(low) ? [low, high] : [0, 0];
}

function hexToRgb(hex: string): [number, number, number] {
  return [1, 3, 5].map((index) => parseInt(hex.slice(index, index + 2), 16)) as [number, number, number];
}

/** Continuous heatmap colour: linear blend between neighbouring ramp stops. */
function blend(stops: readonly string[], ratio: number): string {
  const position = ratio * (stops.length - 1);
  const index = Math.min(Math.floor(position), stops.length - 2);
  const share = position - index;
  const from = hexToRgb(stops[index]);
  const to = hexToRgb(stops[index + 1]);
  const channel = (i: number) => Math.round(from[i] + (to[i] - from[i]) * share).toString(16).padStart(2, "0");
  return `#${channel(0)}${channel(1)}${channel(2)}`;
}

export function rampColor(value: number | null, low: number, high: number): string {
  if (value === null || !Number.isFinite(value)) return EXCLUDED_COLOR;
  if (high <= low) return RAMP[0];
  return blend(RAMP, flowShare(value, low, high));
}

/** Colour of a road for a given flow: green when free, dark red when congested. */
export function trafficColor(value: number, low: number, high: number): string {
  return blend(TRAFFIC_RAMP, flowShare(value, low, high));
}

export function formatNumber(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return value.toLocaleString("vi-VN", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

export function formatDistance(meters: number | null | undefined): string {
  if (meters === null || meters === undefined) return "—";
  return meters >= 1000 ? `${formatNumber(meters / 1000, 2)} km` : `${Math.round(meters)} m`;
}

export function formatPower(groups: GapStationItem["port_groups"]): string {
  return groups
    .map((group) => `${group.port_count} × ${group.charger_type} ${formatNumber(group.power_kw_per_port, 1)} kW`)
    .join(" + ");
}

export const RELATIONSHIP_COLORS = { OWNED: "#0f766e", OTHER_NETWORK: "#c2410c" } as const;

/** Stations come in exactly two kinds: our own, and competitors'. */
export function relationshipLabel(relationship: string): string {
  return relationship === "OWNED" ? "Trạm của mình" : "Trạm đối thủ";
}

export function stationColorOf(relationship: string): string {
  return relationship === "OWNED" ? RELATIONSHIP_COLORS.OWNED : RELATIONSHIP_COLORS.OTHER_NETWORK;
}

export function stabilityLabel(candidate: GapCandidate): string {
  if (candidate.stability === null) return "Chưa tính";
  const share = `${Math.round(candidate.stability * 100)}%`;
  return candidate.stability_label === "stable" ? `Ổn định (${share})` : `Nhạy với giả định (${share})`;
}

export function candidatesToCsv(candidates: GapCandidate[]): string {
  const header = [
    "Thứ tự", "Hạng điểm", "Mã", "Đường bao quanh", "Diện tích (ha)", "Phường", "Vĩ độ", "Kinh độ", "Điểm", "Gap", "Nhu cầu D", "Cung",
    "Lưu lượng (mô phỏng, xe/giờ)", "Lưu lượng quanh, trung bình (xe/giờ)", "Lưu lượng quanh, cao nhất (xe/giờ)",
    "POI có trọng số", "Giá thuê (mô phỏng, nghìn đ/m²/tháng)", "Giá thuê quanh, trung bình", "Giá thuê quanh, thấp nhất",
    "Giá thuê quanh, cao nhất",
    "Trạm của mình gần nhất", "Khoảng cách tới trạm của mình (m)", "Trạm đối thủ gần nhất",
    "Khoảng cách tới trạm đối thủ (m)", "Gần trạm của mình", "Độ ổn định", "Pháp lý",
  ];
  const lines = candidates.map((c) => [
    c.selection_order, c.rank ?? "", c.cell_id, (c.road_names ?? []).join(" | "),
    c.area_m2 ? (c.area_m2 / 10000).toFixed(2) : "", c.unit_name, c.lat.toFixed(6), c.lon.toFixed(6),
    c.score.toFixed(4), c.gap.toFixed(4), c.demand.toFixed(3), c.supply.toFixed(2), c.flow_vph,
    Math.round(c.nearby.flow_mean_vph), Math.round(c.nearby.flow_max_vph),
    c.poi_weighted, c.rent_kvnd_m2_month ?? "", Math.round(c.nearby.rent_mean_kvnd ?? 0) || "",
    c.nearby.rent_min_kvnd ?? "", c.nearby.rent_max_kvnd ?? "",
    c.nearest_own?.station_id ?? "", c.nearest_own ? Math.round(c.nearest_own.distance_m) : "",
    c.nearest_competitor?.station_id ?? "",
    c.nearest_competitor ? Math.round(c.nearest_competitor.distance_m) : "",
    c.own_overlap ? "Có" : "Không", c.stability === null ? "" : c.stability.toFixed(2),
    "Chưa xác minh",
  ]);
  const escape = (value: string | number) => `"${String(value).replaceAll('"', '""')}"`;
  return `${String.fromCharCode(0xfeff)}${[header, ...lines].map((row) => row.map(escape).join(",")).join("\r\n")}\r\n`;
}
