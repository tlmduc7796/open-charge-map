import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import { api } from "./api";
import App from "./App";
import { demoClock, modelStatus, recommendation, station, status, vehicle } from "./test/fixtures";
import type { DemoClock, StationForecast } from "./types";

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
    demoClock: vi.fn(),
    setDemoClock: vi.fn(),
    resetDemoClock: vi.fn(),
  },
}));

vi.mock("./components/MapView", () => ({
  default: ({ route, onStationSelect }: {
    route: { route_id: string } | null;
    onStationSelect: (id: string) => void;
  }) => (
    <div aria-label="mock map" data-route={route?.route_id ?? ""}>
      <button type="button" onClick={() => onStationSelect(station.properties.station_id)}>
        marker
      </button>
    </div>
  ),
}));

vi.mock("./planning/PlannerView", async () => {
  const { useState } = await import("react");
  return {
    default: ({ onModeChange }: { onModeChange: (mode: "driver" | "planner") => void }) => {
      const [count, setCount] = useState(0);
      return (
        <section>
          <output>Planner local state: {count}</output>
          <button type="button" onClick={() => setCount((value) => value + 1)}>Change planner state</button>
          <button type="button" onClick={() => onModeChange("driver")}>Return to driver</button>
        </section>
      );
    },
  };
});

const mockedApi = vi.mocked(api);

const forecast: StationForecast = {
  station_id: station.properties.station_id,
  total_ports: 2,
  operational_ports: 2,
  generated_at: "2026-09-25T18:00:00+07:00",
  points: [0, 5, 10, 15, 20, 25, 30].map((offset) => ({
    offset_min: offset,
    available_ports: 1,
    prediction_source: "model",
    flags: [],
  })),
};

/** The demo clock after the user jumped to 2026-10-03 07:45:30 (Vietnam time). */
const jumped: DemoClock = {
  ...demoClock,
  demo_now: "2026-10-03T00:45:30Z",
  offset_s: -800_000,
};

beforeEach(() => {
  mockedApi.stations.mockResolvedValue([station]);
  mockedApi.stationStatus.mockResolvedValue(status);
  mockedApi.stationColors.mockResolvedValue({ [station.properties.station_id]: "green" });
  mockedApi.stationForecast.mockResolvedValue(forecast);
  mockedApi.vehicles.mockResolvedValue([vehicle]);
  mockedApi.modelStatus.mockResolvedValue(modelStatus);
  mockedApi.searchRoute.mockResolvedValue(recommendation);
  mockedApi.geocodeSuggestions.mockResolvedValue([]);
  mockedApi.demoClock.mockResolvedValue(demoClock);
  // Like the real backend: after a change, reads of the clock return the new moment.
  mockedApi.setDemoClock.mockImplementation(async () => {
    mockedApi.demoClock.mockResolvedValue(jumped);
    return jumped;
  });
  mockedApi.resetDemoClock.mockImplementation(async () => {
    const real = { ...demoClock, demo_now: demoClock.wall_now, is_shifted: false, offset_s: 0 };
    mockedApi.demoClock.mockResolvedValue(real);
    return real;
  });
});

async function changeTime() {
  fireEvent.click(await screen.findByRole("button", { name: "Đổi giờ" }));
  fireEvent.change(screen.getByLabelText("Ngày"), { target: { value: "2026-10-03" } });
  fireEvent.change(screen.getByLabelText("Giờ"), { target: { value: "7" } });
  fireEvent.change(screen.getByLabelText("Phút"), { target: { value: "45" } });
  fireEvent.change(screen.getByLabelText("Giây"), { target: { value: "30" } });
  fireEvent.click(screen.getByRole("button", { name: "Áp dụng" }));
}

test("shows the server's demo time instead of the browser clock", async () => {
  render(<App />);

  expect(await screen.findByText(/^18:00:/)).toBeInTheDocument();
  expect(screen.getByText("Giờ demo")).toBeInTheDocument();
});

test("applying a time sends it to the backend and shows the new moment", async () => {
  render(<App />);
  await changeTime();

  await waitFor(() =>
    expect(mockedApi.setDemoClock).toHaveBeenCalledWith("2026-10-03T07:45:30+07:00"),
  );
  expect(await screen.findByText(/^07:45:/)).toBeInTheDocument();
});

test("moving the demo time makes the earlier search stale and re-reads the data", async () => {
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Tìm đường đi" }));
  await waitFor(() => expect(mockedApi.searchRoute).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(screen.getByLabelText("mock map")).toHaveAttribute("data-route", "ROUTE_TEST"));
  const statusCalls = mockedApi.stationStatus.mock.calls.length;

  await changeTime();

  // The route of the old moment is gone and the list asks for a new search.
  await waitFor(() =>
    expect(screen.getByText("Nhập thông tin để xem trạm sạc phù hợp.")).toBeInTheDocument(),
  );
  expect(screen.getByLabelText("mock map")).toHaveAttribute("data-route", "");
  // Status and colours are read again for the new moment.
  await waitFor(() => expect(mockedApi.stationStatus.mock.calls.length).toBeGreaterThan(statusCalls));
});

test("moving the demo time reloads the forecast of the selected station", async () => {
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "marker" }));
  await waitFor(() => expect(mockedApi.stationForecast).toHaveBeenCalledTimes(1));

  await changeTime();

  await waitFor(() => expect(mockedApi.stationForecast).toHaveBeenCalledTimes(2));
});

test("a failed change keeps the previous time and reports the error", async () => {
  mockedApi.setDemoClock.mockRejectedValueOnce(new Error("the demo clock is read-only"));
  render(<App />);
  await changeTime();

  expect(await screen.findByText("the demo clock is read-only")).toBeInTheDocument();
  expect(screen.getByText(/^18:00:/)).toBeInTheDocument();
});

test("going back to real time calls the reset endpoint", async () => {
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Đổi giờ" }));
  fireEvent.click(screen.getByRole("button", { name: "Về giờ thật" }));

  await waitFor(() => expect(mockedApi.resetDemoClock).toHaveBeenCalledTimes(1));
  expect(await screen.findByText("Giờ thật")).toBeInTheDocument();
});

test("keeps planner state when switching to driver and back", async () => {
  render(<App />);

  fireEvent.click(await screen.findByRole("button", { name: "Planner" }));
  expect(await screen.findByText("Planner local state: 0")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Change planner state" }));
  expect(screen.getByText("Planner local state: 1")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Return to driver" }));
  expect(await screen.findByRole("button", { name: "Tìm đường đi" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Planner" }));

  expect(await screen.findByText("Planner local state: 1")).toBeInTheDocument();
});
