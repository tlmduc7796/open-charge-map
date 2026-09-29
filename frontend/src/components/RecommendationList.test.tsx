import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { recommendationItem, station, vehicle } from "../test/fixtures";
import RecommendationList from "./RecommendationList";

test("renders recommendation metrics and selection", () => {
  const onSelect = vi.fn();
  render(
    <RecommendationList
      items={[recommendationItem]}
      exclusions={[]}
      stations={[station]}
      vehicle={vehicle}
      selectedStationId={null}
      hasRun
      onSelect={onSelect}
    />,
  );

  expect(screen.getByText(station.properties.name)).toBeInTheDocument();
  expect(screen.getByText("14 phút")).toBeInTheDocument();
  expect(screen.getByText("156 km")).toBeInTheDocument();
  expect(screen.queryByText(/cost|giá điện/i)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: new RegExp(station.properties.name) }));
  expect(onSelect).toHaveBeenCalledWith(recommendationItem);
});

test("renders empty and exclusion states", () => {
  render(
    <RecommendationList
      items={[]}
      exclusions={[{ station_id: station.properties.station_id, reason_codes: ["INSUFFICIENT_SOC_RESERVE"] }]}
      stations={[station]}
      vehicle={vehicle}
      selectedStationId={null}
      hasRun
      onSelect={vi.fn()}
    />,
  );

  expect(screen.getByText(/Không có trạm tương thích/i)).toBeInTheDocument();
  fireEvent.click(screen.getByText(/1 trạm đã bị loại/i));
  expect(screen.getByText("Phương tiện không đủ pin để tới")).toBeInTheDocument();
});
