import type { ReactNode } from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import type { RecommendationItem } from "../types";
import { route, station } from "../test/fixtures";

const goong = vi.hoisted(() => {
  const instances: FakeMap[] = [];
  const markers: FakeMarker[] = [];

  class FakeMap {
    handlers: Record<string, () => void> = {};
    remove = vi.fn();
    flyTo = vi.fn();
    addControl = vi.fn();
    addSource = vi.fn();
    addLayer = vi.fn();
    getSource = vi.fn(() => undefined);
    getLayer = vi.fn(() => undefined);
    removeLayer = vi.fn();
    removeSource = vi.fn();
    canvas = document.createElement("canvas");
    getCanvas = vi.fn(() => this.canvas);
    clickHandlers: Array<(event: unknown) => void> = [];
    on = vi.fn((event: string, handler: (event?: unknown) => void) => {
      if (event === "click") this.clickHandlers.push(handler);
      else this.handlers[event] = handler as () => void;
    });
    off = vi.fn((event: string, handler: (event?: unknown) => void) => {
      if (event === "click") this.clickHandlers = this.clickHandlers.filter((item) => item !== handler);
    });
    constructor() {
      instances.push(this);
    }
  }

  class FakeMarker {
    remove = vi.fn();
    constructor(public element: HTMLElement) {
      markers.push(this);
    }
    setLngLat() {
      return this;
    }
    addTo() {
      return this;
    }
  }

  return { instances, markers, FakeMap, FakeMarker };
});

vi.mock("@goongmaps/goong-js", () => ({
  default: {
    supported: () => true,
    accessToken: "",
    Map: goong.FakeMap,
    Marker: goong.FakeMarker,
    NavigationControl: class {},
  },
}));

vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }: { children: ReactNode }) => (
    <div data-testid="osm-map">{children}</div>
  ),
  TileLayer: () => <div data-testid="osm-tiles" />,
  CircleMarker: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Polyline: () => <div />,
  Popup: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  useMap: () => ({ fitBounds: vi.fn(), flyTo: vi.fn() }),
  useMapEvents: () => ({ getContainer: () => document.createElement("div") }),
}));

import MapView from "./MapView";

beforeEach(() => {
  vi.stubEnv("VITE_GOONG_MAPTILES_KEY", "");
  goong.instances.length = 0;
  goong.markers.length = 0;
});
afterEach(() => vi.unstubAllEnvs());

