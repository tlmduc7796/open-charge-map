import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import goongjs from "@goongmaps/goong-js";
import "@goongmaps/goong-js/dist/goong-js.css";
import { CircleMarker, MapContainer, Polyline, Popup, TileLayer, useMap, useMapEvents } from "react-leaflet";

import { hideGoongPoiLayers, loadSdfIcon } from "../goongMapStyle";
import { COLOR_HEX } from "../stationColor";
import type { GeoPoint, PickTarget, RouteResult, Station, StationColor } from "../types";

// MDI "ev-station" glyph (https://pictogrammers.com/library/mdi/icon/ev-station/).
const STATION_ICON_PATH =
  "M19.77,7.23L19.78,7.22L16.06,3.5L15,4.56L17.11,6.67C16.17,7.03 15.5,7.93 15.5,9A2.5,2.5 0 0,0 18,11.5C18.36,11.5 18.69,11.42 19,11.29V18.5A1,1 0 0,1 18,19.5A1,1 0 0,1 17,18.5V14A2,2 0 0,0 15,12H14V5A2,2 0 0,0 12,3H6A2,2 0 0,0 4,5V21H14V13.5H15.5V18.5A2.5,2.5 0 0,0 18,21A2.5,2.5 0 0,0 20.5,18.5V9C20.5,8.31 20.22,7.68 19.77,7.23M18,10A1,1 0 0,1 17,9A1,1 0 0,1 18,8A1,1 0 0,1 19,9A1,1 0 0,1 18,10M8,18V13.5H6L10,6V11H12L8,18Z";
const STATION_ICON_ID = "ev-station-icon";
const STATION_SOURCE = "station-markers";
const STATION_DOT_LAYER = "station-markers-dot";
const STATION_ICON_LAYER = "station-markers-icon";

interface MapViewProps {
  stations: Station[];
  /** Backend-computed colour per station id; a station without one is drawn grey. */
  colors: Record<string, StationColor>;
  route: RouteResult | null;
  selectedStationId: string | null;
  hoveredStationId?: string | null;
  /** Journey start (route start, or the single point of a station search). */
  origin?: GeoPoint;
  destination?: GeoPoint;
  /** While set, the next map click sets that endpoint instead of selecting a station. */
  pickTarget?: PickTarget | null;
  onMapPick?: (point: { lat: number; lon: number }) => void;
  onStationSelect: (stationId: string) => void;
  onStationHover?: (stationId: string | null) => void;
  onProviderChange: (provider: "goong" | "osm") => void;
}

const HCMC_CENTER: [number, number] = [106.7009, 10.7769];
const ROUTE_SOURCE = "journey-route";
const ROUTE_LAYER = "journey-route-line";

function stationFeatureCollection(
  stations: Station[],
  colors: Record<string, StationColor>,
  selectedStationId: string | null,
  hoveredStationId: string | null | undefined,
) {
  return {
    type: "FeatureCollection" as const,
    features: stations.map((station) => {
      const stationId = station.properties.station_id;
      return {
        type: "Feature" as const,
        geometry: station.geometry,
        properties: {
          stationId,
          color: colors[stationId] ?? "grey",
          selected: stationId === selectedStationId,
          hovered: stationId === hoveredStationId,
        },
      };
    }),
  };
}

