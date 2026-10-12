import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import { api } from "./api";
import App from "./App";
import {
  demoClock,
  modelStatus,
  recommendation,
  recommendationItem,
  station,
  status,
  vehicle,
} from "./test/fixtures";

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
    logDirectionClick: vi.fn(),
    reverseGeocode: vi.fn(),
    demoClock: vi.fn(),
    setDemoClock: vi.fn(),
    resetDemoClock: vi.fn(),
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
  mockedApi.demoClock.mockResolvedValue(demoClock);
  mockedApi.searchRoute.mockResolvedValue(recommendation);
  mockedApi.logDirectionClick.mockResolvedValue(undefined);
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

test("pressing Chỉ đường after a route search logs the rank-1 and the chosen station", async () => {
  // The panel opens on the first listed item (rank 2); the system's pick is rank 1, listed second.
  const chosen = { ...recommendationItem, rank: 2, total_min: 50 };
  const best = { ...recommendationItem, rank: 1, station_id: "ST_BEST", station_name: "Best" };
  mockedApi.searchRoute.mockResolvedValue({
    ...recommendation,
    recommendations: [chosen, best],
  });
  render(<App />);

  fireEvent.click(await screen.findByRole("button", { name: "Tìm đường đi" }));
  fireEvent.click(await screen.findByRole("link", { name: "Chỉ đường" }));

  await waitFor(() => expect(mockedApi.logDirectionClick).toHaveBeenCalledTimes(1));
  expect(mockedApi.logDirectionClick).toHaveBeenCalledWith({
    mode: "route",
    origin: expect.objectContaining({ lat: 10.7075, lon: 106.705 }),
    destination: expect.objectContaining({ lat: 10.806, lon: 106.687 }),
    vehicle_id: vehicle.vehicle_id,
    battery_pct: 50,
    recommended_station_id: "ST_BEST",
    actual_station_id: recommendationItem.station_id,
  });
});

test("station search logs a click without a destination", async () => {
  mockedApi.searchStations.mockResolvedValue({
    stations: [recommendationItem],
    excluded_candidates: [],
    nearest_station_name: null,
    missing_km: null,
    reachable_km: 30,
  });
  render(<App />);

  fireEvent.click(await screen.findByRole("tab", { name: "Tìm trạm" }));
  fireEvent.click(screen.getByRole("button", { name: "Tìm trạm" }));
  fireEvent.click(await screen.findByRole("link", { name: "Chỉ đường" }));

  await waitFor(() =>
    expect(mockedApi.logDirectionClick).toHaveBeenCalledWith(
      expect.objectContaining({
        mode: "stations",
        destination: null,
        recommended_station_id: recommendationItem.station_id,
        actual_station_id: recommendationItem.station_id,
      }),
    ),
  );
});
