import { useEffect, useMemo, useRef, useState } from "react";
import goongjs, { type GoongMapLayerMouseEvent } from "@goongmaps/goong-js";
import "@goongmaps/goong-js/dist/goong-js.css";

import { hideGoongPoiLayers } from "../../goongMapStyle";
import GapLegend from "./GapLegend";
import {
  HCMC_CENTER, cellBounds, cellFeatureCollection, cellOwnerId, cellTooltipHtml, roadFeatureCollection,
  roadTooltipHtml, stationFeatureCollection, stationPopupHtml, type GapMapProps,
} from "./gapGeo";
import type { CellView } from "./gapFormat";

const CELLS_SOURCE = "gap-cells";
const CELLS_FILL = "gap-cells-fill";
const CELLS_LINE = "gap-cells-line";
const CELLS_OWN_LINE = "gap-cells-own-line";
const CELLS_CLUSTER_LINE = "gap-cells-cluster-line";
const ROADS_SOURCE = "gap-roads";
const ROADS_CASING = "gap-roads-casing";
const ROADS_LINE = "gap-roads-line";
const ROADS_HIT = "gap-roads-hit";
const STATIONS_SOURCE = "gap-stations";
const STATIONS_LAYER = "gap-stations-layer";

type GoongFeatureEvent = GoongMapLayerMouseEvent;

const EMPTY_COLLECTION = { type: "FeatureCollection" as const, features: [] as unknown[] };

