import {
  EXCLUDED_COLOR, EXCLUDED_LABELS, ROAD_TYPE_LABELS, congestionLabel, flowShare, formatDistance,
  formatNumber, greysOutExcluded, layerRange, layerValue, rampColor, relationshipLabel, roadFlowRange,
  roadWidth, siteTypeLabel, stationColorOf, trafficColor, type CellView, type GapLayer,
} from "./gapFormat";
import type {
  GapCandidate, GapCellItem, GapCellResult, GapRoadItem, GapStationItem,
} from "./gapTypes";

export interface GapMapProps {
  cells: GapCellItem[];
  roads: GapRoadItem[];
  results: Map<string, GapCellResult>;
  layer: GapLayer;
  stations: GapStationItem[];
  showStations: boolean;
  candidates: GapCandidate[];
  selectedCandidateId: string | null;
  onSelectCandidate: (cellId: string | null) => void;
}

export const HCMC_CENTER: [number, number] = [106.69, 10.78];

export interface CellStyle {
  fillColor: string;
  fillOpacity: number;
  greyed: boolean;
}

/** On the traffic layer the roads carry the colour, so the blocks only stay as a faint backdrop. */
export const TRAFFIC_BACKDROP: CellStyle = { fillColor: "#cbd5e1", fillOpacity: 0.1, greyed: false };

/** Heatmap colour of every cell for the chosen layer; excluded cells grey out on gap/score. */
export function cellStyles(cells: GapCellItem[], results: Map<string, GapCellResult>, layer: GapLayer): Map<string, CellStyle> {
  if (layer === "flow") return new Map(cells.map((cell) => [cell.cell_id, TRAFFIC_BACKDROP]));
  const views: CellView[] = cells.map((item) => ({ item, result: results.get(item.cell_id) }));
  const [low, high] = layerRange(layer, views);
  const styles = new Map<string, CellStyle>();
  for (const view of views) {
    const greyed = Boolean(view.result?.excluded_reason) && greysOutExcluded(layer);
    styles.set(view.item.cell_id, {
      greyed,
      fillColor: greyed ? EXCLUDED_COLOR : rampColor(layerValue(layer, view), low, high),
      fillOpacity: greyed ? 0.35 : 0.68,
    });
  }
  return styles;
}

/** Cell that owns a clicked cell: the candidate itself or the candidate whose cluster contains it. */
export function cellOwnerId(cellId: string, candidates: GapCandidate[]): string | null {
  return candidates.find((candidate) => candidate.cell_id === cellId || candidate.cluster_cell_ids.includes(cellId))?.cell_id ?? null;
}

export function clusterIdsOf(candidates: GapCandidate[], selectedCandidateId: string | null): Set<string> {
  const selected = candidates.find((candidate) => candidate.cell_id === selectedCandidateId);
  return new Set(selected ? [selected.cell_id, ...selected.cluster_cell_ids] : []);
}

export function cellTooltipLines(item: GapCellItem, result: GapCellResult | undefined): string[] {
  const lines = [`${item.cell_id} · ${item.unit_name}`];
  if (item.road_names?.length) lines.push(`Giới hạn bởi: ${item.road_names.join(", ")}`);
  if (item.area_m2) {
    lines.push(`Diện tích ${formatNumber(item.area_m2 / 10000, 1)} ha${item.subdivided ? " · chia nhỏ từ vùng trống lớn" : ""}`);
  }
  if (!result) return lines;
  lines.push(`Gap ${formatNumber(result.gap, 4)} · D ${formatNumber(result.demand, 2)} · Cung ${formatNumber(result.supply, 1)}`);
  if (result.excluded_reason) lines.push(EXCLUDED_LABELS[result.excluded_reason]);
  else if (result.rank !== null) lines.push(`Hạng điểm ${result.rank}`);
  if (result.own_overlap) lines.push(`Trong ${formatDistance(result.d_own_m)} từ trạm của mình`);
  return lines;
}

export function roadTooltipLines(road: GapRoadItem, roads: GapRoadItem[]): string[] {
  const [low, high] = roadFlowRange(roads);
  const share = flowShare(road.flow_vph, low, high);
  return [
    road.name,
    `${ROAD_TYPE_LABELS[road.road_type] ?? road.road_type}${road.lanes ? ` · ${road.lanes} làn` : ""}`,
    `${formatNumber(road.flow_vph, 0)} xe/giờ cao điểm (mô phỏng)`,
    congestionLabel(share),
  ];
}

export function roadTooltipHtml(road: GapRoadItem, roads: GapRoadItem[]): string {
  const [title, ...rest] = roadTooltipLines(road, roads);
  return `<strong>${escapeHtml(title)}</strong>${rest.map((line) => `<br/>${escapeHtml(line)}`).join("")}`;
}

/** Roads as coloured lines; the busiest are listed last so they are drawn on top. */
export function sortedRoads(roads: GapRoadItem[]): GapRoadItem[] {
  return [...roads].sort((a, b) => a.flow_vph - b.flow_vph);
}

export function roadFeatureCollection(roads: GapRoadItem[]) {
  const [low, high] = roadFlowRange(roads);
  return {
    type: "FeatureCollection" as const,
    features: sortedRoads(roads).map((road) => ({
      type: "Feature" as const,
      geometry: { type: "LineString" as const, coordinates: road.coordinates.map(([lat, lon]) => [lon, lat]) },
      properties: {
        road_id: road.road_id,
        color: trafficColor(road.flow_vph, low, high),
        width: roadWidth(road.road_type),
      },
    })),
  };
}

export function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (char) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char] as string
  ));
}

