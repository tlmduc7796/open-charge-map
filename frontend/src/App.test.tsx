import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import { api } from "./api";
import App from "./App";
import { modelStatus, recommendation, station, status, vehicle } from "./test/fixtures";

vi.mock("./api", () => ({
  api: {
    stations: vi.fn(),
    stationStatus: vi.fn(),
    vehicles: vi.fn(),
    modelStatus: vi.fn(),
    geocodeSuggestions: vi.fn(),
    geocodeDetails: vi.fn(),
    searchRoute: vi.fn(),
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
  mockedApi.modelStatus.mockResolvedValue(modelStatus);
  mockedApi.searchRoute.mockResolvedValue(recommendation);
  mockedApi.geocodeSuggestions.mockResolvedValue([]);
});

test("loads backend data and renders a recommendation from mocked API", async () => {
  render(<App />);
  expect(screen.getByText(/Đang kết nối Smart EV backend/i)).toBeInTheDocument();

  expect(await screen.findByRole("heading", { name: /Chọn trạm sạc phù hợp/i })).toBeInTheDocument();
  expect(screen.getByText("Quãng đường tối đa EV có thể đi")).toBeInTheDocument();
  expect(screen.getByText("150 km")).toBeInTheDocument();
  fireEvent.change(screen.getByRole("slider", { name: "Quãng đường tối đa EV có thể đi" }), {
    target: { value: "120" },
  });
  fireEvent.click(screen.getByRole("button", { name: /Tìm trạm phù hợp/i }));

  expect((await screen.findAllByText(station.properties.name)).length).toBeGreaterThan(0);
  expect(screen.getByText("156 km")).toBeInTheDocument();
  await waitFor(() =>
    expect(mockedApi.searchRoute).toHaveBeenCalledWith(
      expect.objectContaining({
        vehicle_id: vehicle.vehicle_id,
        battery_pct: 40,
      }),
    ),
  );
});

test("shows a recoverable backend error state", async () => {
  mockedApi.vehicles.mockRejectedValueOnce(new Error("Backend unavailable"));
  render(<App />);

  expect(await screen.findByRole("heading", { name: /Không thể khởi tạo ứng dụng/i })).toBeInTheDocument();
  expect(screen.getByText("Backend unavailable")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Thử lại/i })).toBeInTheDocument();
});

test("shows an empty recommendation state", async () => {
  mockedApi.searchRoute.mockResolvedValueOnce({
    ...recommendation,
    recommendations: [],
    excluded_candidates: [{ station_id: station.properties.station_id, reason_codes: ["STATION_OFFLINE"] }],
  });
  render(<App />);

  await screen.findByRole("heading", { name: /Chọn trạm sạc phù hợp/i });
  fireEvent.click(screen.getByRole("button", { name: /Tìm trạm phù hợp/i }));
  expect(await screen.findByText(/Không có trạm tương thích/i)).toBeInTheDocument();
});

test("explains when the battery is enough and no charging stop is needed", async () => {
  mockedApi.searchRoute.mockResolvedValueOnce({
    ...recommendation,
    case: "enough",
    recommendations: [],
  });
  render(<App />);

  await screen.findByRole("heading", { name: /Chọn trạm sạc phù hợp/i });
  fireEvent.click(screen.getByRole("button", { name: /Tìm trạm phù hợp/i }));
  expect(await screen.findByText(/Pin đủ để tới điểm đến/i)).toBeInTheDocument();
});
