import type { ReactNode } from "react";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import type { GapCandidate, GapCellItem, GapCellResult, GapRoadItem, GapStationItem } from "./gapTypes";

const goong = vi.hoisted(() => {
  const instances: FakeMap[] = [];
  const markers: FakeMarker[] = [];
  const popups: FakePopup[] = [];

  class FakeMap {
    handlers: Record<string, () => void> = {};
    layerHandlers: Record<string, Record<string, (event: unknown) => void>> = {};
    sources: Record<string, { data: unknown }> = {};
    layers: { id: string; type: string; filter?: unknown }[] = [];
    remove = vi.fn();
    resize = vi.fn();
    addControl = vi.fn();
    fitBounds = vi.fn();
    canvas = document.createElement("canvas");
    getCanvas = () => this.canvas;
    getStyle = () => ({ layers: [] });
    setLayoutProperty = vi.fn();
    queryRenderedFeatures = vi.fn(() => [] as unknown[]);
    addSource = (id: string, source: { data: unknown }) => { this.sources[id] = { data: source.data }; };
    getSource = (id: string) => {
      const source = this.sources[id];
      return source ? { setData: (data: unknown) => { source.data = data; } } : undefined;
    };
    addLayer = (layer: { id: string; type: string; filter?: unknown }) => { this.layers.push(layer); };
    on = (event: string, layerOrHandler: string | (() => void), handler?: (event: unknown) => void) => {
      if (typeof layerOrHandler === "function") this.handlers[event] = layerOrHandler;
      else (this.layerHandlers[layerOrHandler] ??= {})[event] = handler as (event: unknown) => void;
    };
    off = vi.fn();
    constructor() { instances.push(this); }
  }

  class FakeMarker {
    lngLat: [number, number] | null = null;
    remove = vi.fn();
    constructor(public element: HTMLElement) { markers.push(this); }
    setLngLat(value: [number, number]) { this.lngLat = value; return this; }
    addTo() { return this; }
  }

  class FakePopup {
    html = "";
    constructor() { popups.push(this); }
    setLngLat() { return this; }
    setHTML(html: string) { this.html = html; return this; }
    addTo() { return this; }
    remove() {}
  }

  return { instances, markers, popups, FakeMap, FakeMarker, FakePopup };
});

vi.mock("@goongmaps/goong-js", () => ({
  default: {
    supported: () => true,
    accessToken: "",
    Map: goong.FakeMap,
    Marker: goong.FakeMarker,
    Popup: goong.FakePopup,
    NavigationControl: class {},
  },
}));

vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }: { children: ReactNode }) => <div data-testid="osm-map">{children}</div>,
  TileLayer: () => null,
  Polygon: ({ children }: { children: ReactNode }) => <div data-testid="osm-cell">{children}</div>,
  Polyline: ({ children, pathOptions }: { children: ReactNode; pathOptions: { color: string } }) => (
    <div data-testid="osm-road" data-color={pathOptions.color}>{children}</div>
  ),
  Tooltip: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  CircleMarker: ({ children }: { children: ReactNode }) => <div data-testid="osm-station">{children}</div>,
  Popup: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Marker: () => <div data-testid="osm-rank" />,
  useMap: () => ({ fitBounds: vi.fn() }),
}));

import GapMap from "./GapMap";

const cells: GapCellItem[] = ["A", "B"].map((id, index) => ({
  cell_id: id, unit_id: "u", unit_name: "Phường U", lat: 10.77 + index * 0.003, lon: 106.69,
  bounds: [10.769 + index * 0.003, 106.689, 10.771 + index * 0.003, 106.691] as [number, number, number, number],
  poi_count: 3, poi_weighted: 5, flow_vph: 500 + index * 500, rent_kvnd_m2_month: 200,
}));

function cellResult(id: string, gap: number, extra: Partial<GapCellResult> = {}): GapCellResult {
  return {
    cell_id: id, flow_norm: 0.5, poi_norm: 0.5, demand: 0.5, supply: 1, supply_own: 0.5,
    supply_competitor: 0.5, gap, rent_norm: 0.5, rent_missing: false, score: gap, d_own_m: 800,
    d_competitor_m: 600, own_overlap: false, excluded_reason: null, rank: 1, ...extra,
  };
}

