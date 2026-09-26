import type {
  DemoScenario,
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
    station_id: "ST_EVO_LAVIDA_Q7",
    name: "EV ONE – Lavida Quận 7",
    address: "Khu dân cư Lavida, TP.HCM",
    operator: "EV ONE",
    total_ports: 1,
    connectors: [{ type: "CCS2", current: "DC", max_power_kw: 160, count: 1, source: "real" }],
    access: "public",
    notes: [],
  },
};

export const status: StationStatus = {
  station_id: station.properties.station_id,
  timestamp: "2026-09-25T18:00:00+07:00",
  total_ports: 1,
  operational_ports: 1,
  occupied_ports: 0,
  available_ports: 1,
  offline_ports: 0,
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
  max_ac_power_kw: 6.6,
  max_dc_power_kw: 50,
  reserve_soc: 0.1,
  default_target_soc: 0.8,
};

export const scenario: DemoScenario = {
  scenario_id: "SCN_NORMAL",
  name: "Normal journey",
  vehicle_id: vehicle.vehicle_id,
  initial_soc: 0.55,
  target_soc: 0.8,
  origin: { lat: 10.7075, lon: 106.705, label: "Nguyen Huu Tho" },
  destination: { lat: 10.806, lon: 106.687, label: "Phu Nhuan" },
  departure_at: "2026-09-25T18:00:00+07:00",
  event_ids: [],
};

export const route: RouteResult = {
  route_id: "ROUTE_VIA_LAVIDA",
  provider: "osrm",
  resolution_source: "cache",
  origin: scenario.origin,
  destination: scenario.destination,
  geometry: {
    type: "LineString",
    coordinates: [[106.705, 10.7075], [106.701, 10.727], [106.687, 10.806]],
  },
  distance_m: 15654,
  duration_s: 1157,
  flags: ["ROUTE_CACHE"],
};

export const recommendationItem: RecommendationItem = {
  station_id: station.properties.station_id,
  station_name: station.properties.name,
  route_id: route.route_id,
  route_provider: "osrm",
  route,
  matched_connectors: ["CCS2"],
  effective_power_kw: 50,
  route_distance_to_station_m: 2200,
  route_duration_to_station_s: 240,
  detour_min: 3.3,
  arrival_soc: 0.52,
  predicted_occupied_ports: 0,
  predicted_occupancy_ratio: 0,
  prediction_source: "persistence",
  estimated_wait_min: 0,
  estimated_charge_min: 14,
  energy_to_add_kwh: 10.4,
  wait_score: 1,
  detour_score: 0.89,
  charging_time_score: 0.84,
  soc_risk_score: 1,
  final_score: 0.94,
  rank: 1,
  flags: ["MATCHED_CCS2", "PERSISTENCE_FALLBACK"],
};

export const recommendation: JourneyRecommendation = {
  scenario_id: scenario.scenario_id,
  generated_at: "2026-09-25T18:00:00+07:00",
  vehicle_id: vehicle.vehicle_id,
  direct_route: { ...route, route_id: "ROUTE_BASE_DIRECT" },
  recommendations: [recommendationItem],
  excluded_candidates: [],
  active_event_ids: [],
};

export const modelStatus: ModelStatus = {
  prediction_source: "persistence",
  model_artifact_available: false,
  preprocessor_artifact_available: false,
  metadata_available: false,
  model_adapter_loaded: false,
  release_ready: false,
  flags: ["PHASE_04_ARTIFACTS_UNAVAILABLE"],
};