function GoongMap({
  stations,
  colors,
  route,
  selectedStationId,
  hoveredStationId,
  origin,
  destination,
  pickTarget,
  onMapPick,
  onStationSelect,
  onStationHover,
  onFailure,
}: Omit<MapViewProps, "onProviderChange"> & { onFailure: () => void }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [map, setMap] = useState<InstanceType<typeof goongjs.Map> | null>(null);
  const mapToken = import.meta.env.VITE_GOONG_MAPTILES_KEY;
  const originLat = origin?.lat;
  const originLon = origin?.lon;
  const originLabel = origin?.label ?? "Điểm đi";
  const destLat = destination?.lat;
  const destLon = destination?.lon;
  const destLabel = destination?.label ?? "Điểm đến";

  // Latest props for listeners and effects that must not re-run when they change.
  const latest = useRef({
    onStationSelect,
    onStationHover,
    onFailure,
    onMapPick,
    pickTarget,
    selectedStationId,
    hoveredStationId,
  });
  useEffect(() => {
    latest.current = {
      onStationSelect,
      onStationHover,
      onFailure,
      onMapPick,
      pickTarget,
      selectedStationId,
      hoveredStationId,
    };
  });

  // The map instance is created once per token.
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
    return () => {
      setMap(null);
      instance.remove();
    };
  }, [mapToken]);

  // Station markers are a GL source/layers, not DOM elements: goong-js's DOM Marker
  // repositions an HTML element via JS on every "move" event, which can visibly lag
  // behind the WebGL canvas during a fast zoom/pan. A GL layer is drawn by the same
  // pipeline as the basemap in the same frame, so it can never drift from it.
  // The source is created once; later updates just call setData (cheap for ~dozens
  // of points), matching the pattern PlannerMap.tsx already uses for its GL layers.
  useEffect(() => {
    if (!map) return;
    const data = stationFeatureCollection(stations, colors, selectedStationId, hoveredStationId);
    const source = map.getSource(STATION_SOURCE);
    if (source) {
      source.setData(data);
      return;
    }
    map.addSource(STATION_SOURCE, { type: "geojson", data });
    map.addLayer({
      id: STATION_DOT_LAYER,
      type: "circle",
      source: STATION_SOURCE,
      paint: {
        "circle-radius": ["case", ["get", "selected"], 16, ["get", "hovered"], 15, 13],
        "circle-color": [
          "match",
          ["get", "color"],
          "green", COLOR_HEX.green,
          "yellow", COLOR_HEX.yellow,
          "red", COLOR_HEX.red,
          COLOR_HEX.grey,
        ],
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": ["case", ["get", "selected"], 3, 2],
      },
    });
    map.addLayer({
      id: STATION_ICON_LAYER,
      type: "symbol",
      source: STATION_SOURCE,
      layout: {
        "icon-image": STATION_ICON_ID,
        "icon-size": ["case", ["get", "selected"], 0.27, ["get", "hovered"], 0.25, 0.22],
        "icon-allow-overlap": true,
        "icon-ignore-placement": true,
      },
      paint: { "icon-color": "#ffffff" },
    });
    // The icon registers asynchronously; a symbol layer with no image yet for its
    // "icon-image" just skips drawing icons until addImage resolves, so this doesn't
    // need to block (or gate) the addLayer calls above.
    loadSdfIcon(map, STATION_ICON_ID, STATION_ICON_PATH).catch(() => undefined);
  }, [map, stations, colors, selectedStationId, hoveredStationId]);

  // Click/hover are bound once to the stable layer id rather than rebuilding per
  // station-data change (mirrors the layer click/hover wiring in PlannerMap.tsx).
  useEffect(() => {
    if (!map) return;
    const canvas = map.getCanvas();
    const stationIdOf = (event: { features?: Array<{ properties: Record<string, unknown> }> }) => {
      const value = event.features?.[0]?.properties.stationId;
      return typeof value === "string" ? value : undefined;
    };
    const handleClick = (event: { features?: Array<{ properties: Record<string, unknown> }> }) => {
      const stationId = stationIdOf(event);
      // While picking, the map's own click handler (below) takes this click.
      if (stationId && !latest.current.pickTarget) latest.current.onStationSelect(stationId);
    };
    const handleEnter = (event: { features?: Array<{ properties: Record<string, unknown> }> }) => {
      const stationId = stationIdOf(event);
      if (stationId) latest.current.onStationHover?.(stationId);
      if (!latest.current.pickTarget) canvas.style.cursor = "pointer";
    };
    const handleLeave = () => {
      latest.current.onStationHover?.(null);
      if (!latest.current.pickTarget) canvas.style.cursor = "";
    };
    map.on("click", STATION_DOT_LAYER, handleClick);
    map.on("mouseenter", STATION_DOT_LAYER, handleEnter);
    map.on("mouseleave", STATION_DOT_LAYER, handleLeave);
    return () => {
      map.off("click", STATION_DOT_LAYER, handleClick);
      map.off("mouseenter", STATION_DOT_LAYER, handleEnter);
      map.off("mouseleave", STATION_DOT_LAYER, handleLeave);
    };
  }, [map]);

  // Journey endpoints live in their own effect so moving them never rebuilds the station markers.
  // goong-js owns each marker element's inline transform, so the visual shape lives on a child.
  useEffect(() => {
    if (!map) return;
    const markers: Array<{ remove(): void }> = [];
    if (originLat !== undefined && originLon !== undefined) {
      const element = document.createElement("div");
      element.className = "origin-marker";
      element.title = `Điểm đi: ${originLabel}`;
      const badge = document.createElement("div");
      badge.className = "origin-badge";
      badge.textContent = "Đi";
      element.append(badge);
      markers.push(new goongjs.Marker(element).setLngLat([originLon, originLat]).addTo(map));
    }
    if (destLat !== undefined && destLon !== undefined) {
      const element = document.createElement("div");
      element.className = "destination-marker";
      element.title = `Điểm đến: ${destLabel}`;
      const pin = document.createElement("div");
      pin.className = "destination-pin";
      const pinLabel = document.createElement("span");
      pinLabel.textContent = "Đ";
      pin.append(pinLabel);
      element.append(pin);
      markers.push(new goongjs.Marker(element).setLngLat([destLon, destLat]).addTo(map));
    }
    return () => markers.forEach((marker) => marker.remove());
  }, [map, originLat, originLon, originLabel, destLat, destLon, destLabel]);

  // Pick mode: crosshair cursor and a map click handler, active only while a target is set.
  useEffect(() => {
    if (!map || !pickTarget) return;
    const canvas = map.getCanvas();
    const previousCursor = canvas.style.cursor;
    canvas.style.cursor = "crosshair";
    const handleClick = (event?: unknown) => {
      const lngLat = (event as { lngLat?: { lat: number; lng: number } } | undefined)?.lngLat;
      if (lngLat) latest.current.onMapPick?.({ lat: lngLat.lat, lon: lngLat.lng });
    };
    map.on("click", handleClick);
    return () => {
      map.off("click", handleClick);
      canvas.style.cursor = previousCursor;
    };
  }, [map, pickTarget]);

  useEffect(() => {
    if (!map) return;
    const source = map.getSource(ROUTE_SOURCE);
    if (!route) {
      if (map.getLayer(ROUTE_LAYER)) map.removeLayer(ROUTE_LAYER);
      if (source) map.removeSource(ROUTE_SOURCE);
      return;
    }
    const data = { type: "Feature", properties: {}, geometry: route.geometry };
    if (source) {
      source.setData(data);
      return;
    }
    map.addSource(ROUTE_SOURCE, { type: "geojson", data });
    // Inserted below the station layers so the route never paints over a marker.
    map.addLayer(
      {
        id: ROUTE_LAYER,
        type: "line",
        source: ROUTE_SOURCE,
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": "#14b8a6", "line-width": 6, "line-opacity": 0.9 },
      },
      map.getLayer(STATION_DOT_LAYER) ? STATION_DOT_LAYER : undefined,
    );
  }, [map, route]);

  // Keyed on the selected station's coordinates, not the `stations` array: the parent narrows that
  // list to the route, and a new list with the same selection must not re-centre the map.
  const selectedCoordinates = stations.find(
    (item) => item.properties.station_id === selectedStationId,
  )?.geometry.coordinates;
  const selectedLon = selectedCoordinates?.[0];
  const selectedLat = selectedCoordinates?.[1];
  useEffect(() => {
    if (!map || selectedLon === undefined || selectedLat === undefined) return;
    map.flyTo({
      center: [selectedLon, selectedLat],
      zoom: 14,
      padding: { top: 70, bottom: 250, left: 60, right: 60 },
    });
  }, [map, selectedStationId, selectedLon, selectedLat]);

  return <div className="map-canvas" ref={containerRef} aria-label="Bản đồ Goong" />;
}

