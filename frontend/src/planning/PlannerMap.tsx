import { useEffect } from "react";
import { latLngBounds } from "leaflet";
import { CircleMarker, MapContainer, Popup, TileLayer, useMap } from "react-leaflet";

import type { Station } from "../types";
import type { PlanningRecommendation } from "./types";

const HCMC_CENTER: [number, number] = [10.7769, 106.7009];

interface PlannerMapProps {
  recommendations: PlanningRecommendation[];
  stationCatalog: Station[];
  selectedCandidateId: string | null;
  onSelect: (candidateId: string) => void;
}

function FitMapItems({ items, stations }: { items: PlanningRecommendation[]; stations: Station[] }) {
  const map = useMap();
  useEffect(() => {
    const points = items.length > 0
      ? items.map(({ location }) => [location.lat, location.lon] as [number, number])
      : stations.map(({ geometry }) => [geometry.coordinates[1], geometry.coordinates[0]] as [number, number]);
    if (points.length === 0) return;
    const bounds = latLngBounds(points);
    map.fitBounds(bounds, { padding: [42, 42], maxZoom: 14 });
  }, [items, map, stations]);
  return null;
}

export default function PlannerMap({ recommendations, stationCatalog, selectedCandidateId, onSelect }: PlannerMapProps) {
  return (
    <div className="planner-map-shell">
      <MapContainer center={HCMC_CENTER} zoom={11} className="planner-map" scrollWheelZoom>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitMapItems items={recommendations} stations={stationCatalog} />
        {stationCatalog.map((station) => (
          <CircleMarker
            key={`station-${station.properties.station_id}`}
            center={[station.geometry.coordinates[1], station.geometry.coordinates[0]]}
            radius={5}
            pathOptions={{ color: "#ffffff", weight: 1.5, fillColor: "#627a89", fillOpacity: 0.82 }}
          >
            <Popup>
              <strong>{station.properties.name}</strong>
              <br />Danh mục trạm · nguồn: {station.properties.source_provider ?? "chưa rõ"} · cập nhật: {station.properties.source_updated_at ? new Date(station.properties.source_updated_at).toLocaleString("vi-VN") : "chưa rõ"}
              <br />Trường synthetic: {station.properties.synthetic_fields?.length ? station.properties.synthetic_fields.join(", ") : station.properties.synthetic_fields ? "không có" : "chưa rõ"}
            </Popup>
          </CircleMarker>
        ))}
        {recommendations.map((item) => {
          const selected = item.candidate_id === selectedCandidateId;
          return (
            <CircleMarker
              key={item.candidate_id}
              center={[item.location.lat, item.location.lon]}
              radius={selected ? 11 : 8}
              pathOptions={{
                color: selected ? "#123d35" : "#ffffff",
                weight: selected ? 4 : 2,
                fillColor: item.eligibility === "eligible" ? "#2f9e74" : "#e3a526",
                fillOpacity: 0.95,
              }}
              eventHandlers={{ click: () => onSelect(item.candidate_id) }}
            >
              <Popup>
                <strong>#{item.rank} · {item.candidate_id}</strong>
                <br />Điểm kỹ thuật: {item.technical_score.toFixed(1)}/100
                <br />Mức bằng chứng: {(item.evidence_coverage * 100).toFixed(0)}%
              </Popup>
            </CircleMarker>
          );
        })}
      </MapContainer>
      {recommendations.length === 0 && stationCatalog.length === 0 && (
        <div className="planner-map-empty">
          <strong>Chưa có điểm dữ liệu để vẽ</strong>
          <span>Candidate xuất hiện sau khi planning snapshot M1/M2 sẵn sàng.</span>
        </div>
      )}
      <div className="planner-map-legend" aria-label="Chú giải bản đồ">
        <span><i className="planner-map-dot station" />Danh mục trạm</span>
        <span><i className="planner-map-dot eligible" />Đủ điều kiện</span>
        <span><i className="planner-map-dot conditional" />Cần xác minh</span>
      </div>
    </div>
  );
}