export function cellTooltipHtml(item: GapCellItem, result: GapCellResult | undefined): string {
  const [title, ...rest] = cellTooltipLines(item, result);
  return `<strong>${escapeHtml(title)}</strong>${rest.map((line) => `<br/>${escapeHtml(line)}`).join("")}`;
}

/** Port numbers per group, e.g. a 4 + 2 station gives "1–4" and "5–6". */
export function portRanges(groups: GapStationItem["port_groups"]): string[] {
  let next = 1;
  return groups.map((group) => {
    const first = next;
    next += group.port_count;
    return group.port_count === 1 ? String(first) : `${first}–${next - 1}`;
  });
}

const CHARGER_LABELS: Record<string, string> = { DC: "DC · sạc nhanh", AC: "AC · sạc thường" };

/** Everything known about one station: where it is and the spec of every port. */
export function stationPopupHtml(station: GapStationItem): string {
  const place: [string, string][] = [
    ["Loại điểm", siteTypeLabel(station.site_type)],
    ["Phường", station.unit_name],
    ["Tọa độ", `${station.lat.toFixed(5)}, ${station.lon.toFixed(5)}`],
    ["Giờ mở cửa", station.opening_hours],
    ["Đơn vị vận hành", station.operator_name],
  ];
  const ranges = portRanges(station.port_groups);
  const ports = station.port_groups.map((group, index) => (
    `<tr><td>${ranges[index]}</td><td>${escapeHtml(CHARGER_LABELS[group.charger_type] ?? group.charger_type)}</td>`
    + `<td>${escapeHtml(group.connector_type)}</td><td>${group.port_count}</td>`
    + `<td>${formatNumber(group.power_kw_per_port, 1)}</td>`
    + `<td>${formatNumber(group.port_count * group.power_kw_per_port, 1)}</td></tr>`
  )).join("");
  return `<div class="gap-popup"><strong>${escapeHtml(station.station_id)}</strong>`
    + `<span class="gap-chip ${station.relationship === "OWNED" ? "own" : "other"}">${relationshipLabel(station.relationship)}</span>`
    + "<h5>Địa điểm</h5>"
    + `<dl>${place.map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`).join("")}</dl>`
    + `<h5>Thông số cổng · ${station.port_count} cổng (${station.dc_port_count} DC, ${station.ac_port_count} AC)</h5>`
    + "<table><thead><tr><th>Cổng</th><th>Loại sạc</th><th>Đầu cắm</th><th>Số cổng</th><th>kW/cổng</th><th>Tổng kW</th></tr></thead>"
    + `<tbody>${ports}</tbody>`
    + `<tfoot><tr><td colspan="3">Tổng</td><td>${station.port_count}</td><td>tối đa ${formatNumber(station.max_port_power_kw, 1)}</td>`
    + `<td>${formatNumber(station.total_power_kw, 1)}</td></tr></tfoot></table>`
    + "<small>Dữ liệu mô phỏng, không phải trạm thật.</small></div>";
}

export function stationRadius(station: GapStationItem): number {
  return 4 + Math.sqrt(station.port_count) * 1.6;
}

export function stationColor(station: GapStationItem): string {
  return stationColorOf(station.relationship);
}

type Position = [number, number];

/** [lon, lat] rings of a cell: the street-block outline, or the box of a grid cell. */
export function cellPolygon(cell: GapCellItem): Position[][] {
  if (cell.polygon?.length) return cell.polygon.map((ring) => ring.map(([lat, lon]) => [lon, lat] as Position));
  const [latMin, lonMin, latMax, lonMax] = cell.bounds;
  return [[[lonMin, latMin], [lonMax, latMin], [lonMax, latMax], [lonMin, latMax], [lonMin, latMin]]];
}

export function cellFeatureCollection(
  cells: GapCellItem[], results: Map<string, GapCellResult>, layer: GapLayer,
  candidates: GapCandidate[], selectedCandidateId: string | null,
) {
  const styles = cellStyles(cells, results, layer);
  const cluster = clusterIdsOf(candidates, selectedCandidateId);
  return {
    type: "FeatureCollection" as const,
    features: cells.map((cell) => {
      const style = styles.get(cell.cell_id) as CellStyle;
      const result = results.get(cell.cell_id);
      return {
        type: "Feature" as const,
        geometry: { type: "Polygon" as const, coordinates: cellPolygon(cell) },
        properties: {
          cell_id: cell.cell_id,
          fill_color: style.fillColor,
          fill_opacity: style.fillOpacity,
          own_overlap: Boolean(result?.own_overlap) && !result?.excluded_reason,
          in_cluster: cluster.has(cell.cell_id),
        },
      };
    }),
  };
}

export function stationFeatureCollection(stations: GapStationItem[]) {
  return {
    type: "FeatureCollection" as const,
    features: stations.map((station) => ({
      type: "Feature" as const,
      geometry: { type: "Point" as const, coordinates: [station.lon, station.lat] },
      properties: {
        station_id: station.station_id,
        color: stationColor(station),
        radius: stationRadius(station),
      },
    })),
  };
}

export function cellBounds(cells: GapCellItem[]): [Position, Position] | null {
  if (!cells.length) return null;
  let minLat = Infinity;
  let minLon = Infinity;
  let maxLat = -Infinity;
  let maxLon = -Infinity;
  for (const cell of cells) {
    minLat = Math.min(minLat, cell.bounds[0]);
    minLon = Math.min(minLon, cell.bounds[1]);
    maxLat = Math.max(maxLat, cell.bounds[2]);
    maxLon = Math.max(maxLon, cell.bounds[3]);
  }
  return [[minLon, minLat], [maxLon, maxLat]];
}
