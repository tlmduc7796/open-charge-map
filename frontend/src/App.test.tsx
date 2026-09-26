import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import { api } from "./api";
import App from "./App";
import { modelStatus, recommendation, route, scenario, station, status, vehicle } from "./test/fixtures";

vi.mock("./api", () => ({
  api: {
    stations: vi.fn(),
    stationStatus: vi.fn(),
    vehicles: vi.fn(),
    scenarios: vi.fn(),
    modelStatus: vi.fn(),
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
  mockedApi.stations.mockResolvedValue([station]);
  mockedApi.stationStatus.mockResolvedValue(status);
  mockedApi.vehicles.mockResolvedValue([vehicle]);
  mockedApi.scenarios.mockResolvedValue([scenario]);
  mockedApi.modelStatus.mockResolvedValue(modelStatus);
  mockedApi.recommend.mockResolvedValue(recommendation);
  mockedApi.route.mockResolvedValue(route);
  mockedApi.resetDemo.mockResolvedValue({ status: "reset" });
  mockedApi.geocodeSuggestions.mockResolvedValue([]);
  mockedApi.commitArrival.mockResolvedValue({
    arrival_id: "ARR_TEST",
    station_id: station.properties.station_id,
    vehicle_id: vehicle.vehicle_id,
    eta_at: "2099-01-01T10:10:00+07:00",
    route_id: route.route_id,
    status: "planned",
  });
});

test("loads backend data and renders a recommendation from mocked API", async () => {
  render(<App />);
  expect(screen.getByText(/Đang kết nối Smart EV backend/i)).toBeInTheDocument();

  expect(await screen.findByRole("heading", { name: /Chọn trạm sạc phù hợp/i })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Tìm trạm phù hợp/i }));

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
  ));
  expect(await screen.findByText(/Đã xác nhận tuyến/i)).toBeInTheDocument();
});

test("shows a recoverable backend error state", async () => {
  mockedApi.scenarios.mockRejectedValueOnce(new Error("Backend unavailable"));
  render(<App />);

  expect(await screen.findByRole("heading", { name: /Không thể khởi tạo demo/i })).toBeInTheDocument();
  expect(screen.getByText("Backend unavailable")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Thử lại/i })).toBeInTheDocument();
});

test("shows an empty recommendation state", async () => {
  mockedApi.recommend.mockResolvedValueOnce({
    ...recommendation,
    recommendations: [],
    excluded_candidates: [{ station_id: station.properties.station_id, reason_codes: ["STATION_OFFLINE"] }],
  });
  render(<App />);

  await screen.findByRole("heading", { name: /Chọn trạm sạc phù hợp/i });
  fireEvent.click(screen.getByRole("button", { name: /Tìm trạm phù hợp/i }));
  expect(await screen.findByText(/Không có trạm tương thích/i)).toBeInTheDocument();
});
