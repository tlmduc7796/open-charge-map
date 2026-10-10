import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { modelStatus, recommendation, scenario, station, status, vehicle } from "./test/fixtures";

vi.stubEnv("VITE_DEMO_MODE", "false");

vi.mock("./api", () => ({
  api: {
    stationsInBounds: vi.fn(),
    station: vi.fn(),
    stationStatuses: vi.fn(),
    stationStatus: vi.fn(),
    stationForecast: vi.fn(),
    stationHistory: vi.fn(),
    vehicles: vi.fn(),
    scenarios: vi.fn(),
    modelStatus: vi.fn(),
    getJourney: vi.fn(),
    realtimeStatusEventsUrl: vi.fn(() => "/realtime/stations/status/events"),
    geocodeSuggestions: vi.fn(),
    geocodeDetails: vi.fn(),
    recommend: vi.fn(),
    route: vi.fn(),
    resetDemo: vi.fn(),
    commitArrival: vi.fn(),
    cancelArrival: vi.fn(),
  },
}));

vi.mock("./components/MapView", () => ({
  default: () => <div aria-label="mock map">Map</div>,
}));

const { api } = await import("./api");
const { default: App } = await import("./App");
const mockedApi = vi.mocked(api);

beforeEach(() => {
  sessionStorage.setItem("smart-ev-current-journey-id", "journey-123");
  sessionStorage.setItem("journey-token:journey-123", "journey-capability-token");
  mockedApi.stationsInBounds.mockResolvedValue([station]);
  mockedApi.station.mockResolvedValue(station);
  mockedApi.stationStatuses.mockResolvedValue([status]);
  mockedApi.stationStatus.mockResolvedValue(status);
  mockedApi.stationForecast.mockResolvedValue({
    station_id: station.properties.station_id,
    generated_at: "2026-10-09T10:00:00Z",
    target_at: "2026-10-09T10:15:00Z",
    requested_horizon_min: 15,
    used_horizon_min: 15,
    predicted_occupancy_ratio: 0.5,
    predicted_occupied_ports: 2,
    operational_ports: 4,
    prediction_source: "persistence",
    model_version: null,
    confidence: null,
    flags: ["PERSISTENCE_FALLBACK"],
    data_source: "derived",
  });
  mockedApi.stationHistory.mockResolvedValue([]);
  mockedApi.vehicles.mockResolvedValue([vehicle]);
  mockedApi.scenarios.mockResolvedValue([]);
  mockedApi.modelStatus.mockResolvedValue(modelStatus);
  mockedApi.getJourney.mockResolvedValue({
    journey_id: "journey-123",
    request: {
      vehicle_id: vehicle.vehicle_id,
      initial_soc: 0.42,
      target_soc: 0.85,
      origin: scenario.origin,
      destination: scenario.destination,
      departure_at: "2026-10-09T10:00:00Z",
    },
    recommendation: {
      ...recommendation,
      journey_id: "journey-123",
    },
    active_planned_arrival: {
      arrival_id: "ARR_RESTORED",
      journey_id: "journey-123",
      station_id: station.properties.station_id,
      vehicle_id: vehicle.vehicle_id,
      created_at: "2026-10-09T10:00:00Z",
      eta_at: "2026-10-09T10:10:00Z",
      eta_window_start: "2026-10-09T10:05:00Z",
      eta_window_end: "2026-10-09T10:15:00Z",
      expected_energy_kwh: 10,
      expected_charge_duration_min: 20,
      arrival_probability: 0.8,
      expires_at: "2026-10-09T10:20:00Z",
      route_id: recommendation.recommendations[0].route_id,
      status: "planned",
      data_source: "journey_recommendation",
    },
  });
});

afterEach(() => {
  cleanup();
  sessionStorage.clear();
  vi.clearAllMocks();
  vi.unstubAllEnvs();
});

test("restores the persisted release journey after page load", async () => {
  render(<App />);

  await waitFor(() => expect(mockedApi.getJourney).toHaveBeenCalledWith(
    "journey-123",
    "journey-capability-token",
  ));
  expect(await screen.findAllByText(station.properties.name)).not.toHaveLength(0);
  expect(await screen.findByText("Đã xác nhận tuyến")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Hủy planned arrival" })).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /Xác nhận tuyến đến trạm/i }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Tìm trạm tốt nhất/i })).toBeInTheDocument();
});

test("can retry initial API loading after release readiness recovers", async () => {
  mockedApi.stationsInBounds.mockRejectedValueOnce(new Error("API is not ready yet"));
  render(<App />);

  expect(await screen.findByRole("alert")).toHaveTextContent("API is not ready yet");
  fireEvent.click(screen.getByRole("button", { name: "Thử tải lại" }));

  expect(await screen.findByText("Đã xác nhận tuyến")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
