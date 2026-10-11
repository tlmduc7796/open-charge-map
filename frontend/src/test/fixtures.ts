import type {
  JourneyRecommendation,
  ModelStatus,
  RecommendationItem,
  RouteResult,
  Station,
  StationStatus,
  Vehicle,
} from "../types";

export const station: Station = {
  type: "Feature",
  geometry: { type: "Point", coordinates: [106.7016553, 10.7271154] },
  properties: {
    station_id: "ST_VF_LA_VELA",
    name: "VinFast – La Vela Saigon Hotel",
    address: "280 Nam Kỳ Khởi Nghĩa, TP.HCM",
    operator: "VinFast",
    total_ports: 2,
    connectors: [{ type: "CCS2", current: "DC", max_power_kw: 150, count: 2, source: "real" }],
    access: "public",
    notes: [],
  },
};

export const status: StationStatus = {
  station_id: station.properties.station_id,
  timestamp: "2026-09-25T18:00:00+07:00",
  total_ports: 2,
  operational_ports: 2,
  occupied_ports: 0,
  available_ports: 2,
  offline_ports: 0,
  unknown_ports: 0,
  occupancy_ratio: 0,
  queue_length: 0,
  avg_session_duration_min: 30,
  data_source: "synthetic",
};

export const vehicle: Vehicle = {
  vehicle_id: "EV_VF5_PLUS",
  make: "VinFast",
  model: "VF 5",
  variant: "Plus",
  battery_capacity_kwh: 37.23,
  usable_battery_kwh: 37.23,
  consumption_wh_km: 124.1,
  max_ac_power_kw: 6.6,
  max_dc_power_kw: 50,
  reserve_soc: 0.1,
  default_target_soc: 0.8,
};

export const route: RouteResult = {
  route_id: "ROUTE_TEST",
  provider: "osrm",
  geometry: {
    type: "LineString",
    coordinates: [[106.705, 10.7075], [106.701, 10.727], [106.687, 10.806]],
  },
  distance_m: 15654,
  duration_s: 1157,
};

export const recommendationItem: RecommendationItem = {
  rank: 1,
  station_id: station.properties.station_id,
  station_name: station.properties.name,
  connectors: ["CCS2"],
  route,
  distance_km: 2.2,
  travel_min: 4,
  wait_min: 0,
  charge_min: 14,
  to_dest_min: 16,
  total_min: 34,
  arrive_battery_pct: 52,
  prediction_source: "default",
  flags: ["ML_DEFAULT_VALUE"],
};

export const recommendation: JourneyRecommendation = {
  search_id: "SRCH_TEST",
  case: "needCharge",
  generated_at: "2026-09-25T18:00:00+07:00",
  direct_route: { ...route, route_id: "ROUTE_DIRECT" },
  direct_min: 19,
  recommendations: [recommendationItem],
  excluded_candidates: [],
  missing_km: null,
  nearest_station_name: null,
};

export const modelStatus: ModelStatus = {
  prediction_source: "default",
  model_artifact_available: false,
  preprocessor_artifact_available: false,
  metadata_available: false,
  model_adapter_loaded: false,
  release_ready: false,
  flags: ["PHASE_04_ARTIFACTS_UNAVAILABLE"],
};
