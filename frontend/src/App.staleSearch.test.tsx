import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import { api } from "./api";
import App from "./App";
import { demoClock, modelStatus, recommendation, station, status, vehicle } from "./test/fixtures";
import type { Station, StationForecast } from "./types";

vi.mock("./planning/PlannerView", () => ({ default: () => null }));
vi.mock("./planning/gap/GapView", () => ({ default: () => null }));

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

// The real map needs WebGL; expose one button per station so tests can "click a marker".
vi.mock("./components/MapView", () => ({
  default: ({
    stations,
    route,
    onStationSelect,
  }: {
    stations: Station[];
    route: { route_id: string } | null;
    onStationSelect: (id: string) => void;
  }) => (
    <div aria-label="mock map" data-route={route?.route_id ?? ""}>
      {stations.map((item) => (
        <button key={item.properties.station_id} type="button" onClick={() => onStationSelect(item.properties.station_id)}>
          {`marker ${item.properties.station_id}`}
        </button>
      ))}
    </div>
  ),
}));

const mockedApi = vi.mocked(api);

const OTHER_ID = "ST_NOT_RECOMMENDED";
const otherStation: Station = {
  ...station,
  properties: { ...station.properties, station_id: OTHER_ID, name: "Trạm không được đề xuất" },
};

const forecastFor = (stationId: string): StationForecast => ({
  station_id: stationId,
  total_ports: 2,
  operational_ports: 2,
  generated_at: "2026-09-25T18:00:00+07:00",
  points: [0, 5, 10, 15, 20, 25, 30].map((offset) => ({
    offset_min: offset,
    available_ports: 1,
    prediction_source: "default",
    flags: ["ML_DEFAULT_VALUE"],
  })),
});

const panel = () => screen.getByRole("complementary", { name: "Chi tiết trạm" });
const times = () => within(panel()).queryByLabelText("Thời gian tại trạm");
const marker = (id: string) => screen.getByRole("button", { name: `marker ${id}` });

async function runRouteSearch() {
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Tìm đường đi" }));
  // The recommended station is auto-selected and shows its times.
  await waitFor(() => expect(times()).not.toBeNull());
}

beforeEach(() => {
  mockedApi.stations.mockResolvedValue([station, otherStation]);
  mockedApi.stationStatus.mockImplementation(async (id: string) => ({ ...status, station_id: id }));
  mockedApi.stationColors.mockResolvedValue({
    [station.properties.station_id]: "green",
    [OTHER_ID]: "green",
  });
  mockedApi.stationForecast.mockImplementation(async (id: string) => forecastFor(id));
  mockedApi.vehicles.mockResolvedValue([vehicle]);
  mockedApi.modelStatus.mockResolvedValue(modelStatus);
  mockedApi.demoClock.mockResolvedValue(demoClock);
  mockedApi.searchRoute.mockResolvedValue(recommendation);
  mockedApi.geocodeSuggestions.mockResolvedValue([]);
});

test("a recommended station shows arrival, wait, charge and the leg to the destination", async () => {
  await runRouteSearch();

  const section = times()!;
  expect(section).toHaveTextContent("Đến trạm");
  expect(section).toHaveTextContent("Chờ");
  expect(section).toHaveTextContent("Sạc");
  expect(section).toHaveTextContent("Tới điểm đến");
  expect(section).toHaveTextContent("16 phút");
});

test("a station the search did not recommend shows the forecast only, with no time estimate", async () => {
  await runRouteSearch();

  fireEvent.click(marker(OTHER_ID));

  await waitFor(() => expect(within(panel()).getByText("Trạm không được đề xuất")).toBeInTheDocument());
  expect(times()).toBeNull();
  expect(
    within(panel()).getByText("Trạm này không được đề xuất cho lần tìm kiếm hiện tại."),
  ).toBeInTheDocument();
  expect(panel().querySelector(".chart-arrival")).toBeNull();
  expect(within(panel()).queryByText(/khi bạn đến/)).not.toBeInTheDocument();
  // The previous station's route must not stay drawn for this one: back to the direct route.
  expect(screen.getByLabelText("mock map")).toHaveAttribute("data-route", "ROUTE_DIRECT");
  // Forecast bars are still there.
  expect(await within(panel()).findByRole("img", { name: /Số cổng trống dự báo/ })).toBeInTheDocument();

  fireEvent.click(marker(station.properties.station_id));
  await waitFor(() => expect(times()).not.toBeNull());
});

test("changing the battery level discards the previous search's times", async () => {
  await runRouteSearch();

  fireEvent.change(screen.getByRole("slider", { name: "Phần trăm pin còn lại" }), {
    target: { value: "20" },
  });
  fireEvent.click(marker(station.properties.station_id));

  await waitFor(() => expect(within(panel()).getByText(/Tìm trạm theo hành trình/)).toBeInTheDocument());
  expect(times()).toBeNull();
  // The stale list is gone too.
  expect(screen.getByText("Nhập thông tin để xem trạm sạc phù hợp.")).toBeInTheDocument();
});

test("route results do not leak into the station-search mode", async () => {
  await runRouteSearch();

  fireEvent.click(screen.getByRole("tab", { name: "Tìm trạm" }));
  fireEvent.click(marker(station.properties.station_id));

  await waitFor(() => expect(within(panel()).getByText("VinFast – La Vela Saigon Hotel")).toBeInTheDocument());
  expect(times()).toBeNull();

  // Back in route mode with the same inputs, the earlier result is valid again — but only then.
  fireEvent.click(screen.getByRole("tab", { name: "Tìm đường" }));
  expect(screen.queryByRole("complementary", { name: "Chi tiết trạm" })).not.toBeInTheDocument();
});

test("clicking a station excluded for insufficient battery shows the red 'not enough charge' message", async () => {
  mockedApi.searchRoute.mockResolvedValue({
    ...recommendation,
    excluded_candidates: [{ station_id: OTHER_ID, reason_codes: ["INSUFFICIENT_SOC_RESERVE"] }],
  });
  await runRouteSearch();

  fireEvent.click(marker(OTHER_ID));

  const message = await within(panel()).findByText("Không đủ điện để đến trạm này.");
  expect(message).toHaveClass("detail-hint", "detail-hint-error");
  expect(times()).toBeNull();

  // A recommended station keeps its normal summary.
  fireEvent.click(marker(station.properties.station_id));
  await waitFor(() => expect(times()).not.toBeNull());
  expect(within(panel()).queryByText("Không đủ điện để đến trạm này.")).not.toBeInTheDocument();
});

test("the need-charge case does not show the optional-stop button", async () => {
  await runRouteSearch();

  expect(screen.queryByRole("button", { name: "Ghé một trạm sạc dọc đường" })).not.toBeInTheDocument();
});

test("in the need-charge case the notice is plain text, not a go-straight choice", async () => {
  mockedApi.searchRoute.mockResolvedValueOnce({
    ...recommendation,
    case: "fallback" as const,
    recommendations: [],
    nearest_station_name: "Trạm gần nhất",
    missing_km: 5,
  });
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Tìm đường đi" }));

  await screen.findByText(/Pin không đủ tới trạm nào/);
  expect(screen.queryByRole("button", { name: /Pin không đủ/ })).not.toBeInTheDocument();
});
