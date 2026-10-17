import type { ReactNode } from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { route, station } from "../test/fixtures";

const STATION_SOURCE = "station-markers";
const STATION_DOT_LAYER = "station-markers-dot";

const goong = vi.hoisted(() => {
  const instances: FakeMap[] = [];
  const markers: FakeMarker[] = [];

  class FakeSource {
    data: unknown;
    setData = vi.fn((data: unknown) => {
      this.data = data;
    });
    constructor(data: unknown) {
      this.data = data;
    }
  }

  class FakeMap {
    handlers: Record<string, () => void> = {};
    remove = vi.fn();
    flyTo = vi.fn();
    addControl = vi.fn();
    sources: Record<string, FakeSource> = {};
    layers = new Set<string>();
    addSource = vi.fn((id: string, source: { data: unknown }) => {
      this.sources[id] = new FakeSource(source.data);
    });
    getSource = vi.fn((id: string) => this.sources[id]);
    addLayer = vi.fn((layer: { id: string }) => {
      this.layers.add(layer.id);
    });
    getLayer = vi.fn((id: string) => (this.layers.has(id) ? {} : undefined));
    removeLayer = vi.fn((id: string) => {
      this.layers.delete(id);
    });
    removeSource = vi.fn((id: string) => {
      delete this.sources[id];
    });
    getStyle = vi.fn(() => ({ layers: [] }));
    setLayoutProperty = vi.fn();
    hasImage = vi.fn(() => false);
    addImage = vi.fn();
    canvas = document.createElement("canvas");
    getCanvas = vi.fn(() => this.canvas);
    clickHandlers: Array<(event: unknown) => void> = [];
    // goong-js's `on`/`off` are overloaded: a plain handler for map-wide events,
    // or a layer id + handler for events scoped to one layer (symbol/circle click & hover).
    layerHandlers: Record<string, Record<string, Array<(event?: unknown) => void>>> = {};
    on = vi.fn(
      (
        event: string,
        layerIdOrHandler: string | ((event?: unknown) => void),
        layerHandler?: (event?: unknown) => void,
      ) => {
        if (typeof layerIdOrHandler === "function") {
          if (event === "click") this.clickHandlers.push(layerIdOrHandler);
          else this.handlers[event] = layerIdOrHandler as () => void;
          return;
        }
        const perEvent = (this.layerHandlers[layerIdOrHandler] ??= {});
        (perEvent[event] ??= []).push(layerHandler as (event?: unknown) => void);
      },
    );
    off = vi.fn(
      (
        event: string,
        layerIdOrHandler: string | ((event?: unknown) => void),
        layerHandler?: (event?: unknown) => void,
      ) => {
        if (typeof layerIdOrHandler === "function") {
          this.clickHandlers = this.clickHandlers.filter((item) => item !== layerIdOrHandler);
          return;
        }
        const list = this.layerHandlers[layerIdOrHandler]?.[event];
        if (list && layerHandler) {
          this.layerHandlers[layerIdOrHandler][event] = list.filter((item) => item !== layerHandler);
        }
      },
    );
    fireLayerEvent(layerId: string, event: string, payload?: unknown) {
      this.layerHandlers[layerId]?.[event]?.forEach((handler) => handler(payload));
    }
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

interface StationFeature {
  properties: { stationId: string; color: string; selected: boolean; hovered: boolean };
}

function stationFeatures(map: InstanceType<typeof goong.FakeMap>): StationFeature[] {
  const source = map.getSource(STATION_SOURCE) as unknown as { data: { features: StationFeature[] } } | undefined;
  return source?.data.features ?? [];
}

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

test("keeps the Goong station layer in sync with hover and selection changes", async () => {
  vi.stubEnv("VITE_GOONG_MAPTILES_KEY", "test-key");
  const stationId = station.properties.station_id;
  // Data props keep their identity across renders, as they do in App; only callbacks are fresh.
  const stations = [station];
  const colors = {};
  const view = (selectedStationId: string | null, hoveredStationId: string | null) => (
    <MapView
      stations={stations}
      colors={colors}
      route={null}
      selectedStationId={selectedStationId}
      hoveredStationId={hoveredStationId}
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
  await waitFor(() => expect(stationFeatures(map)).toHaveLength(1));
  expect(stationFeatures(map)[0].properties.stationId).toBe(stationId);
  expect(stationFeatures(map)[0].properties.selected).toBe(false);
  expect(stationFeatures(map)[0].properties.hovered).toBe(false);

  rerender(view(null, stationId));
  expect(stationFeatures(map)[0].properties.hovered).toBe(true);
  rerender(view(null, null));
  expect(stationFeatures(map)[0].properties.hovered).toBe(false);

  rerender(view(stationId, null));
  expect(stationFeatures(map)[0].properties.selected).toBe(true);
  expect(map.flyTo).toHaveBeenCalledTimes(1);

  // The GL layer is created once; later updates go through setData, not addLayer again.
  expect(map.addLayer).toHaveBeenCalledTimes(2);
  expect(goong.instances).toHaveLength(1);
  expect(map.remove).not.toHaveBeenCalled();
});

test("colours each Goong station feature with the backend colour and falls back to grey", async () => {
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
  const map = goong.instances[0];
  act(() => map.handlers.load());
  await waitFor(() => expect(stationFeatures(map)).toHaveLength(2));

  expect(stationFeatures(map)[0].properties.color).toBe("yellow");
  expect(stationFeatures(map)[1].properties.color).toBe("grey");
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
  await waitFor(() => expect(stationFeatures(map)).toHaveLength(1));
  expect(map.addSource).not.toHaveBeenCalledWith("journey-route", expect.anything());

  rerender(<MapView {...props} route={route} />);
  expect(map.addSource).toHaveBeenCalledWith("journey-route", expect.anything());
  // Below the station markers, so the line never covers them.
  expect(map.addLayer).toHaveBeenCalledWith(
    expect.objectContaining({ id: "journey-route-line" }),
    STATION_DOT_LAYER,
  );
  expect(goong.instances).toHaveLength(1);
});

test("shows origin and destination markers and leaves the station layer untouched when they move", async () => {
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
  const map = goong.instances[0];
  act(() => map.handlers.load());
  await waitFor(() => expect(goong.markers).toHaveLength(2));
  const classes = goong.markers.map((marker) => marker.element.className);
  expect(classes).toContain("origin-marker");
  expect(classes).toContain("destination-marker");
  const addLayerCallsBeforeMove = map.addLayer.mock.calls.length;

  rerender(<MapView {...base} origin={{ lat: 10.71, lon: 106.71 }} destination={{ lat: 10.8, lon: 106.68 }} />);
  // Both endpoint markers are recreated; the station GL layer (a different effect) is untouched.
  expect(goong.markers).toHaveLength(4);
  expect(map.addLayer.mock.calls.length).toBe(addLayerCallsBeforeMove);
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
  await waitFor(() => expect(stationFeatures(map)).toHaveLength(1));
  expect(map.clickHandlers).toHaveLength(0);

  const clickStation = () =>
    act(() =>
      map.fireLayerEvent(STATION_DOT_LAYER, "click", {
        features: [{ properties: { stationId: station.properties.station_id } }],
      }),
    );

  // Not picking: a station click selects the station.
  clickStation();
  expect(onStationSelect).toHaveBeenCalledTimes(1);

  rerender(<MapView {...base} pickTarget="origin" />);
  expect(map.canvas.style.cursor).toBe("crosshair");
  expect(map.clickHandlers).toHaveLength(1);
  act(() => map.clickHandlers[0]({ lngLat: { lat: 10.75, lng: 106.69 } }));
  expect(onMapPick).toHaveBeenCalledWith({ lat: 10.75, lon: 106.69 });

  // Picking: the same station click no longer selects a station.
  clickStation();
  expect(onStationSelect).toHaveBeenCalledTimes(1);

  rerender(<MapView {...base} pickTarget={null} />);
  expect(map.clickHandlers).toHaveLength(0);
  expect(map.canvas.style.cursor).toBe("");
  expect(goong.instances).toHaveLength(1);
});
