import type {
  GeocodedPlace,
  JourneyRecommendation,
  ModelStatus,
  PlaceSuggestion,
  RecommendationItem,
  RouteResult,
  SearchRequest,
  Station,
  StationStatus,
  Vehicle,
} from "./types";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000").replace(
  /\/$/,
  "",
);

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail = payload?.error?.message ?? payload?.detail ?? `HTTP ${response.status}`;
    throw new Error(String(detail));
  }
  return response.json() as Promise<T>;
}

/** `/api/v1` JSON shapes (camelCase) that the adapter below converts. */
interface ApiRouteSummary {
  routeId: string;
  provider: string;
  distanceKm: number;
  travelMin: number;
  geometry: [number, number][];
}

interface ApiStationSummary {
  id: string;
  name: string;
  connectors: string[];
}

interface ApiSearchOption {
  rank: number;
  station: ApiStationSummary;
  route: ApiRouteSummary;
  distanceKm: number;
  travelMin: number;
  waitMin: number;
  chargeMin: number;
  toDestMin: number | null;
  totalMin: number;
  arriveBatteryPct: number;
  predictionSource: string;
  flags: string[];
}

interface ApiSearchRoute {
  searchId: string;
  case: "enough" | "needCharge" | "fallback";
  directRoute: ApiRouteSummary;
  directMin: number;
  stations: ApiSearchOption[];
  excludedCandidates: { stationId: string; reasonCodes: string[] }[];
  missingKm: number | null;
  nearestStation: ApiStationSummary | null;
  generatedAt: string;
}

const toRoute = (route: ApiRouteSummary): RouteResult => ({
  route_id: route.routeId,
  provider: route.provider,
  geometry: { type: "LineString", coordinates: route.geometry },
  distance_m: route.distanceKm * 1000,
  duration_s: route.travelMin * 60,
});

const toItem = (option: ApiSearchOption): RecommendationItem => ({
  rank: option.rank,
  station_id: option.station.id,
  station_name: option.station.name,
  connectors: option.station.connectors,
  route: toRoute(option.route),
  distance_km: option.distanceKm,
  travel_min: option.travelMin,
  wait_min: option.waitMin,
  charge_min: option.chargeMin,
  to_dest_min: option.toDestMin,
  total_min: option.totalMin,
  arrive_battery_pct: option.arriveBatteryPct,
  prediction_source: option.predictionSource,
  flags: option.flags,
});

export function toJourneyRecommendation(response: ApiSearchRoute): JourneyRecommendation {
  return {
    search_id: response.searchId,
    case: response.case,
    generated_at: response.generatedAt,
    direct_route: toRoute(response.directRoute),
    direct_min: response.directMin,
    recommendations: response.stations.map(toItem),
    excluded_candidates: response.excludedCandidates.map((item) => ({
      station_id: item.stationId,
      reason_codes: item.reasonCodes,
    })),
    missing_km: response.missingKm,
    nearest_station_name: response.nearestStation?.name ?? null,
  };
}

export const api = {
  stations: () => requestJson<Station[]>("/stations"),
  stationStatus: (stationId: string) =>
    requestJson<StationStatus>(`/stations/${stationId}/status`),
  vehicles: () => requestJson<Vehicle[]>("/vehicles"),
  modelStatus: () => requestJson<ModelStatus>("/model/status"),
  geocodeSuggestions: (query: string) =>
    requestJson<PlaceSuggestion[]>(`/geocoding/autocomplete?query=${encodeURIComponent(query)}`),
  geocodeDetails: (placeId: string) =>
    requestJson<GeocodedPlace>(`/geocoding/details/${encodeURIComponent(placeId)}`),
  searchRoute: async (payload: SearchRequest): Promise<JourneyRecommendation> => {
    const response = await requestJson<ApiSearchRoute>("/api/v1/search/route", {
      method: "POST",
      body: JSON.stringify({
        origin: { lat: payload.origin.lat, lng: payload.origin.lon },
        destination: { lat: payload.destination.lat, lng: payload.destination.lon },
        vehicleId: payload.vehicle_id,
        batteryPct: payload.battery_pct,
      }),
    });
    return toJourneyRecommendation(response);
  },
};
