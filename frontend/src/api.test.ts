import { afterEach, expect, test, vi } from "vitest";

import { ApiRequestError, api, setAccessTokenProvider } from "./api";

afterEach(() => {
  setAccessTokenProvider(null);
  vi.unstubAllGlobals();
});

test("adds the OIDC access token to API requests", async () => {
  const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
    new Response(JSON.stringify({ station_id: "ST_TEST" }), { status: 200 }),
  );
  vi.stubGlobal("fetch", fetchMock);
  setAccessTokenProvider(() => "oidc-access-token");

  await api.stationStatus("ST_TEST");

  const request = fetchMock.mock.calls[0]?.[1];
  expect(new Headers(request?.headers).get("Authorization")).toBe(
    "Bearer oidc-access-token",
  );
});

test("preserves the journey capability token over the OIDC token", async () => {
  const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
    new Response(JSON.stringify({}), { status: 200 }),
  );
  vi.stubGlobal("fetch", fetchMock);
  setAccessTokenProvider(() => "oidc-access-token");

  await api.cancelArrival("ARR_TEST", "JOURNEY_TEST", "journey-capability-token");

  const request = fetchMock.mock.calls[0]?.[1];
  expect(new Headers(request?.headers).get("Authorization")).toBe(
    "Bearer journey-capability-token",
  );
});

test("loads a persisted journey with its capability token", async () => {
  const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
    new Response(JSON.stringify({ journey_id: "journey-123" }), { status: 200 }),
  );
  vi.stubGlobal("fetch", fetchMock);
  setAccessTokenProvider(() => "oidc-access-token");

  await api.getJourney("journey-123", "journey-capability-token");

  expect(fetchMock.mock.calls[0]?.[0]).toBe("http://127.0.0.1:8000/journeys/journey-123");
  expect(new Headers(fetchMock.mock.calls[0]?.[1]?.headers).get("Authorization")).toBe(
    "Bearer journey-capability-token",
  );
});

test("uses bounded map and status queries and scopes realtime subscriptions", async () => {
  const fetchMock = vi.fn<typeof fetch>().mockImplementation(async () =>
    new Response(JSON.stringify([]), { status: 200 }),
  );
  vi.stubGlobal("fetch", fetchMock);
  await api.stationsInBounds({ west: 106.6, south: 10.6, east: 106.8, north: 10.9 });
  await api.stationStatuses(["ST_A", "ST_B"]);

  expect(fetchMock.mock.calls[0]?.[0]).toContain(
    "/stations/search?west=106.6&south=10.6&east=106.8&north=10.9&limit=200",
  );
  expect(fetchMock.mock.calls[1]?.[0]).toContain(
    "/stations/statuses?station_ids=ST_A&station_ids=ST_B",
  );
  expect(api.realtimeStatusEventsUrl(["ST_A", "ST_B"])).toContain(
    "?station_ids=ST_A&station_ids=ST_B",
  );
});

test("encodes station and arrival identifiers as URL path segments", async () => {
  const fetchMock = vi.fn<typeof fetch>().mockImplementation(async () =>
    new Response(JSON.stringify({}), { status: 200 }),
  );
  vi.stubGlobal("fetch", fetchMock);

  await api.stationStatus("station A?#");
  await api.cancelArrival("arrival A?#");

  expect(new URL(String(fetchMock.mock.calls[0]?.[0])).pathname).toBe(
    "/stations/station%20A%3F%23/status",
  );
  expect(new URL(String(fetchMock.mock.calls[1]?.[0])).pathname).toBe(
    "/planned-arrivals/arrival%20A%3F%23/cancel",
  );
});

test("preserves stable API error code, detail, status, and request ID", async () => {
  const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
    new Response(
      JSON.stringify({ detail: "journey not found", error_code: "NOT_FOUND" }),
      { status: 404, headers: { "X-Request-ID": "req-test-123" } },
    ),
  );
  vi.stubGlobal("fetch", fetchMock);

  const request = api.getJourney("journey-missing", "capability-token");

  await expect(request).rejects.toMatchObject({
    name: "ApiRequestError",
    message: "journey not found (request ID: req-test-123)",
    status: 404,
    errorCode: "NOT_FOUND",
    requestId: "req-test-123",
  } satisfies Partial<ApiRequestError>);
});
