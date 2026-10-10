import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import { api } from "./api";
import App from "./App";
import { modelStatus, recommendation, route, scenario, station, status, vehicle } from "./test/fixtures";

vi.mock("./api", () => ({
  api: {
    stationsInBounds: vi.fn(),
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

const mockedApi = vi.mocked(api);

beforeEach(() => {
  mockedApi.stationsInBounds.mockResolvedValue([station]);
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
    flags: ["OBSERVED_HISTORY_UNAVAILABLE", "PERSISTENCE_FALLBACK"],
    data_source: "derived",
  });
  mockedApi.stationHistory.mockResolvedValue([]);
  mockedApi.vehicles.mockResolvedValue([vehicle]);
  mockedApi.scenarios.mockResolvedValue([scenario]);
  mockedApi.modelStatus.mockResolvedValue(modelStatus);
  mockedApi.recommend.mockResolvedValue(recommendation);
  mockedApi.route.mockResolvedValue(route);
  mockedApi.resetDemo.mockResolvedValue({ status: "reset" });
  mockedApi.geocodeSuggestions.mockResolvedValue([]);
  mockedApi.commitArrival.mockResolvedValue({
    arrival_id: "ARR_TEST",
    journey_id: null,
    station_id: station.properties.station_id,
    vehicle_id: vehicle.vehicle_id,
    created_at: "2099-01-01T10:00:00+07:00",
    eta_at: "2099-01-01T10:10:00+07:00",
    eta_window_start: "2099-01-01T10:05:00+07:00",
    eta_window_end: "2099-01-01T10:15:00+07:00",
    expected_energy_kwh: 10,
    expected_charge_duration_min: 20,
    arrival_probability: 0.8,
    expires_at: "2099-01-01T10:20:00+07:00",
    route_id: route.route_id,
    status: "planned",
    data_source: "journey_recommendation",
  });
});

test("loads backend data and renders a recommendation from mocked API", async () => {
  render(<App />);
  expect(screen.getByText(/Đang kết nối Smart EV backend/i)).toBeInTheDocument();

  expect(await screen.findByRole("heading", { name: "Chọn trạm sạc" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Tìm trạm tốt nhất/i }));

  expect((await screen.findAllByText(station.properties.name)).length).toBeGreaterThan(0);
  expect(mockedApi.recommend).toHaveBeenCalledWith(
    expect.objectContaining({ scenario_id: scenario.scenario_id, vehicle_id: vehicle.vehicle_id }),
  );
  await waitFor(() => expect(mockedApi.recommend).toHaveBeenCalledWith(
    expect.objectContaining({ origin: scenario.origin, destination: scenario.destination }),
  ));
  fireEvent.click(screen.getByRole("button", { name: /Xác nhận tuyến đến trạm/i }));
  await waitFor(() => expect(mockedApi.commitArrival).toHaveBeenCalledWith(
    expect.objectContaining({ station_id: station.properties.station_id }),
    undefined,
  ));
  expect(await screen.findByText(/Đã xác nhận tuyến/i)).toBeInTheDocument();
  expect(await screen.findByText(/Nguồn dự báo: persistence/i)).toBeInTheDocument();
});

test("shows a recoverable backend error state", async () => {
  mockedApi.scenarios.mockRejectedValueOnce(new Error("Backend unavailable"));
  render(<App />);

  expect(await screen.findByRole("heading", { name: /Không thể khởi tạo demo/i })).toBeInTheDocument();
  expect(screen.getByText("Backend unavailable")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Thử lại/i })).toBeInTheDocument();
});

test("marks station status unavailable when the REST status read fails", async () => {
  mockedApi.stationStatuses.mockRejectedValueOnce(new Error("Status service unavailable"));
  render(<App />);

  expect(await screen.findByText(/Station status: unavailable/)).toBeInTheDocument();
  expect(screen.getByText(/last data marked stale/)).toBeInTheDocument();
});

test("shows an empty recommendation state", async () => {
  mockedApi.recommend.mockResolvedValueOnce({
    ...recommendation,
    recommendations: [],
    excluded_candidates: [{ station_id: station.properties.station_id, reason_codes: ["STATION_OFFLINE"] }],
  });
  render(<App />);

  await screen.findByRole("heading", { name: "Chọn trạm sạc" });
  fireEvent.click(screen.getByRole("button", { name: /Tìm trạm tốt nhất/i }));
  expect(await screen.findByText(/Không tìm thấy trạm sạc khả thi/i)).toBeInTheDocument();
});
