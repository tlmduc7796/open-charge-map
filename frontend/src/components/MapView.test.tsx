import type { ReactNode } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

const goong = vi.hoisted(() => {
  const handlers: Record<string, (event?: unknown) => void> = {};
  const map = {
    on: vi.fn((event: string, handler: (event?: unknown) => void) => {
      handlers[event] = handler;
    }),
    addControl: vi.fn(),
    addSource: vi.fn(),
    addLayer: vi.fn(),
    getSource: vi.fn(() => undefined),
    getLayer: vi.fn(() => undefined),
    getBounds: vi.fn(() => ({
      getWest: () => 106.6,
      getSouth: () => 10.6,
      getEast: () => 106.8,
      getNorth: () => 10.9,
    })),
    removeLayer: vi.fn(),
    removeSource: vi.fn(),
    remove: vi.fn(),
  };
  return {
    handlers,
    map,
    accessToken: "",
    supported: vi.fn(() => true),
    Map: vi.fn(function MapMock() {
      return map;
    }),
    Marker: vi.fn(),
    NavigationControl: vi.fn(function NavigationControlMock() {
      return {};
    }),
  };
});

vi.mock("@goongmaps/goong-js", () => ({
  default: goong,
}));

vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }: { children: ReactNode }) => (
    <div data-testid="osm-map">{children}</div>
  ),
  TileLayer: () => <div data-testid="osm-tiles" />,
  CircleMarker: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Polyline: () => <div />,
  Popup: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  useMap: () => ({
    getBounds: () => ({
      getWest: () => 106.6,
      getSouth: () => 10.6,
      getEast: () => 106.8,
      getNorth: () => 10.9,
    }),
  }),
  useMapEvents: () => null,
}));

import MapView from "./MapView";

beforeEach(() => vi.stubEnv("VITE_GOONG_MAPTILES_KEY", ""));
afterEach(() => vi.unstubAllEnvs());

beforeEach(() => {
  goong.Map.mockClear();
  goong.map.on.mockClear();
  goong.map.remove.mockClear();
  for (const key of Object.keys(goong.handlers)) delete goong.handlers[key];
});

test("uses Leaflet and OSM when the Goong map key is unavailable", async () => {
  const onProviderChange = vi.fn();
  const onViewportChange = vi.fn();
  render(
    <MapView
      stations={[]}
      statuses={{}}
      route={null}
      selectedStationId={null}
      onStationSelect={vi.fn()}
      onProviderChange={onProviderChange}
      onViewportChange={onViewportChange}
    />,
  );

  expect(screen.getByTestId("osm-map")).toBeInTheDocument();
  expect(screen.getByTestId("osm-tiles")).toBeInTheDocument();
  await waitFor(() => expect(onProviderChange).toHaveBeenCalledWith("osm"));
  expect(onViewportChange).toHaveBeenCalledWith({
    west: 106.6,
    south: 10.6,
    east: 106.8,
    north: 10.9,
  });
});

test("loads the Goong SDK and reports the viewport in release map mode", async () => {
  vi.stubEnv("VITE_GOONG_MAPTILES_KEY", "release-map-token");
  const onProviderChange = vi.fn();
  const onViewportChange = vi.fn();
  const view = render(
    <MapView
      stations={[]}
      statuses={{}}
      route={null}
      selectedStationId={null}
      onStationSelect={vi.fn()}
      onProviderChange={onProviderChange}
      onViewportChange={onViewportChange}
    />,
  );

  await waitFor(() => expect(goong.Map).toHaveBeenCalledOnce());
  expect(goong.supported).toHaveBeenCalledOnce();
  expect(goong.accessToken).toBe("release-map-token");
  expect(onProviderChange).toHaveBeenCalledWith("goong");
  expect(goong.map.addControl).toHaveBeenCalledOnce();

  goong.handlers.load?.();
  expect(onViewportChange).toHaveBeenCalledWith({
    west: 106.6,
    south: 10.6,
    east: 106.8,
    north: 10.9,
  });

  view.unmount();
  expect(goong.map.remove).toHaveBeenCalledOnce();
});

test("falls back to OSM when the configured Goong map fails before loading", async () => {
  vi.stubEnv("VITE_GOONG_MAPTILES_KEY", "release-map-token");
  const onProviderChange = vi.fn();
  const view = render(
    <MapView
      stations={[]}
      statuses={{}}
      route={null}
      selectedStationId={null}
      onStationSelect={vi.fn()}
      onProviderChange={onProviderChange}
      onViewportChange={vi.fn()}
    />,
  );

  await waitFor(() => expect(goong.Map).toHaveBeenCalledOnce());
  goong.handlers.error?.();

  expect(await screen.findByTestId("osm-map")).toBeInTheDocument();
  await waitFor(() => expect(onProviderChange).toHaveBeenCalledWith("osm"));
  expect(goong.map.remove).toHaveBeenCalledOnce();
  view.unmount();
});
