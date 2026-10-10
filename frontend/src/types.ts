export type Coordinates = [number, number];

export interface StationBounds {
  west: number;
  south: number;
  east: number;
  north: number;
}

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
    provider_station_id: string | null;
    name: string;
    address: string;
    operator: string | null;
    zone_id: string | null;
    total_ports: number;
    connectors: StationConnector[];
    amenities: string[];
    opening_hours: string | Record<string, unknown> | null;
    access: "public" | "customers" | "private" | "unknown";
    notes: string[];
    source_provider: string;
    source_updated_at: string | null;
    source_updated_at_basis: "source" | "database_updated_at" | "missing";
    synthetic_fields: string[];
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
  is_stale: boolean;
}

export interface StationOccupancyForecast {
  station_id: string;
  generated_at: string;
  target_at: string;
  requested_horizon_min: number;
  used_horizon_min: number;
  predicted_occupancy_ratio: number | null;
  predicted_occupied_ports: number;
  operational_ports: number;
  prediction_source: "model" | "persistence";
  model_version: string | null;
  confidence: number | null;
  flags: string[];
  data_source: "derived";
}

export interface StationOccupancyObservation {
  station_id: string;
  bucket_at: string;
  total_ports: number;
  operational_ports: number;
  occupied_ports: number;
  occupancy_ratio: number | null;
  queue_length: number | null;
  data_source: "observed";
}

export interface Vehicle {
  vehicle_id: string;
  make: string;
  model: string;
  variant: string | null;
  battery_capacity_kwh: number;
  usable_battery_kwh: number | null;
  ac_connectors: string[];
  dc_connectors: string[];
  max_ac_power_kw: number;
  max_dc_power_kw: number;
  consumption_wh_km: number;
  reserve_soc: number;
  default_target_soc: number;
  charging_efficiency: number;
  source: string;
  is_synthetic: boolean;
  synthetic_fields: string[];
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
  waypoints: RouteWaypoint[];
  geometry: { type: "LineString"; coordinates: Coordinates[] };
  distance_m: number;
  duration_s: number;
  legs: RouteLeg[];
  flags: string[];
}

export interface RouteWaypoint extends GeoPoint {
  station_id?: string | null;
}

export interface RouteLeg {
  origin: GeoPoint;
  destination: GeoPoint;
  distance_m: number;
  duration_s: number;
  geometry: { type: "LineString"; coordinates: Coordinates[] } | null;
  provider: "goong" | "osrm";
  retrieved_at: string;
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
  drive_to_station_min: number;
  drive_station_to_destination_min: number;
  detour_min: number;
  arrival_soc: number;
  destination_soc: number;
  minimum_soc: number;
  predicted_occupied_ports: number;
  predicted_occupancy_ratio: number | null;
  predicted_free_ports: number | null;
  prediction_source: string;
  model_version: string | null;
  estimated_wait_min: number;
  wait_expected_min: number | null;
  wait_probability: number | null;
  wait_p90_min: number | null;
  wait_method: "erlang_c" | "scoring_cap";
  wait_data_source: "derived";
  estimated_charge_min: number;
  charge_min: number | null;
  soc_after_charge: number | null;
  total_time_min: number;
  energy_to_add_kwh: number;
  /** Diagnostic component score; does not determine rank. */
  wait_score: number;
  detour_score: number;
  charging_time_score: number;
  soc_risk_score: number;
  /** Legacy weighted diagnostic score; rank follows ranking_policy_version. */
  final_score: number;
  rank: number;
  flags: string[];
}

export interface CandidateExclusion {
  station_id: string;
  reason_codes: string[];
}

export interface UnreachableStationFallback {
  station_id: string;
  station_name: string;
  straight_line_distance_m: number;
  is_reachable: false;
  reason_codes: string[];
}

export type StationIncidentType =
  | "port_unavailable"
  | "queue_inaccurate"
  | "access_problem"
  | "safety_concern"
  | "other";

export interface StationIncidentReport {
  incident_id: string;
  journey_id: string;
  station_id: string;
  incident_type: StationIncidentType;
  description: string;
  status: "open" | "triaged" | "resolved" | "rejected";
  created_at: string;
  data_source: "user_report";
}

