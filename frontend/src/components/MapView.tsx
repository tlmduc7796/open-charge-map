import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "@goongmaps/goong-js/dist/goong-js.css";
import { CircleMarker, MapContainer, Polyline, Popup, TileLayer, useMap, useMapEvents } from "react-leaflet";

import type { GoongMap, GoongMarker, GoongStatic } from "@goongmaps/goong-js";
import type { RouteResult, Station, StationBounds, StationStatus } from "../types";

interface MapViewProps {
  stations: Station[];
  statuses: Record<string, StationStatus>;
  route: RouteResult | null;
  selectedStationId: string | null;
  onStationSelect: (stationId: string) => void;
  onProviderChange: (provider: "goong" | "osm") => void;
  onViewportChange: (bounds: StationBounds) => void;
}

const HCMC_CENTER: [number, number] = [106.7009, 10.7769];

function stateFor(status: StationStatus | undefined) {
  if (!status) return "unknown";
  if (status.is_stale || status.data_source === "unknown" || status.unknown_ports === status.total_ports) return "unknown";
  if (status.operational_ports === 0) return "offline";
  if (status.data_source === "runtime") return "affected";
  if (status.available_ports === 0 || (status.queue_length != null && status.queue_length > 0)) return "busy";
  return "available";
}

function GoongMap({
  stations,
  statuses,
  route,
  selectedStationId,
  onStationSelect,
  onViewportChange,
  onFailure,
}: Omit<MapViewProps, "onProviderChange"> & { onFailure: () => void }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<GoongMap | null>(null);
  const goongRef = useRef<GoongStatic | null>(null);
  const markersRef = useRef(
    new Map<string, { marker: GoongMarker; element: HTMLButtonElement }>(),
  );
  const latestProps = useRef({
    stations,
    statuses,
    route,
    selectedStationId,
    onStationSelect,
    onViewportChange,
  });
  const mapToken = import.meta.env.VITE_GOONG_MAPTILES_KEY;

  useEffect(() => {
    latestProps.current = {
      stations,
      statuses,
      route,
      selectedStationId,
      onStationSelect,
      onViewportChange,
    };
  }, [onStationSelect, onViewportChange, route, selectedStationId, stations, statuses]);

  const syncMarkers = useCallback(() => {
    const map = mapRef.current;
    const goongjs = goongRef.current;
    if (!map || !goongjs) return;
    const current = latestProps.current;
    const stationIds = new Set(current.stations.map((station) => station.properties.station_id));
    for (const [stationId, entry] of markersRef.current) {
      if (stationIds.has(stationId)) continue;
      entry.marker.remove();
      markersRef.current.delete(stationId);
    }
    for (const station of current.stations) {
      const stationId = station.properties.station_id;
      let entry = markersRef.current.get(stationId);
      if (!entry) {
        const element = document.createElement("button");
        element.type = "button";
        element.addEventListener("click", () => latestProps.current.onStationSelect(stationId));
        entry = {
          element,
          marker: new goongjs.Marker(element)
            .setLngLat(station.geometry.coordinates)
            .addTo(map),
        };
        markersRef.current.set(stationId, entry);
      }
      entry.element.className = `map-marker map-marker--${stateFor(current.statuses[stationId])}`;
      if (stationId === current.selectedStationId) {
        entry.element.classList.add("map-marker--selected");
      }
      entry.element.title = station.properties.name;
      entry.element.setAttribute("aria-label", `Open ${station.properties.name}`);
    }
  }, []);

  const syncRoute = useCallback(() => {
    const map = mapRef.current;
    if (!map) return;
    const source = map.getSource("journey-route");
    const currentRoute = latestProps.current.route;
    if (currentRoute && source) {
      source.setData({
        type: "Feature",
        properties: {},
        geometry: currentRoute.geometry,
      });
      return;
    }
    if (currentRoute) {
      map.addSource("journey-route", {
        type: "geojson",
        data: { type: "Feature", properties: {}, geometry: currentRoute.geometry },
      });
      map.addLayer({
        id: "journey-route-line",
        type: "line",
        source: "journey-route",
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": "#14b8a6", "line-width": 6, "line-opacity": 0.9 },
      });
    } else if (source) {
      if (map.getLayer("journey-route-line")) map.removeLayer("journey-route-line");
      map.removeSource("journey-route");
    }
  }, []);

  const reportViewport = useCallback(() => {
    const bounds = mapRef.current?.getBounds();
    if (!bounds) return;
    latestProps.current.onViewportChange({
      west: bounds.getWest(),
      south: bounds.getSouth(),
      east: bounds.getEast(),
      north: bounds.getNorth(),
    });
  }, []);

  useEffect(() => {
    const markers = markersRef.current;
    let disposed = false;
    let createdMap: GoongMap | null = null;
    if (!containerRef.current || !mapToken) {
      onFailure();
      return () => { disposed = true; };
    }
    void import("@goongmaps/goong-js").then(
      ({ default: goongjs }) => {
        if (disposed) return;
        if (!containerRef.current || !goongjs.supported()) {
          onFailure();
          return;
        }
        goongjs.accessToken = mapToken;
        goongRef.current = goongjs;
        let loaded = false;
        createdMap = new goongjs.Map({
          container: containerRef.current,
          style: "https://tiles.goong.io/assets/goong_map_web.json",
          center: HCMC_CENTER,
          zoom: 12,
        });
        mapRef.current = createdMap;
        createdMap.addControl(new goongjs.NavigationControl(), "top-right");
        createdMap.on("error", () => {
          if (!loaded) onFailure();
        });
        createdMap.on("load", () => {
          loaded = true;
          syncMarkers();
          syncRoute();
          reportViewport();
        });
        createdMap.on("moveend", reportViewport);
      },
      onFailure,
    );
    return () => {
      disposed = true;
      markers.forEach(({ marker }) => marker.remove());
      markers.clear();
      if (mapRef.current === createdMap) mapRef.current = null;
      goongRef.current = null;
      createdMap?.remove();
    };
  }, [mapToken, onFailure, reportViewport, syncMarkers, syncRoute]);

  useEffect(() => syncMarkers(), [selectedStationId, stations, statuses, syncMarkers]);
  useEffect(() => syncRoute(), [route, syncRoute]);

  return <div className="map-canvas" ref={containerRef} aria-label="Goong map" />;
}

