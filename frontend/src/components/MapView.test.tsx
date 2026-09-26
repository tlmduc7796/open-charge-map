import type { ReactNode } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

vi.mock("@goongmaps/goong-js", () => ({
  default: { supported: () => true },
}));

vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }: { children: ReactNode }) => (
    <div data-testid="osm-map">{children}</div>
  ),
  TileLayer: () => <div data-testid="osm-tiles" />,
  CircleMarker: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Polyline: () => <div />,
  Popup: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

import MapView from "./MapView";

beforeEach(() => vi.stubEnv("VITE_GOONG_MAPTILES_KEY", ""));
afterEach(() => vi.unstubAllEnvs());

test("uses Leaflet and OSM when the Goong map key is unavailable", async () => {
  const onProviderChange = vi.fn();
  render(
    <MapView
      stations={[]}
      statuses={{}}
      route={null}
      selectedStationId={null}
      onStationSelect={vi.fn()}
      onProviderChange={onProviderChange}
    />,
  );

  expect(screen.getByTestId("osm-map")).toBeInTheDocument();
  expect(screen.getByTestId("osm-tiles")).toBeInTheDocument();
  await waitFor(() => expect(onProviderChange).toHaveBeenCalledWith("osm"));
});