export interface JourneyRecommendation {
  scenario_id: string | null;
  journey_id: string | null;
  journey_access_token?: string | null;
  generated_at: string;
  vehicle_id: string;
  direct_route: RouteResult;
  outcome: "direct_no_charge" | "charging_stops" | "no_reachable_station";
  recommendations: RecommendationItem[];
  excluded_candidates: CandidateExclusion[];
  fallback_candidate: UnreachableStationFallback | null;
  active_event_ids: string[];
  flags: string[];
  candidate_limit: number | null;
  ranking_policy_version: string;
  scoring_method: "fixed_threshold_weighted_sum";
}

export interface ModelStatus {
  prediction_source: "persistence" | "model";
  model_artifact_available: boolean;
  preprocessor_artifact_available: boolean;
  metadata_available: boolean;
  model_adapter_loaded: boolean;
  release_ready: boolean;
  flags: string[];
  model_version: string | null;
  model_profile: string | null;
  serving_reason: string | null;
}

export interface JourneyRequest {
  scenario_id?: string;
  apply_scenario_events?: boolean;
  vehicle_id: string;
  initial_soc: number;
  target_soc: number;
  origin: GeoPoint;
  destination: GeoPoint;
  departure_at: string;
}

export interface JourneyPositionRequest {
  recorded_at: string;
  location: GeoPoint;
  speed_kmh?: number;
  heading?: number;
  battery_pct: number;
  distance_km?: number;
}

export interface StationIncidentCreateRequest {
  journey_id: string;
  idempotency_key: string;
  incident_type: StationIncidentType;
  description: string;
}

export interface RouteRequest {
  origin: GeoPoint;
  destination: GeoPoint;
  waypoints?: RouteWaypoint[];
  preferred_route_id?: string | null;
}

export interface PlannedArrivalCommitRequest {
  arrival_id: string;
  journey_id?: string | null;
  station_id: string;
  vehicle_id: string;
  departure_at: string;
  route_id: string;
  route_duration_to_station_s: number;
  expected_energy_kwh: number;
  expected_charge_duration_min: number;
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
  journey_id: string | null;
  station_id: string;
  vehicle_id: string | null;
  created_at: string;
  eta_at: string;
  eta_window_start: string;
  eta_window_end: string;
  expected_energy_kwh: number;
  expected_charge_duration_min: number;
  arrival_probability: number;
  expires_at: string;
  route_id: string | null;
  status: "planned" | "arrived" | "cancelled" | "expired";
  data_source: string;
}

export interface SyntheticDuration {
  kind: "fixed" | "uniform";
  value_min?: number | null;
  min_min?: number | null;
  max_min?: number | null;
}

export interface QueueLabPort {
  port_id: string;
  connector_types: string[];
  state: "available" | "charging" | "offline";
  remaining_port_release?: SyntheticDuration | null;
}

export interface QueueLabVehicle {
  vehicle_id: string;
  queue_position: number;
  connector_types: string[];
  charging_duration: SyntheticDuration;
}

export interface QueueLabRequest {
  evaluation_at: string;
  ports: QueueLabPort[];
  confirmed_queue: QueueLabVehicle[];
  requester_connector_types: string[];
  requester_charge_duration: SyntheticDuration;
  trials: number;
  seed: number;
  wait_threshold_min: number;
}

export interface QueueLabTimelineEntry {
  port_id: string;
  vehicle_id: string;
  kind: "active_session" | "confirmed_queue" | "requester";
  start_at: string;
  end_at: string;
}

export interface QueueLabMonteCarloSummary {
  trials: number;
  seed: number;
  p10_wait_min: number | null;
  p50_wait_min: number | null;
  p90_wait_min: number | null;
  probability_wait_over_threshold: number | null;
  wait_threshold_min: number;
}

export interface QueueLabResult {
  estimated_start_at: string | null;
  estimated_wait_min: number | null;
  timeline: QueueLabTimelineEntry[];
  monte_carlo: QueueLabMonteCarloSummary;
  caveats: string[];
}
