import type {
  DemoScenario,
  JourneyRecommendation,
  JourneyRequest,
  JourneyPositionRequest,
  GeoPoint,
  ModelStatus,
  QueueLabRequest,
  QueueLabResult,
  GeocodedPlace,
  PlaceSuggestion,
  PlannedArrival,
  PlannedArrivalCommitRequest,
  RouteRequest,
  RouteResult,
  Station,
  StationBounds,
  StationOccupancyForecast,
  StationOccupancyObservation,
  StationIncidentReport,
  StationIncidentCreateRequest,
  StationStatus,
  Vehicle,
} from "./types";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000").replace(
  /\/$/,
  "",
);
let accessTokenProvider: (() => string | null) | null = null;

export function setAccessTokenProvider(provider: (() => string | null) | null): void {
  accessTokenProvider = provider;
}

export function clearJourneySessionState(): void {
  fallbackIdempotencyKeys.clear();
  try {
    for (const key of Object.keys(sessionStorage)) {
      if (
        key === "smart-ev-current-journey-id"
        || key === "smart-ev-authenticated-subject"
        || key.startsWith("journey-token:")
        || key.startsWith("journey:")
      ) {
        sessionStorage.removeItem(key);
      }
    }
  } catch {
    // The page may run with storage disabled; in-memory keys are still cleared.
  }
}

function authenticatedHeaders(headers?: HeadersInit): Headers {
  const result = new Headers(headers);
  if (!result.has("Authorization")) {
    const token = accessTokenProvider?.();
    if (token) result.set("Authorization", `Bearer ${token}`);
  }
  return result;
}

export class ApiRequestError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly errorCode: string | null,
    readonly requestId: string | null,
  ) {
    super(message);
    this.name = "ApiRequestError";
  }
}

async function responseError(response: Response): Promise<ApiRequestError> {
  const payload = await response.json().catch(() => null);
  const detail = payload?.detail;
  const reason = typeof detail === "string"
    ? detail
    : detail === undefined
      ? `HTTP ${response.status}`
      : JSON.stringify(detail);
  const requestId = response.headers.get("X-Request-ID");
  const message = requestId ? `${reason} (request ID: ${requestId})` : reason;
  const errorCode = typeof payload?.error_code === "string" ? payload.error_code : null;
  return new ApiRequestError(message, response.status, errorCode, requestId);
}

const fallbackIdempotencyKeys = new Map<string, string>();

function fallbackFingerprint(value: string): string {
  let first = 0x811c9dc5;
  let second = 0x9e3779b9;
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    first = Math.imul(first ^ code, 0x01000193);
    second = Math.imul(second ^ code, 0x85ebca6b);
  }
  return `${value.length.toString(36)}-${(first >>> 0).toString(36)}-${(second >>> 0).toString(36)}`;
}

async function journeyIdempotencyKey(body: string): Promise<{
  key: string;
  clear: () => void;
}> {
  let storageKey: string;
  try {
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(body));
    storageKey = Array.from(new Uint8Array(digest), (byte) =>
      byte.toString(16).padStart(2, "0"),
    ).join("");
  } catch {
    storageKey = fallbackFingerprint(body);
  }
  const mapKey = `journey:${storageKey}`;
  let key = fallbackIdempotencyKeys.get(mapKey);
  try {
    key ??= sessionStorage.getItem(mapKey) ?? undefined;
  } catch {
    // Continue with the in-memory key if browser storage is blocked.
  }
  if (!key) {
    if (!crypto.randomUUID) throw new Error("Secure random IDs are unavailable in this browser.");
    key = crypto.randomUUID();
  }
  fallbackIdempotencyKeys.set(mapKey, key);
  try {
    sessionStorage.setItem(mapKey, key);
  } catch {
    // Keep the retry key in memory for the current page.
  }
  return {
    key,
    clear: () => {
      fallbackIdempotencyKeys.delete(mapKey);
      try {
        sessionStorage.removeItem(mapKey);
      } catch {
        // Nothing else to clear when browser storage is blocked.
      }
    },
  };
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: authenticatedHeaders({ "Content-Type": "application/json", ...init?.headers }),
  });
  if (!response.ok) {
    throw await responseError(response);
  }
  return response.json() as Promise<T>;
}

