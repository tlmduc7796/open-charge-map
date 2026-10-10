import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { recommendationItem, station, status } from "../test/fixtures";
import StationDetails from "./StationDetails";

test("shows access, connector, live state and prediction without cost", () => {
  render(
    <StationDetails
      demoMode
      station={station}
      status={status}
      forecast={null}
      forecastUnavailable={false}
      recommendation={recommendationItem}
      activeArrival={null}
      committing={false}
      onCommit={() => undefined}
      onCancel={() => undefined}
      journeyId={null}
      journeyAccessToken={null}
      onReportIncident={async () => undefined}
    />,
  );

  expect(screen.getByText("public")).toBeInTheDocument();
  expect(screen.getByText(/CCS2 160 kW/)).toBeInTheDocument();
  expect(screen.getByText("1/1")).toBeInTheDocument();
  expect(screen.getAllByText("0").length).toBeGreaterThanOrEqual(2);
  expect(screen.getByText("0 xe")).toBeInTheDocument();
  expect(screen.getByText("Occupancy dự báo +15 phút")).toBeInTheDocument();
  expect(screen.getByText("Chờ dự kiến khi tới")).toBeInTheDocument();
  expect(screen.queryByText(/cost|giá điện/i)).not.toBeInTheDocument();
});

test("hides operational counts when the station snapshot is synthetic or stale", () => {
  render(
    <StationDetails
      demoMode={false}
      station={station}
      status={{ ...status, data_source: "synthetic", is_stale: true }}
      forecast={null}
      forecastUnavailable={false}
      recommendation={null}
      activeArrival={null}
      committing={false}
      onCommit={() => undefined}
      onCancel={() => undefined}
      journeyId={null}
      journeyAccessToken={null}
      onReportIncident={async () => undefined}
    />,
  );

  expect(screen.getByText(/Dữ liệu đã cũ/)).toBeInTheDocument();
  expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(5);
  expect(screen.queryByText("2/4")).not.toBeInTheDocument();
});

test("renders observed history and preserves unknown occupancy as unknown", () => {
  render(
    <StationDetails
      demoMode
      station={station}
      status={status}
      forecast={null}
      forecastUnavailable={false}
      history={[
        {
          station_id: station.properties.station_id,
          bucket_at: "2026-10-09T10:00:00Z",
          total_ports: 4,
          operational_ports: 4,
          occupied_ports: 2,
          occupancy_ratio: 0.5,
          queue_length: null,
          data_source: "observed",
        },
        {
          station_id: station.properties.station_id,
          bucket_at: "2026-10-09T10:05:00Z",
          total_ports: 4,
          operational_ports: 0,
          occupied_ports: 0,
          occupancy_ratio: null,
          queue_length: null,
          data_source: "observed",
        },
      ]}
      recommendation={null}
      activeArrival={null}
      committing={false}
      onCommit={() => undefined}
      onCancel={() => undefined}
      journeyId={null}
      journeyAccessToken={null}
      onReportIncident={async () => undefined}
    />,
  );

  const history = screen.getByRole("img", { name: "2 bản ghi quan sát" });
  expect(history.querySelectorAll("span")).toHaveLength(2);
  expect(history.querySelector("span.unknown")).toBeInTheDocument();
  expect(screen.getByText("2 bucket 5 phút · dữ liệu observed")).toBeInTheDocument();
});
