import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import goongjs from "@goongmaps/goong-js";
import "@goongmaps/goong-js/dist/goong-js.css";
import { CircleMarker, MapContainer, Polyline, Popup, TileLayer, useMap, useMapEvents } from "react-leaflet";

import { COLOR_HEX } from "../stationColor";
import type { GeoPoint, PickTarget, RecommendationItem, RouteResult, Station, StationColor } from "../types";

interface MapViewProps {
  stations: Station[];
  /** Backend-computed colour per station id; a station without one is drawn grey. */
  colors: Record<string, StationColor>;
  route: RouteResult | null;
  selectedStationId: string | null;
  hoveredStationId?: string | null;
  items?: RecommendationItem[];
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
const EMPTY_ITEMS: RecommendationItem[] = [];
const ROUTE_SOURCE = "journey-route";
const ROUTE_LAYER = "journey-route-line";

// Selected/hovered only toggle classes on existing markers; they never rebuild the map.
function applyMarkerClasses(
  elements: Map<string, HTMLElement>,
  selectedStationId: string | null,
  hoveredStationId: string | null | undefined,
) {
  elements.forEach((element, stationId) => {
    element.classList.toggle("map-marker--selected", stationId === selectedStationId);
    element.classList.toggle("map-marker--hovered", stationId === hoveredStationId);
  });
}

function GoongMap({
  stations,
  colors,
  route,
  selectedStationId,
  hoveredStationId,
  items = EMPTY_ITEMS,
  origin,
  destination,
  pickTarget,
  onMapPick,
  onStationSelect,
  onStationHover,
  onFailure,
}: Omit<MapViewProps, "onProviderChange"> & { onFailure: () => void }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const markerElements = useRef(new Map<string, HTMLElement>());
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
      setMap(instance);
    });
    return () => {
      setMap(null);
      instance.remove();
    };
  }, [mapToken]);

  // Markers are rebuilt only when the data they show changes.
  useEffect(() => {
    if (!map) return;
    const ranks = new Map(items.map((item, index) => [item.station_id, index + 1]));
    const elements = new Map<string, HTMLElement>();
    const markers: Array<{ remove(): void }> = [];
    for (const station of stations) {
      const stationId = station.properties.station_id;
      const element = document.createElement("button");
      element.type = "button";
      element.className = `map-marker map-marker--${colors[stationId] ?? "grey"}`;
      element.textContent = ranks.has(stationId) ? String(ranks.get(stationId)) : "•";
      element.title = station.properties.name;
      element.dataset.stationId = stationId;
      element.setAttribute("aria-label", `Mở ${station.properties.name}`);
      element.addEventListener("click", () => {
        // While picking, the map's own click handler takes this click.
        if (!latest.current.pickTarget) latest.current.onStationSelect(stationId);
      });
      element.addEventListener("mouseenter", () => latest.current.onStationHover?.(stationId));
      element.addEventListener("mouseleave", () => latest.current.onStationHover?.(null));
      elements.set(stationId, element);
      markers.push(new goongjs.Marker(element).setLngLat(station.geometry.coordinates).addTo(map));
    }
    markerElements.current = elements;
    applyMarkerClasses(elements, latest.current.selectedStationId, latest.current.hoveredStationId);
    return () => {
      markers.forEach((marker) => marker.remove());
      markerElements.current = new Map();
    };
  }, [map, stations, colors, items]);

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
    applyMarkerClasses(markerElements.current, selectedStationId, hoveredStationId);
  }, [map, selectedStationId, hoveredStationId]);

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
    map.addLayer({
      id: ROUTE_LAYER,
      type: "line",
      source: ROUTE_SOURCE,
      layout: { "line-join": "round", "line-cap": "round" },
      paint: { "line-color": "#14b8a6", "line-width": 6, "line-opacity": 0.9 },
    });
  }, [map, route]);

  useEffect(() => {
    if (!map || !selectedStationId) return;
    const selected = stations.find((item) => item.properties.station_id === selectedStationId);
    if (!selected) return;
    map.flyTo({
      center: selected.geometry.coordinates,
      zoom: 14,
      padding: { top: 70, bottom: 250, left: 60, right: 60 },
    });
  }, [map, selectedStationId, stations]);

  return <div className="map-canvas" ref={containerRef} aria-label="Bản đồ Goong" />;
}

function OsmMap({
  stations,
  colors,
  route,
  selectedStationId,
  hoveredStationId,
  items,
  origin,
  destination,
  pickTarget,
  onMapPick,
  onStationSelect,
  onStationHover,
}: Omit<MapViewProps, "onProviderChange">) {
  const rankedItems = items ?? [];
  const reportHover = onStationHover ?? (() => undefined);
  const ranks = new Map(rankedItems.map((item, index) => [item.station_id, index + 1]));
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
            <Popup>#{ranks.get(stationId) ?? "•"} · {station.properties.name}</Popup>
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
