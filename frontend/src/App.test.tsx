import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import { api } from "./api";
import App from "./App";
import { modelStatus, recommendation, station, status, vehicle } from "./test/fixtures";

vi.mock("./api", () => ({
  api: {
    stations: vi.fn(),
    stationStatus: vi.fn(),
    stationColors: vi.fn(),
    vehicles: vi.fn(),
    modelStatus: vi.fn(),
    geocodeSuggestions: vi.fn(),
    geocodeDetails: vi.fn(),
    searchRoute: vi.fn(),
    searchStations: vi.fn(),
    reverseGeocode: vi.fn(),
  },
}));

vi.mock("./components/MapView", () => ({
  default: ({ route, origin, destination, pickTarget, onMapPick }: {
    route: { route_id: string } | null;
    origin?: { lat: number; lon: number };
    destination?: { lat: number; lon: number };
    pickTarget?: "origin" | "destination" | null;
    onMapPick?: (point: { lat: number; lon: number }) => void;
  }) => (
    <div
      aria-label="mock map"
      data-route-id={route?.route_id ?? "none"}
      data-has-origin={String(Boolean(origin))}
      data-has-destination={String(Boolean(destination))}
      data-pick-target={pickTarget ?? "none"}
    >
      Map
      {pickTarget && (
        <button type="button" onClick={() => onMapPick?.({ lat: 10.8, lon: 106.68 })}>
          mock map pick
        </button>
      )}
    </div>
  ),
}));

const mockedApi = vi.mocked(api);

beforeEach(() => {
  mockedApi.stations.mockResolvedValue([station]);
  mockedApi.stationStatus.mockResolvedValue(status);
  mockedApi.stationColors.mockResolvedValue({ [station.properties.station_id]: "green" });
  mockedApi.vehicles.mockResolvedValue([vehicle]);
  mockedApi.modelStatus.mockResolvedValue(modelStatus);
  mockedApi.searchRoute.mockResolvedValue(recommendation);
  mockedApi.geocodeSuggestions.mockResolvedValue([]);
  mockedApi.reverseGeocode.mockResolvedValue({
    place_id: "reverse-test",
    label: "",
    location: { lat: 10.8, lon: 106.68 },
    provider: "goong",
  });
});

test("shows a recoverable backend error state", async () => {
  mockedApi.vehicles.mockRejectedValueOnce(new Error("Backend unavailable"));
  render(<App />);

  expect(await screen.findByRole("heading", { name: /Không thể khởi tạo ứng dụng/i })).toBeInTheDocument();
  expect(screen.getByText("Backend unavailable")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Thử lại/i })).toBeInTheDocument();
});

test("station search has a single start point and searches from it", async () => {
  mockedApi.searchStations.mockResolvedValue({
    stations: [],
    excluded_candidates: [],
    nearest_station_name: null,
    missing_km: null,
    reachable_km: 30,
  });
  render(<App />);

  fireEvent.click(await screen.findByRole("tab", { name: "Tìm trạm" }));

  expect(screen.getByRole("textbox", { name: "Điểm bắt đầu" })).toBeInTheDocument();
  expect(screen.queryByRole("textbox", { name: /Điểm đến/ })).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Tìm trạm" }));

  await waitFor(() =>
    expect(mockedApi.searchStations).toHaveBeenCalledWith(
      expect.objectContaining({ location: expect.objectContaining({ lat: 10.7075, lon: 106.705 }) }),
    ),
  );
});