/** Goong vector basemap (VITE_GOONG_MAPTILES_KEY) with the grid, stations and candidates as GL layers. */
export default function GapGoongMap({
  cells, roads, results, layer, stations, showStations, candidates, selectedCandidateId, onSelectCandidate,
  onFailure,
}: GapMapProps & { onFailure: () => void }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const markersRef = useRef<InstanceType<typeof goongjs.Marker>[]>([]);
  const popupRef = useRef<InstanceType<typeof goongjs.Popup> | null>(null);
  const [map, setMap] = useState<InstanceType<typeof goongjs.Map> | null>(null);
  const mapToken = import.meta.env.VITE_GOONG_MAPTILES_KEY;
  const views = useMemo<CellView[]>(() => cells.map((item) => ({ item, result: results.get(item.cell_id) })), [cells, results]);

  const latest = useRef({ cells, roads, results, stations, candidates, onSelectCandidate, onFailure });
  useEffect(() => {
    latest.current = { cells, roads, results, stations, candidates, onSelectCandidate, onFailure };
  });

  // One map instance per token.
  useEffect(() => {
    if (!containerRef.current || !mapToken || !goongjs.supported()) {
      latest.current.onFailure();
      return;
    }
    goongjs.accessToken = mapToken;
    let loaded = false;
    const instance = new goongjs.Map({
      container: containerRef.current,
      style: "https://tiles.goong.io/assets/goong_map_web.json",
      center: HCMC_CENTER,
      zoom: 12,
    });
    instance.addControl(new goongjs.NavigationControl(), "top-right");
    instance.on("error", () => {
      if (!loaded) latest.current.onFailure();
    });
    instance.on("load", () => {
      loaded = true;
      hideGoongPoiLayers(instance);
      setMap(instance);
    });
    let resizeFrame = 0;
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(resizeFrame);
      resizeFrame = requestAnimationFrame(() => instance.resize());
    });
    observer.observe(containerRef.current);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(resizeFrame);
      setMap(null);
      instance.remove();
    };
  }, [mapToken]);

  // Sources, layers and pointer handlers are created once per map; data arrives through setData.
  useEffect(() => {
    if (!map) return;
    map.addSource(CELLS_SOURCE, { type: "geojson", data: EMPTY_COLLECTION });
    map.addSource(ROADS_SOURCE, { type: "geojson", data: EMPTY_COLLECTION });
    map.addSource(STATIONS_SOURCE, { type: "geojson", data: EMPTY_COLLECTION });
    map.addLayer({
      id: CELLS_FILL, type: "fill", source: CELLS_SOURCE,
      paint: { "fill-color": ["get", "fill_color"], "fill-opacity": ["get", "fill_opacity"], "fill-antialias": true },
    });
    map.addLayer({
      id: CELLS_LINE, type: "line", source: CELLS_SOURCE,
      paint: { "line-color": "#ffffff", "line-width": 0.5, "line-opacity": 0.8 },
    });
    map.addLayer({
      id: CELLS_OWN_LINE, type: "line", source: CELLS_SOURCE, filter: ["==", ["get", "own_overlap"], true],
      paint: { "line-color": "#0f766e", "line-width": 1.4, "line-dasharray": [2, 2] },
    });
    map.addLayer({
      id: CELLS_CLUSTER_LINE, type: "line", source: CELLS_SOURCE, filter: ["==", ["get", "in_cluster"], true],
      paint: { "line-color": "#111827", "line-width": 2.5 },
    });
    // Line widths scale with the road class and the zoom level.
    const zoomWidth = (factor: number) => [
      "interpolate", ["linear"], ["zoom"],
      10, ["*", ["get", "width"], 0.3 * factor], 14, ["*", ["get", "width"], factor],
      18, ["*", ["get", "width"], 3 * factor],
    ];
    map.addLayer({
      id: ROADS_CASING, type: "line", source: ROADS_SOURCE,
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": "#ffffff", "line-opacity": 0.75, "line-width": zoomWidth(1.35) },
    });
    map.addLayer({
      id: ROADS_LINE, type: "line", source: ROADS_SOURCE,
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": ["get", "color"], "line-width": zoomWidth(1) },
    });
    // Invisible wide line so thin roads are easy to hover.
    map.addLayer({
      id: ROADS_HIT, type: "line", source: ROADS_SOURCE,
      paint: { "line-color": "#000000", "line-opacity": 0, "line-width": 12 },
    });
    map.addLayer({
      id: STATIONS_LAYER, type: "circle", source: STATIONS_SOURCE,
      paint: {
        "circle-radius": ["get", "radius"], "circle-color": ["get", "color"],
        "circle-stroke-width": 1.5, "circle-stroke-color": "#ffffff", "circle-opacity": 0.95,
      },
    });

    const canvas = map.getCanvas();
    const closePopup = () => { popupRef.current?.remove(); popupRef.current = null; };
    const openPopup = (lngLat: { lat: number; lng: number }, html: string, closeButton: boolean) => {
      closePopup();
      popupRef.current = new goongjs.Popup({ offset: 8, closeButton, closeOnClick: closeButton, maxWidth: "360px" })
        .setLngLat([lngLat.lng, lngLat.lat])
        .setHTML(html)
        .addTo(map);
    };
    const cellFromEvent = (event: GoongFeatureEvent) => {
      const cellId = event.features?.[0]?.properties.cell_id;
      return typeof cellId === "string" ? cellId : null;
    };
    const roadUnder = (event: GoongFeatureEvent) => map.queryRenderedFeatures(event.point, { layers: [ROADS_HIT] });
    const handleCellMove = (event: GoongFeatureEvent) => {
      if (roadUnder(event).length > 0) return; // the road popup takes over
      const cellId = cellFromEvent(event);
      const item = latest.current.cells.find((cell) => cell.cell_id === cellId);
      if (!item) return;
      canvas.style.cursor = "pointer";
      openPopup(event.lngLat, cellTooltipHtml(item, latest.current.results.get(item.cell_id)), false);
    };
    const handleCellLeave = () => { canvas.style.cursor = ""; closePopup(); };
    const handleCellClick = (event: GoongFeatureEvent) => {
      // A station drawn over the cell has its own popup.
      if (map.queryRenderedFeatures(event.point, { layers: [STATIONS_LAYER] }).length > 0) return;
      const cellId = cellFromEvent(event);
      if (cellId) latest.current.onSelectCandidate(cellOwnerId(cellId, latest.current.candidates));
    };
    const handleStationClick = (event: GoongFeatureEvent) => {
      const stationId = event.features?.[0]?.properties.station_id;
      const station = latest.current.stations.find((item) => item.station_id === stationId);
      if (station) openPopup(event.lngLat, stationPopupHtml(station), true);
    };
    const handleRoadMove = (event: GoongFeatureEvent) => {
      const roadId = event.features?.[0]?.properties.road_id;
      const road = latest.current.roads.find((item) => item.road_id === roadId);
      if (!road) return;
      canvas.style.cursor = "pointer";
      openPopup(event.lngLat, roadTooltipHtml(road, latest.current.roads), false);
    };
    const stationEnter = () => { canvas.style.cursor = "pointer"; closePopup(); };
    const stationLeave = () => { canvas.style.cursor = ""; };
    map.on("mousemove", CELLS_FILL, handleCellMove);
    map.on("mouseleave", CELLS_FILL, handleCellLeave);
    map.on("click", CELLS_FILL, handleCellClick);
    map.on("mousemove", ROADS_HIT, handleRoadMove);
    map.on("mouseleave", ROADS_HIT, handleCellLeave);
    map.on("click", STATIONS_LAYER, handleStationClick);
    map.on("mouseenter", STATIONS_LAYER, stationEnter);
    map.on("mouseleave", STATIONS_LAYER, stationLeave);
    return () => {
      closePopup();
      for (const marker of markersRef.current) marker.remove();
      markersRef.current = [];
    };
  }, [map]);

  useEffect(() => {
    if (!map) return;
    map.getSource(CELLS_SOURCE)?.setData(cellFeatureCollection(cells, results, layer, candidates, selectedCandidateId));
  }, [map, cells, results, layer, candidates, selectedCandidateId]);

  // Road lines only exist on the traffic layer.
  useEffect(() => {
    if (!map) return;
    map.getSource(ROADS_SOURCE)?.setData(layer === "flow" ? roadFeatureCollection(roads) : EMPTY_COLLECTION);
  }, [map, roads, layer]);

  useEffect(() => {
    if (!map) return;
    map.getSource(STATIONS_SOURCE)?.setData(showStations ? stationFeatureCollection(stations) : EMPTY_COLLECTION);
  }, [map, stations, showStations]);

  useEffect(() => {
    if (!map) return;
    const bounds = cellBounds(cells);
    if (bounds) map.fitBounds(bounds, { padding: 24, duration: 0 });
  }, [map, cells]);

  // Numbered candidate markers are DOM markers, so they need no glyphs from the basemap style.
  useEffect(() => {
    if (!map) return;
    for (const marker of markersRef.current) marker.remove();
    markersRef.current = candidates.map((candidate) => {
      const element = document.createElement("button");
      element.type = "button";
      element.className = `gap-rank-marker${candidate.cell_id === selectedCandidateId ? " selected" : ""}`;
      element.textContent = String(candidate.selection_order);
      element.setAttribute("aria-label", `Ứng viên ${candidate.selection_order}, ô ${candidate.cell_id}`);
      element.addEventListener("click", (event) => {
        event.stopPropagation();
        latest.current.onSelectCandidate(candidate.cell_id);
      });
      return new goongjs.Marker(element).setLngLat([candidate.lon, candidate.lat]).addTo(map);
    });
  }, [map, candidates, selectedCandidateId]);

  return (
    <div className="gap-map-wrap">
      <div className="gap-map" ref={containerRef} aria-label="Bản đồ Goong khoảng trống" />
      <GapLegend layer={layer} views={views} roads={roads} />
    </div>
  );
}
