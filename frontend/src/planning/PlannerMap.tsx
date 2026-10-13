import { useEffect } from "react";
import { latLngBounds } from "leaflet";
import { CircleMarker, GeoJSON, MapContainer, Popup, TileLayer, useMap } from "react-leaflet";

import type { PlanningDemoSnapshotResponse, PlanningRecommendation } from "./types";

type Candidate = PlanningDemoSnapshotResponse["candidates"][number];
type ExistingSite = PlanningDemoSnapshotResponse["existing_sites"][number];
type DemandNode = PlanningDemoSnapshotResponse["demand_nodes"][number];
type BoundaryGeometry = PlanningDemoSnapshotResponse["snapshot"]["geometry"];

interface PlannerMapProps {
  recommendations: PlanningRecommendation[];
  candidates: Candidate[];
  existingSites: ExistingSite[];
  demandNodes: DemandNode[];
  boundaryGeometry: BoundaryGeometry | null;
  coverageMinutes: number;
  selectedCandidateId: string | null;
  onSelect: (candidateId: string) => void;
}

function FitMapItems({
  candidates,
  existingSites,
  demandNodes,
}: Pick<PlannerMapProps, "candidates" | "existingSites" | "demandNodes">) {
  const map = useMap();
  useEffect(() => {
    const points = [
      ...candidates.map(({ location }) => [location.lat, location.lon] as [number, number]),
      ...existingSites.map(({ location }) => [location.lat, location.lon] as [number, number]),
      ...demandNodes.map(({ location }) => [location.lat, location.lon] as [number, number]),
    ];
    if (points.length > 0) map.fitBounds(latLngBounds(points), { padding: [34, 34], maxZoom: 12 });
  }, [candidates, demandNodes, existingSites, map]);
  return null;
}

export default function PlannerMap({
  recommendations,
  candidates,
  existingSites,
  demandNodes,
  boundaryGeometry,
  coverageMinutes,
  selectedCandidateId,
  onSelect,
}: PlannerMapProps) {
  const byCandidateId = new Map(recommendations.map((item) => [item.candidate_id, item]));
  const boundaryFeature = boundaryGeometry
    ? { type: "Feature" as const, properties: {}, geometry: boundaryGeometry }
    : null;

  return (
    <div className="planner-map-shell">
      <MapContainer center={[10.7769, 106.7009]} zoom={11} className="planner-map" scrollWheelZoom>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitMapItems candidates={candidates} existingSites={existingSites} demandNodes={demandNodes} />
        {boundaryFeature && (
          <GeoJSON
            data={boundaryFeature as GeoJSON.GeoJsonObject}
            style={() => ({ color: "#28614f", weight: 2, fillColor: "#b9dfcd", fillOpacity: 0.12 })}
          />
        )}
        {demandNodes.map((node) => {
          const covered = node.nearest_existing_access_minutes_proxy <= coverageMinutes;
          return (
            <CircleMarker
              key={`demand-${node.demand_node_id}`}
              center={[node.location.lat, node.location.lon]}
              radius={4}
              pathOptions={{
                color: "#ffffff",
                weight: 1,
                fillColor: covered ? "#69a58b" : "#9ba9a2",
                fillOpacity: 0.78,
              }}
            >
              <Popup>
                <strong>Demand node · {node.demand_node_id}</strong>
                <br />Gần trạm hiện hữu nhất: {node.nearest_existing_access_minutes_proxy.toFixed(1)} phút proxy
                <br />{covered ? `Trong ngưỡng ${coverageMinutes} phút` : `Ngoài ngưỡng ${coverageMinutes} phút`}
                <br />Dữ liệu tổng hợp · profile normal
              </Popup>
            </CircleMarker>
          );
        })}
        {existingSites.map((site) => (
          <CircleMarker
            key={`site-${site.site_id}`}
            center={[site.location.lat, site.location.lon]}
            radius={5}
            pathOptions={{ color: "#ffffff", weight: 1.2, fillColor: "#526c7a", fillOpacity: 0.9 }}
          >
            <Popup>
              <strong>Trạm hiện hữu · {site.site_id}</strong>
              <br />{site.charger_type} · {site.port_count ?? "?"} cổng · {site.power_kw ?? "Chưa rõ"} kW
              <br />Dữ liệu tổng hợp · {site.source_ref ?? "nguồn chưa rõ"}
            </Popup>
          </CircleMarker>
        ))}
        {candidates.map((candidate) => {
          const item = byCandidateId.get(candidate.candidate_id);
          const selected = candidate.candidate_id === selectedCandidateId;
          return (
            <CircleMarker
              key={candidate.candidate_id}
              center={[candidate.location.lat, candidate.location.lon]}
              radius={selected ? 10 : item ? 8 : 6}
              pathOptions={{
                color: selected ? "#123d35" : "#ffffff",
                weight: selected ? 3.5 : 1.5,
                fillColor: item
                  ? item.eligibility === "eligible" ? "#2f9e74" : "#e3a526"
                  : "#82958c",
                fillOpacity: 0.95,
              }}
              eventHandlers={{ click: () => onSelect(candidate.candidate_id) }}
            >
              <Popup>
                <strong>{item ? `#${item.rank} · ` : "Candidate · "}{candidate.label}</strong>
                <br />{candidate.candidate_id} · {candidate.candidate_type}
                {item && <><br />Điểm kỹ thuật: {item.technical_score.toFixed(1)}/100</>}
                <br />Giả thuyết vị trí tổng hợp · cần xác minh site thực tế
              </Popup>
            </CircleMarker>
          );
        })}
      </MapContainer>
      {candidates.length === 0 && existingSites.length === 0 && demandNodes.length === 0 && (
        <div className="planner-map-empty">
          <strong>Chưa tải được snapshot M1</strong>
          <span>Ranh giới, demand node và site sẽ xuất hiện sau khi API trả metadata.</span>
        </div>
      )}
      <div className="planner-map-legend" aria-label="Chú giải bản đồ">
        <span><i className="planner-map-dot station" />Trạm hiện hữu</span>
        <span><i className="planner-map-dot demand-covered" />Demand trong ngưỡng</span>
        <span><i className="planner-map-dot demand-gap" />Demand ngoài ngưỡng</span>
        <span><i className="planner-map-dot eligible" />Candidate được xếp hạng</span>
        <span><i className="planner-map-dot conditional" />Cần xác minh</span>
      </div>
    </div>
  );
}