const roads: GapRoadItem[] = [
  { road_id: "W00001", name: "Hẻm xanh", road_type: "residential", lanes: null, length_m: 100, flow_vph: 300, coordinates: [[10.77, 106.69], [10.771, 106.691]] },
  { road_id: "W00002", name: "Lý Tự Trọng", road_type: "primary", lanes: 4, length_m: 400, flow_vph: 4000, coordinates: [[10.77, 106.69], [10.772, 106.692]] },
  { road_id: "W00003", name: "Hàm Nghi", road_type: "secondary", lanes: null, length_m: 300, flow_vph: 2000, coordinates: [[10.77, 106.69], [10.771, 106.693]] },
];

const stations: GapStationItem[] = [{
  station_id: "OWN-01", operator_id: "OWN", operator_name: "Mạng của mình", relationship: "OWNED",
  unit_id: "u", unit_name: "Phường U", lat: 10.77, lon: 106.69, site_type: "mall",
  opening_hours: "24/7", port_count: 6, dc_port_count: 4, ac_port_count: 2, total_power_kw: 502,
  max_port_power_kw: 120,
  port_groups: [{ charger_type: "DC", connector_type: "CCS2", port_count: 4, power_kw_per_port: 120 }],
  data_status: "synthetic",
}];

const candidate: GapCandidate = {
  ...cellResult("A", 0.4), selection_order: 1, unit_id: "u", unit_name: "Phường U", lat: 10.77,
  lon: 106.69, flow_vph: 500, poi_count: 3, poi_weighted: 5, rent_kvnd_m2_month: 200,
  cluster_cell_ids: ["B"], cluster_size: 2,
  nearby: { radius_m: 800, cell_count: 3, flow_mean_vph: 500, flow_max_vph: 900, flow_max_roads: null, flow_percentile: 50, rent_mean_kvnd: 300, rent_min_kvnd: 250, rent_max_kvnd: 350, rent_percentile: 40 },
  nearest_own: null, nearest_competitor: null,
  top_supply_stations: [], stability: 1, stability_label: "stable", legal_status: "unknown",
  pending_legal_checks: [],
};

function props(overrides: Record<string, unknown> = {}) {
  return {
    cells, roads,
    results: new Map([["A", cellResult("A", 0.4)], ["B", cellResult("B", 0.1, { excluded_reason: "rent_above_limit", rank: null })]]),
    layer: "gap" as const, stations, showStations: true, candidates: [candidate],
    selectedCandidateId: "A", onSelectCandidate: vi.fn(), ...overrides,
  };
}

