import { useEffect, useMemo, useRef, useState } from "react";
import goongjs from "@goongmaps/goong-js";
import "@goongmaps/goong-js/dist/goong-js.css";
import { CircleMarker, MapContainer, Polyline, Popup, TileLayer } from "react-leaflet";

import type { RouteResult, Station, StationStatus } from "../types";

interface MapViewProps {
  stations: Station[];
  statuses: Record<string, StationStatus>;
  route: RouteResult | null;
  selectedStationId: string | null;
  onStationSelect: (stationId: string) => void;
  onProviderChange: (provider: "goong" | "osm") => void;
}

const HCMC_CENTER: [number, number] = [106.7009, 10.7769];

function stateFor(status: StationStatus | undefined) {
  if (!status || status.operational_ports === 0) return "offline";
  if (status.data_source === "runtime") return "affected";
  if (status.available_ports === 0 || (status.queue_length ?? 0) > 0) return "busy";
  return "available";
}

function GoongMap({
  stations,
  statuses,
  route,
  selectedStationId,
  onStationSelect,
  onFailure,
}: Omit<MapViewProps, "onProviderChange"> & { onFailure: () => void }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapToken = import.meta.env.VITE_GOONG_MAPTILES_KEY;

  useEffect(() => {
    if (!containerRef.current || !mapToken || !goongjs.supported()) {
      onFailure();
      return;
    }
    goongjs.accessToken = mapToken;
    let loaded = false;
    const markers: Array<{ remove(): void }> = [];
    const map = new goongjs.Map({
      container: containerRef.current,
      style: "https://tiles.goong.io/assets/goong_map_web.json",
      center: HCMC_CENTER,
      zoom: 12,
    });
    map.addControl(new goongjs.NavigationControl(), "top-right");
    map.on("error", () => {
      if (!loaded) onFailure();
    });
    map.on("load", () => {
      loaded = true;
      for (const station of stations) {
        const state = stateFor(statuses[station.properties.station_id]);
        const marker = document.createElement("button");
        marker.type = "button";
        marker.className = `map-marker map-marker--${state}`;
        if (station.properties.station_id === selectedStationId) {
          marker.classList.add("map-marker--selected");
        }
        marker.title = station.properties.name;
        marker.setAttribute("aria-label", `Mở ${station.properties.name}`);
        marker.addEventListener("click", () =>
          onStationSelect(station.properties.station_id),
        );
        markers.push(
          new goongjs.Marker(marker)
            .setLngLat(station.geometry.coordinates)
            .addTo(map),
        );
      }
      if (route) {
        map.addSource("journey-route", {
          type: "geojson",
          data: { type: "Feature", properties: {}, geometry: route.geometry },
        });
        map.addLayer({
          id: "journey-route-line",
          type: "line",
          source: "journey-route",
          layout: { "line-join": "round", "line-cap": "round" },
          paint: { "line-color": "#14b8a6", "line-width": 6, "line-opacity": 0.9 },
        });
      }
    });
    return () => {
      markers.forEach((marker) => marker.remove());
      map.remove();
    };
  }, [mapToken, onFailure, onStationSelect, route, selectedStationId, stations, statuses]);

  return <div className="map-canvas" ref={containerRef} aria-label="Bản đồ Goong" />;
}

function OsmMap({
  stations,
  statuses,
  route,
  selectedStationId,
  onStationSelect,
}: Omit<MapViewProps, "onProviderChange">) {
  const routePositions = useMemo(
    () => route?.geometry.coordinates.map(([lon, lat]) => [lat, lon] as [number, number]) ?? [],
    [route],
  );
  return (
    <MapContainer center={[HCMC_CENTER[1], HCMC_CENTER[0]]} zoom={12} className="map-canvas">
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

export default function MapView({ onProviderChange, ...props }: MapViewProps) {
  const hasGoongKey = Boolean(import.meta.env.VITE_GOONG_MAPTILES_KEY);
  const [useFallback, setUseFallback] = useState(!hasGoongKey);

  useEffect(() => {
    onProviderChange(useFallback ? "osm" : "goong");
  }, [onProviderChange, useFallback]);

  if (useFallback) return <OsmMap {...props} />;
  return <GoongMap {...props} onFailure={() => setUseFallback(true)} />;
}
