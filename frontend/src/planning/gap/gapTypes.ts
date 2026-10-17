export type GapNormalization = "minmax" | "percentile";
export type GapRentMode = "none" | "filter" | "divide";
export type GapOwnMode = "flag" | "exclude";
export type GapSupplyBasis = "ports" | "power";
/** route = road segments (default), grid = square cells */
export type GapDivision = "route" | "grid";

export interface GapParams {
  snapshot_id?: string | null;
  division: GapDivision;
  w_flow: number;
  lambda_m: number;
  normalization: GapNormalization;
  rent_mode: GapRentMode;
  rent_max_kvnd: number;
  epsilon: number;
  own_min_distance_m: number;
  own_mode: GapOwnMode;
  top_n: number;
  min_separation_m: number;
  supply_basis: GapSupplyBasis;
  reference_power_kw: number;
  min_demand: number;
  with_sensitivity: boolean;
}

export interface GapCellItem {
  cell_id: string;
  unit_id: string;
  unit_name: string;
  lat: number;
  lon: number;
  /** Bounding box: lat_min, lon_min, lat_max, lon_max */
  bounds: [number, number, number, number];
  /** Street block outline as [lat, lon] rings, outer ring first (route division only). */
  polygon?: [number, number][][] | null;
  area_m2?: number | null;
  /** True for a piece cut from an oversized open area, not bounded by roads on every side. */
  subdivided?: boolean;
  /** Route division: longest road in the cell, and up to three roads longest first. */
  road_name?: string | null;
  road_names?: string[] | null;
  road_type?: string | null;
  width_m?: number | null;
  lanes?: number | null;
  /** Road length inside the cell. */
  road_length_m?: number | null;
  poi_count: number;
  poi_weighted: number;
  flow_vph: number;
  rent_kvnd_m2_month: number | null;
}

/** A street with its simulated peak-hour flow, drawn as one coloured line on the traffic map. */
export interface GapRoadItem {
  road_id: string;
  name: string;
  road_type: string;
  lanes: number | null;
  length_m: number;
  flow_vph: number;
  /** [lat, lon] points */
  coordinates: [number, number][];
}

export interface GapPortGroup {
  charger_type: "AC" | "DC";
  connector_type: string;
  port_count: number;
  power_kw_per_port: number;
}

export interface GapStationItem {
  station_id: string;
  operator_id: string;
  operator_name: string;
  relationship: "OWNED" | "OTHER_NETWORK";
  unit_id: string;
  unit_name: string;
  lat: number;
  lon: number;
  site_type: string;
  opening_hours: string;
  port_count: number;
  dc_port_count: number;
  ac_port_count: number;
  total_power_kw: number;
  max_port_power_kw: number;
  port_groups: GapPortGroup[];
  data_status: "synthetic";
}

export interface GapOperatorSummary {
  operator_name: string;
  relationship: string;
  stations: number;
  ports: number;
  dc_ports: number;
  ac_ports: number;
  total_power_kw: number;
}

export interface GapSnapshotResponse {
  contract_version: "gap-0.1";
  snapshot_id: string;
  division: GapDivision;
  prepared_on: string;
  data_labels: Record<string, string>;
  defaults: GapParams;
  cells: GapCellItem[];
  roads: GapRoadItem[];
  stations: GapStationItem[];
  station_summary: {
    stations: number;
    ports: number;
    total_power_kw: number;
    by_operator: Record<string, GapOperatorSummary>;
    ports_by_power_class: Record<string, number>;
    stations_by_ward: Record<string, number>;
  };
}

export type GapExcludedReason = "rent_above_limit" | "own_station_nearby" | "demand_below_floor";

export interface GapCellResult {
  cell_id: string;
  flow_norm: number;
  poi_norm: number;
  demand: number;
  supply: number;
  supply_own: number;
  supply_competitor: number;
  gap: number;
  rent_norm: number | null;
  rent_missing: boolean;
  score: number;
  d_own_m: number | null;
  d_competitor_m: number | null;
  own_overlap: boolean;
  excluded_reason: GapExcludedReason | null;
  rank: number | null;
}

export interface GapNearestStation {
  station_id: string;
  operator_name: string;
  port_count: number;
  total_power_kw: number;
  max_port_power_kw: number;
  distance_m: number;
}

export interface GapSupplyContributor {
  station_id: string;
  operator_name: string;
  relationship: string;
  port_count: number;
  total_power_kw: number;
  distance_m: number;
  contribution: number;
}

/** Traffic and rent of the units within `radius_m` of a candidate (simulated values). */
export interface GapNearby {
  radius_m: number;
  cell_count: number;
  flow_mean_vph: number;
  flow_max_vph: number;
  flow_max_roads: string[] | null;
  /** Share of the nine wards' units (0-100) whose flow is at most this candidate's. */
  flow_percentile: number;
  rent_mean_kvnd: number | null;
  rent_min_kvnd: number | null;
  rent_max_kvnd: number | null;
  rent_percentile: number | null;
}

export interface GapCandidate extends GapCellResult {
  selection_order: number;
  unit_id: string;
  unit_name: string;
  lat: number;
  lon: number;
  flow_vph: number;
  road_name?: string | null;
  road_names?: string[] | null;
  road_type?: string | null;
  width_m?: number | null;
  lanes?: number | null;
  road_length_m?: number | null;
  poi_count: number;
  poi_weighted: number;
  rent_kvnd_m2_month: number | null;
  area_m2?: number | null;
  subdivided?: boolean;
  cluster_cell_ids: string[];
  cluster_size: number;
  nearby: GapNearby;
  nearest_own: GapNearestStation | null;
  nearest_competitor: GapNearestStation | null;
  top_supply_stations: GapSupplyContributor[];
  stability: number | null;
  stability_label: "stable" | "sensitive" | null;
  legal_status: "unknown";
  pending_legal_checks: string[];
}

export interface GapRunResponse {
  contract_version: "gap-0.1";
  snapshot_id: string;
  params: GapParams;
  cells: GapCellResult[];
  candidates: GapCandidate[];
  summary: {
    cell_count: number;
    eligible_cell_count: number;
    excluded_by_reason: Record<string, number>;
    own_overlap_cell_count: number;
    rent_missing_cell_count: number;
    sensitivity_variant_count: number;
    max_gap: number;
    max_score: number;
  };
  warnings: string[];
}