function OsmMap({
  stations,
  colors,
  route,
  selectedStationId,
  hoveredStationId,
  origin,
  destination,
  pickTarget,
  onMapPick,
  onStationSelect,
  onStationHover,
}: Omit<MapViewProps, "onProviderChange">) {
  const reportHover = onStationHover ?? (() => undefined);
  const selectedStation = stations.find((station) => station.properties.station_id === selectedStationId);
  const selectedPosition = useMemo(
    () => selectedStation ? [selectedStation.geometry.coordinates[1], selectedStation.geometry.coordinates[0]] as [number, number] : null,
    [selectedStation],
  );
  const routePositions = useMemo(
    () => route?.geometry.coordinates.map(([lon, lat]) => [lat, lon] as [number, number]) ?? [],
    [route],
  );
  return (
    <MapContainer center={[HCMC_CENTER[1], HCMC_CENTER[0]]} zoom={12} className="map-canvas">
      <MapFocus routePositions={routePositions} selectedPosition={selectedPosition} />
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      {routePositions.length > 0 && <Polyline positions={routePositions} color="#0f766e" weight={6} />}
      <MapPicker active={Boolean(pickTarget)} onPick={onMapPick} />
      {origin && (
        <CircleMarker center={[origin.lat, origin.lon]} radius={9} pathOptions={{ color: "#fff", weight: 3, fillColor: "#2563eb", fillOpacity: 1 }}><Popup>Điểm đi{origin.label ? ` · ${origin.label}` : ""}</Popup></CircleMarker>
      )}
      {destination && (
        <CircleMarker center={[destination.lat, destination.lon]} radius={8} pathOptions={{ color: "#fff", weight: 3, fillColor: "#123d35", fillOpacity: 1 }}><Popup>Điểm đến{destination.label ? ` · ${destination.label}` : ""}</Popup></CircleMarker>
      )}
      {stations.map((station) => {
        const stationId = station.properties.station_id;
        return (
          <CircleMarker
            key={stationId}
            center={[station.geometry.coordinates[1], station.geometry.coordinates[0]]}
            radius={selectedStationId === stationId ? 12 : hoveredStationId === stationId ? 13 : 9}
            pathOptions={{ color: "#ffffff", weight: 3, fillColor: COLOR_HEX[colors[stationId] ?? "grey"], fillOpacity: 1 }}
            eventHandlers={{ click: () => { if (!pickTarget) onStationSelect(stationId); }, mouseover: () => reportHover(stationId), mouseout: () => reportHover(null) }}
          >
            <Popup>{station.properties.name}</Popup>
          </CircleMarker>
        );
      })}
    </MapContainer>
  );
}

