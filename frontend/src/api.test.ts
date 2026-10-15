import { afterEach, expect, test, vi } from "vitest";
import { api } from "./api";
import type { PlanningRequest } from "./planning/types";

afterEach(() => vi.unstubAllGlobals());

function mockFetch() {
  const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
    new Response(JSON.stringify({}), { status: 200 }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

test("reading planner metadata does not trigger JSON content-type preflight", async () => {
  const fetchMock = mockFetch();
  await api.planningDemoSnapshot();
  const [url, request] = fetchMock.mock.calls[0];
  expect(url).toContain("/api/v1/planning/demo-snapshot");
  expect(new Headers(request?.headers).has("Content-Type")).toBe(false);
  expect(request?.body).toBeUndefined();
});

test("submitting a planner scenario still sends a JSON body and content type", async () => {
  const fetchMock = mockFetch();
  const payload: PlanningRequest = {
    contract_version: "0.1",
    study_area: { city_id: "VN-HCMC", boundary_version: "ADMINISTRATIVE_2025", pilot_extent_id: "demo" },
    run: { as_of: "2026-10-14T08:00:00+07:00", horizon_years: 3, data_snapshot_id: "demo", seed: 1, config_version: "technical-demo-v1", demand_scenario: "base" },
    candidate_source: { mode: "provided", candidate_ids: ["candidate"] },
    profile: "technical_opportunity",
    technical: { coverage_minutes: 15, charger_options: [{ charger_type: "DC", port_count: 4, power_kw_per_port: 80 }], budget_vnd: null },
    policy_package: null, finance_package: null,
  };
  await api.planningRecommendations(payload);
  const request = fetchMock.mock.calls[0][1];
  expect(request?.method).toBe("POST");
  expect(new Headers(request?.headers).get("Content-Type")).toBe("application/json");
  expect(JSON.parse(String(request?.body))).toEqual(payload);
});
