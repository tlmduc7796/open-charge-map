import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { recommendationItem, station, status } from "../test/fixtures";
import StationDetails from "./StationDetails";

test("shows access, connector, live state and prediction without cost", () => {
  const stationWithNotes = {
    ...station,
    properties: {
      ...station.properties,
      notes: ["EVCS inventory assumption that should not appear in the demo."],
    },
  };
  render(
    <StationDetails
      station={stationWithNotes}
      status={status}
      recommendation={recommendationItem}
    />,
  );

  expect(screen.getByText("public")).toBeInTheDocument();
  expect(screen.getByText(/CCS2 150 kW/)).toBeInTheDocument();
  expect(screen.getByText("Nguồn dự báo")).toBeInTheDocument();
  expect(screen.getByText("Thời gian chờ")).toBeInTheDocument();
  expect(screen.queryByText(/EVCS inventory assumption/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/cost|giá điện/i)).not.toBeInTheDocument();
});