beforeEach(() => {
  goong.instances.length = 0;
  goong.markers.length = 0;
  goong.popups.length = 0;
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

test("falls back to OpenStreetMap when there is no Goong maptiles key", () => {
  vi.stubEnv("VITE_GOONG_MAPTILES_KEY", "");
  render(<GapMap {...props()} />);
  expect(screen.getByTestId("osm-map")).toBeTruthy();
  expect(screen.getAllByTestId("osm-cell")).toHaveLength(2);
  expect(screen.getAllByTestId("osm-station")).toHaveLength(1);
  expect(goong.instances).toHaveLength(0);
});

test("draws the grid, stations and numbered candidates on the Goong map", () => {
  vi.stubEnv("VITE_GOONG_MAPTILES_KEY", "test-key");
  const onSelect = vi.fn();
  render(<GapMap {...props({ onSelectCandidate: onSelect })} />);
  expect(screen.queryByTestId("osm-map")).toBeNull();
  const map = goong.instances[0];
  act(() => map.handlers.load());

  expect(map.layers.map((layer) => layer.id)).toEqual([
    "gap-cells-fill", "gap-cells-line", "gap-cells-own-line", "gap-cells-cluster-line",
    "gap-roads-casing", "gap-roads-line", "gap-roads-hit", "gap-stations-layer",
  ]);
  const cellData = map.sources["gap-cells"].data as { features: { properties: Record<string, unknown> }[] };
  expect(cellData.features).toHaveLength(2);
  const byId = Object.fromEntries(cellData.features.map((f) => [f.properties.cell_id, f.properties]));
  expect(byId.A.in_cluster).toBe(true);
  expect(byId.B.in_cluster).toBe(true);
  expect(byId.B.fill_color).toBe("#cbd5d1");
  expect(byId.A.fill_color).not.toBe("#cbd5d1");
  const stationData = map.sources["gap-stations"].data as { features: unknown[] };
  expect(stationData.features).toHaveLength(1);
  expect(goong.markers).toHaveLength(1);
  expect(goong.markers[0].element.textContent).toBe("1");
  expect(goong.markers[0].lngLat).toEqual([106.69, 10.77]);
  expect(map.fitBounds).toHaveBeenCalled();

  act(() => goong.markers[0].element.click());
  expect(onSelect).toHaveBeenCalledWith("A");
});

test("a click on a cell selects the candidate that owns its cluster, unless a station was hit", () => {
  vi.stubEnv("VITE_GOONG_MAPTILES_KEY", "test-key");
  const onSelect = vi.fn();
  render(<GapMap {...props({ onSelectCandidate: onSelect })} />);
  const map = goong.instances[0];
  act(() => map.handlers.load());

  const click = map.layerHandlers["gap-cells-fill"].click;
  act(() => click({ lngLat: { lat: 10.7, lng: 106.6 }, point: {}, features: [{ properties: { cell_id: "B" } }] }));
  expect(onSelect).toHaveBeenLastCalledWith("A");

  onSelect.mockClear();
  map.queryRenderedFeatures.mockReturnValueOnce([{}]);
  act(() => click({ lngLat: { lat: 10.7, lng: 106.6 }, point: {}, features: [{ properties: { cell_id: "B" } }] }));
  expect(onSelect).not.toHaveBeenCalled();
});

test("hiding stations empties the station source", () => {
  vi.stubEnv("VITE_GOONG_MAPTILES_KEY", "test-key");
  const { rerender } = render(<GapMap {...props()} />);
  const map = goong.instances[0];
  act(() => map.handlers.load());
  rerender(<GapMap {...props({ showStations: false })} />);
  expect((map.sources["gap-stations"].data as { features: unknown[] }).features).toHaveLength(0);
});

test("switches to OpenStreetMap when Goong errors before it finishes loading", () => {
  vi.stubEnv("VITE_GOONG_MAPTILES_KEY", "test-key");
  render(<GapMap {...props()} />);
  act(() => goong.instances[0].handlers.error());
  expect(screen.getByTestId("osm-map")).toBeTruthy();
});

test("heat-maps cells along roads and gives each station one of two colours", () => {
  vi.stubEnv("VITE_GOONG_MAPTILES_KEY", "test-key");
  const roadCells: GapCellItem[] = cells.map((cell, index) => ({
    ...cell, cell_id: `R${index}`, road_name: "Lý Tự Trọng", road_names: ["Lý Tự Trọng"], road_length_m: 120,
    rent_kvnd_m2_month: 200 + index * 300,
  }));
  const mixed: GapStationItem[] = [
    stations[0],
    { ...stations[0], station_id: "CMP-A-01", operator_id: "CMP-A", relationship: "OTHER_NETWORK" },
    { ...stations[0], station_id: "CMP-C-02", operator_id: "CMP-C", relationship: "OTHER_NETWORK" },
  ];
  render(<GapMap {...props({
    cells: roadCells, stations: mixed, results: new Map(), layer: "rent", candidates: [],
    selectedCandidateId: null,
  })} />);
  const map = goong.instances[0];
  act(() => map.handlers.load());

  const polygons = (map.sources["gap-cells"].data as { features: { geometry: { type: string }; properties: Record<string, unknown> }[] }).features;
  expect(polygons).toHaveLength(2);
  expect(polygons.every((feature) => feature.geometry.type === "Polygon")).toBe(true);
  // Heat colours differ between a low-flow and a high-flow cell (continuous, not two buckets).
  const colours = new Set(polygons.map((feature) => feature.properties.fill_color));
  expect(colours.size).toBe(2);

  const features = (map.sources["gap-stations"].data as { features: { properties: { color: string } }[] }).features;
  expect(new Set(features.map((f) => f.properties.color))).toEqual(new Set(["#0f766e", "#c2410c"]));
});

test("a station popup shows its location and the spec of every port", () => {
  vi.stubEnv("VITE_GOONG_MAPTILES_KEY", "test-key");
  render(<GapMap {...props()} />);
  const map = goong.instances[0];
  act(() => map.handlers.load());
  act(() => map.layerHandlers["gap-stations-layer"].click({
    lngLat: { lat: 10.77, lng: 106.69 }, point: {}, features: [{ properties: { station_id: "OWN-01" } }],
  }));
  const popup = goong.popups.at(-1);
  expect(popup?.html).toContain("OWN-01");
  expect(popup?.html).toContain("Trạm của mình");
  expect(popup?.html).toContain("Trung tâm thương mại");
  expect(popup?.html).toContain("DC · sạc nhanh");
  expect(popup?.html).toContain("502");
});

test("the traffic layer draws every road as a line from green to dark red and fades the blocks", () => {
  vi.stubEnv("VITE_GOONG_MAPTILES_KEY", "test-key");
  const { rerender } = render(<GapMap {...props({ layer: "flow" })} />);
  const map = goong.instances[0];
  act(() => map.handlers.load());

  const lines = (map.sources["gap-roads"].data as {
    features: { geometry: { type: string; coordinates: number[][] }; properties: { road_id: string; color: string } }[];
  }).features;
  expect(lines.map((f) => f.properties.road_id)).toEqual(["W00001", "W00003", "W00002"]); // busiest drawn last
  expect(lines.every((f) => f.geometry.type === "LineString")).toBe(true);
  expect(lines[0].geometry.coordinates[0]).toEqual([106.69, 10.77]); // [lon, lat]
  expect(lines[0].properties.color).toBe("#2eab4f");
  expect(lines[2].properties.color).toBe("#7b0d0d");
  expect(new Set(lines.map((f) => f.properties.color)).size).toBe(3);
  const blocks = (map.sources["gap-cells"].data as { features: { properties: { fill_opacity: number } }[] }).features;
  expect(blocks.every((f) => f.properties.fill_opacity <= 0.12)).toBe(true);
  expect(screen.getByText("Lưu lượng tuyến đường (xe/giờ)")).toBeTruthy();

  act(() => map.layerHandlers["gap-roads-hit"].mousemove({
    lngLat: { lat: 10.771, lng: 106.691 }, point: {}, features: [{ properties: { road_id: "W00002" } }],
  }));
  expect(goong.popups.at(-1)?.html).toContain("Lý Tự Trọng");
  expect(goong.popups.at(-1)?.html).toContain("4 làn");
  expect(goong.popups.at(-1)?.html).toContain("4.000 xe/giờ");
  expect(goong.popups.at(-1)?.html).toContain("Rất đông");

  rerender(<GapMap {...props({ layer: "rent" })} />);
  expect((map.sources["gap-roads"].data as { features: unknown[] }).features).toHaveLength(0);
});

test("the OpenStreetMap fallback colours the road lines on the traffic layer only", () => {
  vi.stubEnv("VITE_GOONG_MAPTILES_KEY", "");
  const { rerender } = render(<GapMap {...props({ layer: "flow" })} />);
  const colours = screen.getAllByTestId("osm-road").map((node) => node.getAttribute("data-color"));
  expect(colours).toEqual(["#2eab4f", expect.any(String), "#7b0d0d"]);
  rerender(<GapMap {...props({ layer: "gap" })} />);
  expect(screen.queryAllByTestId("osm-road")).toHaveLength(0);
});
