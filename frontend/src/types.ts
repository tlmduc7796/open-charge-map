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

/** Availability colour computed by the backend (thresholds come from its `app_config`). */
export type StationColor = "green" | "yellow" | "red" | "grey";

export interface AvailabilityPoint {
  /** Minutes from now; 0 is the live reading, 5..30 are predictions. */
  offset_min: number;
  available_ports: number;
  prediction_source: string;
  flags: string[];
}

export interface StationForecast {
  station_id: string;
  total_ports: number;
  operational_ports: number;
  points: AvailabilityPoint[];
  generated_at: string;
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

/** Which journey endpoint the next map click will set. */
export type PickTarget = "origin" | "destination";

export interface RouteResult {
  route_id: string;
  provider: string;
  geometry: { type: "LineString"; coordinates: Coordinates[] };
  distance_m: number;
  duration_s: number;
}

export interface RecommendationItem {
  rank: number;
  station_id: string;
  station_name: string;
  connectors: string[];
  route: RouteResult;
  distance_km: number;
  travel_min: number;
  wait_min: number;
  charge_min: number;
  to_dest_min: number | null;
  total_min: number;
  arrive_battery_pct: number;
  prediction_source: string;
  flags: string[];
}

export interface CandidateExclusion {
  station_id: string;
  reason_codes: string[];
}

export interface JourneyRecommendation {
  search_id: string;
  case: "enough" | "needCharge" | "fallback";
  generated_at: string;
  direct_route: RouteResult;
  direct_min: number;
  recommendations: RecommendationItem[];
  excluded_candidates: CandidateExclusion[];
  missing_km: number | null;
  nearest_station_name: string | null;
}

export interface ModelStatus {
  prediction_source: "persistence" | "model" | "default";
  model_artifact_available: boolean;
  preprocessor_artifact_available: boolean;
  metadata_available: boolean;
  model_adapter_loaded: boolean;
  release_ready: boolean;
  flags: string[];
}

export interface SearchRequest {
  origin: GeoPoint;
  destination: GeoPoint;
  vehicle_id: string;
  battery_pct: number;
  /** Battery already reaches the destination: also rank stations to visit voluntarily. */
  include_optional_stops?: boolean;
}

export interface SearchStationsRequest {
  location: GeoPoint;
  vehicle_id: string;
  battery_pct: number;
}

export interface StationSearchResult {
  stations: RecommendationItem[];
  excluded_candidates: CandidateExclusion[];
  nearest_station_name: string | null;
  missing_km: number | null;
  reachable_km: number;
}

export interface PlaceSuggestion {
  place_id: string;
  description: string;
  main_text: string;
  secondary_text: string;
  provider: "goong";
}

export interface GeocodedPlace {
  place_id: string;
  label: string;
  location: GeoPoint;
  provider: "goong";
}
