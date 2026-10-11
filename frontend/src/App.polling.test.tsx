import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { api } from "./api";
import App from "./App";
import { modelStatus, recommendationItem, station, status, vehicle } from "./test/fixtures";
import type { Station } from "./types";

vi.mock("./api", () => ({
  api: {
    stations: vi.fn(),
    stationStatus: vi.fn(),
    stationColors: vi.fn(),
    stationForecast: vi.fn(),
    vehicles: vi.fn(),
    modelStatus: vi.fn(),
    geocodeSuggestions: vi.fn(),
    geocodeDetails: vi.fn(),
    searchRoute: vi.fn(),
    searchStations: vi.fn(),
    reverseGeocode: vi.fn(),
  },
}));

// Expose the colours App hands to the map so tests can see what a poll changed.
vi.mock("./components/MapView", () => ({
  default: ({ colors }: { colors: Record<string, string> }) => (
    <div aria-label="mock map" data-colors={JSON.stringify(colors)} />
  ),
}));

const mockedApi = vi.mocked(api);

const OTHER_ID = "ST_OTHER";
const otherStation: Station = {
  ...station,
  properties: { ...station.properties, station_id: OTHER_ID, name: "Trạm khác" },
};

/** Status polls registered by App; captured so the tests fire them instead of waiting 30 s. */
let polls: Array<() => void> = [];
let hidden = false;

beforeEach(() => {
  polls = [];
  hidden = false;
  Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
  const realSetInterval = window.setInterval.bind(window);
  vi.spyOn(window, "setInterval").mockImplementation(((
    callback: () => void,
    delay?: number,
    ...args: unknown[]
  ) => {
    // Testing Library's own 50 ms poller must keep running.
    if (delay !== undefined && delay >= 1000) {
      polls.push(callback);
      return 0;
    }
    return realSetInterval(callback, delay, ...args);
  }) as unknown as typeof window.setInterval);

  mockedApi.stations.mockResolvedValue([station, otherStation]);
  mockedApi.stationStatus.mockImplementation(async (id: string) => ({ ...status, station_id: id }));
  mockedApi.stationColors.mockResolvedValue({
    [station.properties.station_id]: "green",
    [OTHER_ID]: "green",
  });
  mockedApi.stationForecast.mockResolvedValue({
    station_id: station.properties.station_id,
    total_ports: 2,
    operational_ports: 2,
    generated_at: "2026-09-25T18:00:00+07:00",
    points: [],
  });
  mockedApi.vehicles.mockResolvedValue([vehicle]);
  mockedApi.modelStatus.mockResolvedValue(modelStatus);
  mockedApi.geocodeSuggestions.mockResolvedValue([]);
});

afterEach(() => {
  vi.restoreAllMocks();
  Reflect.deleteProperty(document, "hidden");
});

async function renderLoaded() {
  render(<App />);
  await waitFor(() => expect(polls).toHaveLength(1));
  await waitFor(() => expect(mockedApi.stationColors).toHaveBeenCalledTimes(1));
}

test("re-reads every station's status and colour on each poll", async () => {
  await renderLoaded();
  expect(mockedApi.stationStatus).toHaveBeenCalledTimes(2);

  act(() => polls[0]());

  await waitFor(() => expect(mockedApi.stationColors).toHaveBeenCalledTimes(2));
  expect(mockedApi.stationStatus).toHaveBeenCalledTimes(4);
});

test("a new colour from the backend reaches the UI without any user action", async () => {
  await renderLoaded();
  const mapColors = () => JSON.parse(screen.getByLabelText("mock map").dataset.colors ?? "{}");
  await waitFor(() => expect(mapColors()[station.properties.station_id]).toBe("green"));

  mockedApi.stationColors.mockResolvedValue({
    [station.properties.station_id]: "red",
    [OTHER_ID]: "green",
  });
  act(() => polls[0]());

  await waitFor(() => expect(mapColors()[station.properties.station_id]).toBe("red"));
  expect(mapColors()[OTHER_ID]).toBe("green");
});

test("does not poll while the tab is hidden and catches up when it becomes visible", async () => {
  await renderLoaded();

  hidden = true;
  act(() => polls[0]());
  await Promise.resolve();
  expect(mockedApi.stationColors).toHaveBeenCalledTimes(1);

  hidden = false;
  act(() => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await waitFor(() => expect(mockedApi.stationColors).toHaveBeenCalledTimes(2));
});

test("a failed poll keeps the app usable and the next poll recovers", async () => {
  await renderLoaded();

  mockedApi.stationColors.mockRejectedValueOnce(new Error("backend down"));
  act(() => polls[0]());
  await waitFor(() => expect(mockedApi.stationColors).toHaveBeenCalledTimes(2));
  expect(screen.queryByRole("heading", { name: /Không thể khởi tạo ứng dụng/i })).toBeNull();
  expect(screen.queryByText("backend down")).toBeNull();

  act(() => polls[0]());
  await waitFor(() => expect(mockedApi.stationColors).toHaveBeenCalledTimes(3));
});

test("a station search refreshes the status of every station, not only the selected one", async () => {
  mockedApi.searchStations.mockResolvedValue({
    stations: [recommendationItem],
    excluded_candidates: [],
    nearest_station_name: null,
    missing_km: null,
    reachable_km: 120,
  });
  await renderLoaded();
  const callsFor = (id: string) =>
    mockedApi.stationStatus.mock.calls.filter(([stationId]) => stationId === id).length;
  expect(callsFor(OTHER_ID)).toBe(1);

  fireEvent.click(screen.getByRole("tab", { name: "Tìm trạm" }));
  fireEvent.click(screen.getByRole("button", { name: "Tìm trạm" }));

  await waitFor(() => expect(mockedApi.searchStations).toHaveBeenCalledTimes(1));
  // OTHER_ID is not in the result, so only the post-search refresh can have re-read it.
  await waitFor(() => expect(callsFor(OTHER_ID)).toBe(2));
});