test("uses Leaflet and OSM when the Goong map key is unavailable", async () => {
  const onProviderChange = vi.fn();
  render(
    <MapView
      stations={[]}
      colors={{}}
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

test("keeps the Goong map instance on hover and selection changes", async () => {
  vi.stubEnv("VITE_GOONG_MAPTILES_KEY", "test-key");
  const stationId = station.properties.station_id;
  // Data props keep their identity across renders, as they do in App; only callbacks are fresh.
  const stations = [station];
  const colors = {};
  const items: RecommendationItem[] = [];
  const view = (selectedStationId: string | null, hoveredStationId: string | null) => (
    <MapView
      stations={stations}
      colors={colors}
      route={null}
      selectedStationId={selectedStationId}
      hoveredStationId={hoveredStationId}
      items={items}
      // Fresh callbacks on every render, like an inline handler in the parent.
      onStationSelect={() => undefined}
      onStationHover={() => undefined}
      onProviderChange={() => undefined}
    />
  );

  const { rerender } = render(view(null, null));
  expect(goong.instances).toHaveLength(1);
  const map = goong.instances[0];

  act(() => map.handlers.load());
  await waitFor(() => expect(goong.markers).toHaveLength(1));
  const stationMarker = goong.markers[0].element;
  expect(stationMarker.dataset.stationId).toBe(stationId);

  rerender(view(null, stationId));
  expect(stationMarker).toHaveClass("map-marker--hovered");
  rerender(view(null, null));
  expect(stationMarker).not.toHaveClass("map-marker--hovered");

  rerender(view(stationId, null));
  expect(stationMarker).toHaveClass("map-marker--selected");
  expect(map.flyTo).toHaveBeenCalledTimes(1);

  expect(goong.instances).toHaveLength(1);
  expect(goong.markers).toHaveLength(1);
  expect(map.remove).not.toHaveBeenCalled();
});

test("colours each Goong marker with the backend colour and falls back to grey", async () => {
  vi.stubEnv("VITE_GOONG_MAPTILES_KEY", "test-key");
  const stations = [station, { ...station, properties: { ...station.properties, station_id: "ST_OTHER" } }];
  render(
    <MapView
      stations={stations}
      colors={{ [station.properties.station_id]: "yellow" }}
      route={null}
      selectedStationId={null}
      onStationSelect={() => undefined}
      onProviderChange={() => undefined}
    />,
  );
  act(() => goong.instances[0].handlers.load());
  await waitFor(() => expect(goong.markers).toHaveLength(2));

  expect(goong.markers[0].element).toHaveClass("map-marker--yellow");
  expect(goong.markers[1].element).toHaveClass("map-marker--grey");
});

test("draws the route on the existing Goong map", async () => {
  vi.stubEnv("VITE_GOONG_MAPTILES_KEY", "test-key");
  const props = {
    stations: [station],
    colors: {},
    selectedStationId: null,
    onStationSelect: () => undefined,
    onProviderChange: () => undefined,
  };
  const { rerender } = render(<MapView {...props} route={null} />);
  const map = goong.instances[0];
  act(() => map.handlers.load());
  await waitFor(() => expect(goong.markers).toHaveLength(1));
  expect(map.addSource).not.toHaveBeenCalled();

  rerender(<MapView {...props} route={route} />);
  expect(map.addSource).toHaveBeenCalledWith("journey-route", expect.anything());
  expect(map.addLayer).toHaveBeenCalledTimes(1);
  expect(goong.instances).toHaveLength(1);
});

test("shows origin and destination markers without rebuilding station markers when they move", async () => {
  vi.stubEnv("VITE_GOONG_MAPTILES_KEY", "test-key");
  const stations = [station];
  const colors = {};
  const base = {
    stations,
    colors,
    route: null,
    selectedStationId: null,
    onStationSelect: () => undefined,
    onProviderChange: () => undefined,
  };
  const { rerender } = render(
    <MapView {...base} origin={{ lat: 10.7, lon: 106.7 }} destination={{ lat: 10.8, lon: 106.68 }} />,
  );
  act(() => goong.instances[0].handlers.load());
  await waitFor(() => expect(goong.markers).toHaveLength(3));
  const classes = goong.markers.map((marker) => marker.element.className);
  expect(classes).toContain("origin-marker");
  expect(classes).toContain("destination-marker");

  rerender(<MapView {...base} origin={{ lat: 10.71, lon: 106.71 }} destination={{ lat: 10.8, lon: 106.68 }} />);
  // Both endpoint markers are recreated; the station marker keeps its element.
  expect(goong.markers).toHaveLength(5);
  expect(goong.markers[0].remove).not.toHaveBeenCalled();
  expect(goong.instances).toHaveLength(1);
});

test("draws no destination marker when none is provided", async () => {
  vi.stubEnv("VITE_GOONG_MAPTILES_KEY", "test-key");
  render(
    <MapView
      stations={[]}
      colors={{}}
      route={null}
      selectedStationId={null}
      origin={{ lat: 10.7, lon: 106.7 }}
      onStationSelect={() => undefined}
      onProviderChange={() => undefined}
    />,
  );
  act(() => goong.instances[0].handlers.load());
  await waitFor(() => expect(goong.markers).toHaveLength(1));
  expect(goong.markers[0].element.className).toBe("origin-marker");
});

test("pick mode turns map clicks into picked points and ignores station clicks", async () => {
  vi.stubEnv("VITE_GOONG_MAPTILES_KEY", "test-key");
  const onMapPick = vi.fn();
  const onStationSelect = vi.fn();
  const stations = [station];
  const colors = {};
  const base = {
    stations,
    colors,
    route: null,
    selectedStationId: null,
    onStationSelect,
    onMapPick,
    onProviderChange: () => undefined,
  };
  const { rerender } = render(<MapView {...base} pickTarget={null} />);
  const map = goong.instances[0];
  act(() => map.handlers.load());
  await waitFor(() => expect(goong.markers).toHaveLength(1));
  expect(map.clickHandlers).toHaveLength(0);

  // Not picking: a marker click selects the station.
  goong.markers[0].element.click();
  expect(onStationSelect).toHaveBeenCalledTimes(1);

  rerender(<MapView {...base} pickTarget="origin" />);
  expect(map.canvas.style.cursor).toBe("crosshair");
  expect(map.clickHandlers).toHaveLength(1);
  act(() => map.clickHandlers[0]({ lngLat: { lat: 10.75, lng: 106.69 } }));
  expect(onMapPick).toHaveBeenCalledWith({ lat: 10.75, lon: 106.69 });

  // Picking: the same marker click no longer selects a station.
  goong.markers[0].element.click();
  expect(onStationSelect).toHaveBeenCalledTimes(1);

  rerender(<MapView {...base} pickTarget={null} />);
  expect(map.clickHandlers).toHaveLength(0);
  expect(map.canvas.style.cursor).toBe("");
  expect(goong.instances).toHaveLength(1);
});