function OsmMap({
  stations,
  statuses,
  route,
  selectedStationId,
  onStationSelect,
  onViewportChange,
}: Omit<MapViewProps, "onProviderChange">) {
  const routePositions = useMemo(
    () => route?.geometry.coordinates.map(([lon, lat]) => [lat, lon] as [number, number]) ?? [],
    [route],
  );
  return (
    <MapContainer center={[HCMC_CENTER[1], HCMC_CENTER[0]]} zoom={12} className="map-canvas">
      <ViewportReporter onViewportChange={onViewportChange} />
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      {routePositions.length > 0 && <Polyline positions={routePositions} color="#0f766e" weight={6} />}
      {stations.map((station) => {
        const stationId = station.properties.station_id;
        const state = stateFor(statuses[stationId]);
        const colors = {
          available: "#16a34a",
          busy: "#f59e0b",
          affected: "#ef4444",
          offline: "#64748b",
          unknown: "#94a3b8",
        };
        return (
          <CircleMarker
            key={stationId}
            center={[station.geometry.coordinates[1], station.geometry.coordinates[0]]}
            radius={selectedStationId === stationId ? 12 : 9}
            pathOptions={{ color: "#ffffff", weight: 3, fillColor: colors[state], fillOpacity: 1 }}
            eventHandlers={{ click: () => onStationSelect(stationId) }}
          >
            <Popup>{station.properties.name}</Popup>
          </CircleMarker>
        );
      })}
    </MapContainer>
  );
}

function ViewportReporter({
  onViewportChange,
}: {
  onViewportChange: (bounds: StationBounds) => void;
}) {
  const map = useMap();
  const report = useCallback(() => {
    const bounds = map.getBounds();
    onViewportChange({
      west: bounds.getWest(),
      south: bounds.getSouth(),
      east: bounds.getEast(),
      north: bounds.getNorth(),
    });
  }, [map, onViewportChange]);
  useMapEvents({ moveend: report });
  useEffect(() => { report(); }, [report]);
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