export const api = {
  realtimeStatusEventsUrl: (stationIds: string[] = []) => {
    const query = new URLSearchParams();
    stationIds.forEach((stationId) => query.append("station_ids", stationId));
    const suffix = query.size ? `?${query.toString()}` : "";
    return `${API_BASE_URL}/realtime/stations/status/events${suffix}`;
  },
  stationsInBounds: (bounds: StationBounds, limit = 200) => {
    const query = new URLSearchParams({
      west: String(bounds.west),
      south: String(bounds.south),
      east: String(bounds.east),
      north: String(bounds.north),
      limit: String(limit),
    });
    return requestJson<Station[]>(`/stations/search?${query.toString()}`);
  },
  station: (stationId: string) =>
    requestJson<Station>(`/stations/${encodeURIComponent(stationId)}`),
  stationStatuses: (stationIds: string[]) => {
    const query = new URLSearchParams();
    stationIds.forEach((stationId) => query.append("station_ids", stationId));
    return requestJson<StationStatus[]>(`/stations/statuses?${query.toString()}`);
  },
  stationStatus: (stationId: string) =>
    requestJson<StationStatus>(`/stations/${encodeURIComponent(stationId)}/status`),
  stationForecast: (stationId: string, horizonMin = 15) =>
    requestJson<StationOccupancyForecast>(
      `/stations/${encodeURIComponent(stationId)}/forecast?horizon_min=${horizonMin}`,
    ),
  stationHistory: (stationId: string) =>
    requestJson<StationOccupancyObservation[]>(
      `/stations/${encodeURIComponent(stationId)}/history?limit=288`,
    ),
  vehicles: () => requestJson<Vehicle[]>("/vehicles"),
  scenarios: () => requestJson<DemoScenario[]>("/demo/scenarios"),
  modelStatus: () => requestJson<ModelStatus>("/model/status"),
  geocodeSuggestions: (query: string, signal?: AbortSignal) =>
    requestJson<PlaceSuggestion[]>(
      `/geocoding/autocomplete?query=${encodeURIComponent(query)}`,
      { signal },
    ),
  geocodeDetails: (placeId: string) =>
    requestJson<GeocodedPlace>(`/geocoding/details/${encodeURIComponent(placeId)}`),
  recommend: async (payload: JourneyRequest): Promise<JourneyRecommendation> => {
    const body = JSON.stringify(payload);
    const idempotency = await journeyIdempotencyKey(body);
    const response = await fetch(`${API_BASE_URL}/journey/recommend`, {
      method: "POST",
      headers: authenticatedHeaders({
        "Content-Type": "application/json",
        "Idempotency-Key": idempotency.key,
      }),
      body,
    });
    if (!response.ok) {
      const error = await responseError(response);
      if (response.status < 500 && response.status !== 429) idempotency.clear();
      throw error;
    }
    const recommendation = (await response.json()) as JourneyRecommendation;
    idempotency.clear();
    const accessToken = response.headers.get("X-Journey-Access-Token");
    if (accessToken && recommendation.journey_id) {
      try {
        sessionStorage.setItem(`journey-token:${recommendation.journey_id}`, accessToken);
      } catch {
        // Keep the token in component state when browser storage is unavailable.
      }
    }
    return { ...recommendation, journey_access_token: accessToken };
  },
  getJourney: (journeyId: string, accessToken: string) =>
    requestJson<{
      journey_id: string;
      request: JourneyRequest;
      recommendation: JourneyRecommendation;
      active_planned_arrival: PlannedArrival | null;
    }>(`/journeys/${encodeURIComponent(journeyId)}`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    }),
  recordJourneyPosition: (journeyId: string, payload: JourneyPositionRequest, accessToken: string) => requestJson<{
    position: {
      journey_id: string;
      recorded_at: string;
      distance_to_route_m: number | null;
      off_route: boolean;
      replan_suggested: boolean;
      route_version: number;
    };
    recommendation: JourneyRecommendation | null;
    replan_reason?: string;
  }>(`/journeys/${encodeURIComponent(journeyId)}/positions`, {
    method: "POST",
    body: JSON.stringify(payload),
    headers: { Authorization: `Bearer ${accessToken}` },
  }),
  reportStationIncident: (
    stationId: string,
    accessToken: string,
    payload: StationIncidentCreateRequest,
  ) => requestJson<StationIncidentReport>(
    `/stations/${encodeURIComponent(stationId)}/incidents`,
    {
      method: "POST",
      body: JSON.stringify(payload),
      headers: { Authorization: `Bearer ${accessToken}` },
    },
  ),
  route: (routeId: string, origin: GeoPoint, destination: GeoPoint) => {
    const payload: RouteRequest = {
      origin,
      destination,
      preferred_route_id: routeId,
    };
    return requestJson<RouteResult>("/route", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  resetDemo: () => requestJson<{ status: string }>("/demo/reset", { method: "POST" }),
  queueLabScenario: () => requestJson<QueueLabRequest>("/queue-lab/default-scenario"),
  simulateQueueLab: (payload: QueueLabRequest) =>
    requestJson<QueueLabResult>("/queue-lab/simulate", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  commitArrival: (
    payload: PlannedArrivalCommitRequest,
    accessToken?: string | null,
  ) => requestJson<PlannedArrival>("/planned-arrivals/commit", {
    method: "POST",
    body: JSON.stringify(payload),
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : undefined,
  }),
  cancelArrival: (arrivalId: string, journeyId?: string | null, accessToken?: string | null) =>
    requestJson<PlannedArrival>(
      `/planned-arrivals/${encodeURIComponent(arrivalId)}/cancel${journeyId ? `?journey_id=${encodeURIComponent(journeyId)}` : ""}`,
      {
        method: "POST",
        headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : undefined,
      },
    ),
};
