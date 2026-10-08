export type Coordinates = [number, number];

export interface StationConnector {
  type: string;
  current: "AC" | "DC";
  max_power_kw: number;
  count: number;
  source: string;
}

export interface Station {
  type: "Feature";
  geometry: { type: "Point"; coordinates: Coordinates };
  properties: {
    station_id: string;
    name: string;
    address: string;
    operator: string | null;
    total_ports: number;
    connectors: StationConnector[];
    access: "public" | "customers" | "private" | "unknown";
    notes: string[];
  };
}

export interface StationStatus {
  station_id: string;
  timestamp: string;
  total_ports: number;
  operational_ports: number;
  occupied_ports: number;
  available_ports: number;
  offline_ports: number;
  unknown_ports: number;
  occupancy_ratio: number | null;
  queue_length: number | null;
  avg_session_duration_min: number | null;
  data_source: string;
}

export interface Vehicle {
  vehicle_id: string;
  make: string;
  model: string;
  variant: string | null;
  battery_capacity_kwh: number;
  usable_battery_kwh: number;
  consumption_wh_km: number;
  max_ac_power_kw: number;
  max_dc_power_kw: number;
  reserve_soc: number;
  default_target_soc: number;
}

export interface GeoPoint {
  lat: number;
  lon: number;
  label?: string | null;
}

export interface DemoScenario {
  scenario_id: string;
  name: string;
  vehicle_id: string;
  initial_soc: number;
  target_soc: number;
  origin: GeoPoint;
  destination: GeoPoint;
  departure_at: string;
  event_ids: string[];
}

export interface RouteResult {
  route_id: string;
  provider: "goong" | "osrm";
  resolution_source: "cache" | "live";
  origin: GeoPoint;
  destination: GeoPoint;
  geometry: { type: "LineString"; coordinates: Coordinates[] };
  distance_m: number;
  duration_s: number;
  flags: string[];
}

export interface RecommendationItem {
  station_id: string;
  station_name: string;
  route_id: string;
  route_provider: string;
  route: RouteResult;
  matched_connectors: string[];
  effective_power_kw: number;
  route_distance_to_station_m: number;
  route_duration_to_station_s: number;
  detour_min: number;
  arrival_soc: number;
  predicted_occupied_ports: number;
  predicted_occupancy_ratio: number | null;
  prediction_source: string;
  estimated_wait_min: number;
  estimated_charge_min: number;
  energy_to_add_kwh: number;
  wait_score: number;
  detour_score: number;
  charging_time_score: number;
  soc_risk_score: number;
  final_score: number;
  rank: number;
  flags: string[];
}

export interface CandidateExclusion {
  station_id: string;
  reason_codes: string[];
}

export interface JourneyRecommendation {
  scenario_id: string;
  generated_at: string;
  vehicle_id: string;
  direct_route: RouteResult;
  recommendations: RecommendationItem[];
  excluded_candidates: CandidateExclusion[];
  active_event_ids: string[];
}

export interface ModelStatus {
  prediction_source: "persistence" | "model";
  model_artifact_available: boolean;
  preprocessor_artifact_available: boolean;
  metadata_available: boolean;
  model_adapter_loaded: boolean;
  release_ready: boolean;
  flags: string[];
}

export interface JourneyRequest {
  scenario_id: string;
  apply_scenario_events: boolean;
  vehicle_id: string;
  initial_soc: number;
  target_soc: number;
  origin: GeoPoint;
  destination: GeoPoint;
  departure_at: string;
}

export interface PlaceSuggestion {
  place_id: string;
  description: string;
  main_text: string;
  secondary_text: string;
  provider: "goong" | "demo";
}

export interface GeocodedPlace {
  place_id: string;
  label: string;
  location: GeoPoint;
  provider: "goong" | "demo";
}

export interface PlannedArrival {
  arrival_id: string;
  station_id: string;
  vehicle_id: string | null;
  eta_at: string;
  route_id: string | null;
  status: "planned" | "arrived" | "cancelled" | "expired";
}
