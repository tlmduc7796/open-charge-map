import type {
  DemoScenario,
  JourneyRecommendation,
  JourneyRequest,
  ModelStatus,
  GeocodedPlace,
  PlaceSuggestion,
  PlannedArrival,
  RouteResult,
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
    const detail = payload?.detail ?? `HTTP ${response.status}`;
    throw new Error(String(detail));
  }
  return response.json() as Promise<T>;
}

export const api = {
  stations: () => requestJson<Station[]>("/stations"),
  stationStatus: (stationId: string) =>
    requestJson<StationStatus>(`/stations/${stationId}/status`),
  vehicles: () => requestJson<Vehicle[]>("/vehicles"),
  scenarios: () => requestJson<DemoScenario[]>("/demo/scenarios"),
  modelStatus: () => requestJson<ModelStatus>("/model/status"),
  geocodeSuggestions: (query: string) =>
    requestJson<PlaceSuggestion[]>(`/geocoding/autocomplete?query=${encodeURIComponent(query)}`),
  geocodeDetails: (placeId: string) =>
    requestJson<GeocodedPlace>(`/geocoding/details/${encodeURIComponent(placeId)}`),
  recommend: (payload: JourneyRequest) =>
    requestJson<JourneyRecommendation>("/journey/recommend", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  route: (routeId: string, origin: GeoPointLike, destination: GeoPointLike) =>
    requestJson<RouteResult>("/route", {
      method: "POST",
      body: JSON.stringify({
        origin,
        destination,
        preferred_route_id: routeId,
      }),
    }),
  resetDemo: () => requestJson<{ status: string }>("/demo/reset", { method: "POST" }),
  commitArrival: (payload: {
    station_id: string;
    vehicle_id: string;
    departure_at: string;
    route_id: string;
    route_duration_to_station_s: number;
    expected_energy_kwh: number;
    expected_charge_duration_min: number;
  }) => requestJson<PlannedArrival>("/planned-arrivals/commit", {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  cancelArrival: (arrivalId: string) =>
    requestJson<PlannedArrival>(`/planned-arrivals/${arrivalId}/cancel`, { method: "POST" }),
};

type GeoPointLike = { lat: number; lon: number; label?: string | null };
