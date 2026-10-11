import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { station } from "../test/fixtures";
import RecommendationList from "./RecommendationList";

test("renders empty and exclusion states", () => {
  render(
    <RecommendationList
      items={[]}
      exclusions={[{ station_id: station.properties.station_id, reason_codes: ["INSUFFICIENT_SOC_RESERVE"] }]}
      stations={[station]}
      selectedStationId={null}
      hasRun
      onSelect={vi.fn()}
    />,
  );

  expect(screen.getByText(/Không có trạm tương thích/i)).toBeInTheDocument();
  fireEvent.click(screen.getByText(/1 trạm đã bị loại/i));
  expect(screen.getByText("Phương tiện không đủ pin để tới")).toBeInTheDocument();
});
