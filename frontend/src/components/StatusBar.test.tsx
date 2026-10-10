import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import StatusBar from "./StatusBar";

test("reports when station status cannot be refreshed", () => {
  render(
    <StatusBar
      demoMode={false}
      model={null}
      mapProvider="osm"
      activeEvents={[]}
      statusFeedUnavailable
    />,
  );

  expect(screen.getByText(/Station status: unavailable/)).toBeInTheDocument();
  expect(screen.getByText(/last data marked stale/)).toBeInTheDocument();
});