function MapPicker({
  active,
  onPick,
}: {
  active: boolean;
  onPick?: (point: { lat: number; lon: number }) => void;
}) {
  const map = useMapEvents({
    click(event) {
      if (active) onPick?.({ lat: event.latlng.lat, lon: event.latlng.lng });
    },
  });
  useEffect(() => {
    const container = map.getContainer();
    container.style.cursor = active ? "crosshair" : "";
    return () => {
      container.style.cursor = "";
    };
  }, [map, active]);
  return null;
}

function MapFocus({ routePositions, selectedPosition }: { routePositions: [number, number][]; selectedPosition: [number, number] | null }) {
  const map = useMap();
  useEffect(() => {
    if (routePositions.length > 1) {
      map.fitBounds(routePositions, { paddingTopLeft: [42, 54], paddingBottomRight: [42, 250], maxZoom: 14, animate: true });
    } else if (selectedPosition) {
      map.flyTo(selectedPosition, 14, { animate: true });
    }
  }, [map, routePositions, selectedPosition]);
  return null;
}

export default function MapView({ onProviderChange, ...props }: MapViewProps) {
  const hasGoongKey = Boolean(import.meta.env.VITE_GOONG_MAPTILES_KEY);
  const [useFallback, setUseFallback] = useState(!hasGoongKey);
  const handleFailure = useCallback(() => setUseFallback(true), []);

  useEffect(() => {
    onProviderChange(useFallback ? "osm" : "goong");
  }, [onProviderChange, useFallback]);

  if (useFallback) return <OsmMap {...props} />;
  return <GoongMap {...props} onFailure={handleFailure} />;
}
