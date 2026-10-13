import { useCallback, useEffect, useRef, useState } from "react";
import goongjs from "@goongmaps/goong-js";
import "@goongmaps/goong-js/dist/goong-js.css";
import { latLngBounds } from "leaflet";
import { CircleMarker, GeoJSON, MapContainer, Popup, TileLayer, useMap } from "react-leaflet";

import { hideGoongPoiLayers } from "../goongMapStyle";
import type { PlanningDemoSnapshotResponse, PlanningRecommendation } from "./types";

type Candidate = PlanningDemoSnapshotResponse["candidates"][number];
type ExistingSite = PlanningDemoSnapshotResponse["existing_sites"][number];
type DemandNode = PlanningDemoSnapshotResponse["demand_nodes"][number];
type BoundaryGeometry = PlanningDemoSnapshotResponse["snapshot"]["geometry"];

interface GoongLayerClickEvent {
  lngLat: { lat: number; lng: number };
  features?: Array<{ properties: Record<string, unknown> }>;
}

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

const HCMC_CENTER: [number, number] = [106.7009, 10.7769];
const BOUNDARY_SOURCE = "planner-boundary";
const BOUNDARY_FILL_LAYER = "planner-boundary-fill";
const BOUNDARY_LINE_LAYER = "planner-boundary-line";
const DEMAND_SOURCE = "planner-demand";
const DEMAND_LAYER = "planner-demand-layer";
const SITES_SOURCE = "planner-sites";
const SITES_LAYER = "planner-sites-layer";
const CANDIDATES_SOURCE = "planner-candidates";
const CANDIDATES_LAYER = "planner-candidates-layer";

function demandNodeFeature(node: DemandNode, coverageMinutes: number) {
  return {
    type: "Feature" as const,
    geometry: { type: "Point" as const, coordinates: [node.location.lon, node.location.lat] },
    properties: {
      demand_node_id: node.demand_node_id,
      covered: node.nearest_existing_access_minutes_proxy <= coverageMinutes,
      access_minutes: node.nearest_existing_access_minutes_proxy,
    },
  };
}

function existingSiteFeature(site: ExistingSite) {
  return {
    type: "Feature" as const,
    geometry: { type: "Point" as const, coordinates: [site.location.lon, site.location.lat] },
    properties: {
      site_id: site.site_id,
      charger_type: site.charger_type,
      port_count: site.port_count,
      power_kw: site.power_kw,
      source_ref: site.source_ref,
    },
  };
}

function candidateFeature(candidate: Candidate, item: PlanningRecommendation | undefined, selected: boolean) {
  return {
    type: "Feature" as const,
    geometry: { type: "Point" as const, coordinates: [candidate.location.lon, candidate.location.lat] },
    properties: {
      candidate_id: candidate.candidate_id,
      label: candidate.label,
      candidate_type: candidate.candidate_type,
      ranked: Boolean(item),
      eligible: item?.eligibility === "eligible",
      rank: item?.rank ?? null,
      technical_score: item?.technical_score ?? null,
      selected,
    },
  };
}

function PlannerMapLegendAndEmpty({
  isEmpty,
}: {
  isEmpty: boolean;
}) {
  return (
    <>
      {isEmpty && (
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
    </>
  );
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

function OsmPlannerMap({
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
      <PlannerMapLegendAndEmpty
        isEmpty={candidates.length === 0 && existingSites.length === 0 && demandNodes.length === 0}
      />
    </div>
  );
}

function GoongPlannerMap({
  recommendations,
  candidates,
  existingSites,
  demandNodes,
  boundaryGeometry,
  coverageMinutes,
  selectedCandidateId,
  onSelect,
  onFailure,
}: PlannerMapProps & { onFailure: () => void }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const activePopup = useRef<InstanceType<typeof goongjs.Popup> | null>(null);
  const [map, setMap] = useState<InstanceType<typeof goongjs.Map> | null>(null);
  const mapToken = import.meta.env.VITE_GOONG_MAPTILES_KEY;

  const latest = useRef({ onSelect, onFailure });
  useEffect(() => {
    latest.current = { onSelect, onFailure };
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
      zoom: 11,
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

  // Pilot boundary polygon, kept in its own source/layer pair so it can update in place.
  useEffect(() => {
    if (!map) return;
    const data = boundaryGeometry
      ? { type: "Feature" as const, properties: {}, geometry: boundaryGeometry }
      : { type: "FeatureCollection" as const, features: [] as unknown[] };
    const source = map.getSource(BOUNDARY_SOURCE);
    if (source) {
      source.setData(data);
      return;
    }
    map.addSource(BOUNDARY_SOURCE, { type: "geojson", data });
    map.addLayer({
      id: BOUNDARY_FILL_LAYER,
      type: "fill",
      source: BOUNDARY_SOURCE,
      paint: { "fill-color": "#b9dfcd", "fill-opacity": 0.12 },
    });
    map.addLayer({
      id: BOUNDARY_LINE_LAYER,
      type: "line",
      source: BOUNDARY_SOURCE,
      paint: { "line-color": "#28614f", "line-width": 2 },
    });
  }, [map, boundaryGeometry]);

  // Demand nodes, existing sites and candidates are drawn as GL circle layers rather than
  // one DOM element per node: the renderer composites them with the basemap on every frame,
  // so they never lag behind the tiles while panning or zooming the way JS-repositioned DOM
  // markers can once there are more than a handful of them.
  useEffect(() => {
    if (!map) return;
    const data = { type: "FeatureCollection" as const, features: demandNodes.map((node) => demandNodeFeature(node, coverageMinutes)) };
    const source = map.getSource(DEMAND_SOURCE);
    if (source) {
      source.setData(data);
      return;
    }
    map.addSource(DEMAND_SOURCE, { type: "geojson", data });
    map.addLayer({
      id: DEMAND_LAYER,
      type: "circle",
      source: DEMAND_SOURCE,
      paint: {
        "circle-radius": 4,
        "circle-color": ["case", ["get", "covered"], "#69a58b", "#9ba9a2"],
        "circle-stroke-width": 1,
        "circle-stroke-color": "#ffffff",
        "circle-opacity": 0.78,
      },
    });
  }, [map, demandNodes, coverageMinutes]);

  useEffect(() => {
    if (!map) return;
    const data = { type: "FeatureCollection" as const, features: existingSites.map(existingSiteFeature) };
    const source = map.getSource(SITES_SOURCE);
    if (source) {
      source.setData(data);
      return;
    }
    map.addSource(SITES_SOURCE, { type: "geojson", data });
    map.addLayer({
      id: SITES_LAYER,
      type: "circle",
      source: SITES_SOURCE,
      paint: {
        "circle-radius": 5,
        "circle-color": "#526c7a",
        "circle-stroke-width": 1.2,
        "circle-stroke-color": "#ffffff",
        "circle-opacity": 0.9,
      },
    });
  }, [map, existingSites]);

  useEffect(() => {
    if (!map) return;
    const byCandidateId = new Map(recommendations.map((item) => [item.candidate_id, item]));
    const data = {
      type: "FeatureCollection" as const,
      features: candidates.map((candidate) =>
        candidateFeature(candidate, byCandidateId.get(candidate.candidate_id), candidate.candidate_id === selectedCandidateId),
      ),
    };
    const source = map.getSource(CANDIDATES_SOURCE);
    if (source) {
      source.setData(data);
      return;
    }
    map.addSource(CANDIDATES_SOURCE, { type: "geojson", data });
    map.addLayer({
      id: CANDIDATES_LAYER,
      type: "circle",
      source: CANDIDATES_SOURCE,
      paint: {
        "circle-radius": ["case", ["get", "selected"], 10, ["get", "ranked"], 8, 6],
        "circle-color": ["case", ["!", ["get", "ranked"]], "#82958c", ["get", "eligible"], "#2f9e74", "#e3a526"],
        "circle-stroke-color": ["case", ["get", "selected"], "#123d35", "#ffffff"],
        "circle-stroke-width": ["case", ["get", "selected"], 3.5, 1.5],
        "circle-opacity": 0.95,
      },
    });
  }, [map, candidates, recommendations, selectedCandidateId]);

  // Click/hover handlers are registered once: layer ids are stable, so this never re-runs
  // while panning/zooming or when the underlying data changes (setData above is enough).
  useEffect(() => {
    if (!map) return;
    const canvas = map.getCanvas();
    const openPopup = (lngLat: { lat: number; lng: number }, html: string) => {
      activePopup.current?.remove();
      activePopup.current = new goongjs.Popup({ offset: 10 })
        .setLngLat([lngLat.lng, lngLat.lat])
        .setHTML(html)
        .addTo(map);
    };
    const handleDemandClick = (event: GoongLayerClickEvent) => {
      const props = event.features?.[0]?.properties;
      if (!props) return;
      const covered = Boolean(props.covered);
      openPopup(
        event.lngLat,
        `<strong>Demand node · ${props.demand_node_id}</strong><br/>` +
          `Gần trạm hiện hữu nhất: ${Number(props.access_minutes).toFixed(1)} phút proxy<br/>` +
          `${covered ? `Trong ngưỡng ${coverageMinutes} phút` : `Ngoài ngưỡng ${coverageMinutes} phút`}<br/>` +
          `Dữ liệu tổng hợp · profile normal`,
      );
    };
    const handleSiteClick = (event: GoongLayerClickEvent) => {
      const props = event.features?.[0]?.properties;
      if (!props) return;
      openPopup(
        event.lngLat,
        `<strong>Trạm hiện hữu · ${props.site_id}</strong><br/>` +
          `${props.charger_type} · ${props.port_count ?? "?"} cổng · ${props.power_kw ?? "Chưa rõ"} kW<br/>` +
          `Dữ liệu tổng hợp · ${props.source_ref ?? "nguồn chưa rõ"}`,
      );
    };
    const handleCandidateClick = (event: GoongLayerClickEvent) => {
      const props = event.features?.[0]?.properties;
      if (!props) return;
      const candidateId = String(props.candidate_id);
      latest.current.onSelect(candidateId);
      const ranked = Boolean(props.ranked);
      openPopup(
        event.lngLat,
        `<strong>${ranked ? `#${props.rank} · ` : "Candidate · "}${props.label}</strong><br/>` +
          `${candidateId} · ${props.candidate_type}` +
          (ranked ? `<br/>Điểm kỹ thuật: ${Number(props.technical_score).toFixed(1)}/100` : "") +
          `<br/>Giả thuyết vị trí tổng hợp · cần xác minh site thực tế`,
      );
    };
    const pointerEnter = () => { canvas.style.cursor = "pointer"; };
    const pointerLeave = () => { canvas.style.cursor = ""; };
    map.on("click", DEMAND_LAYER, handleDemandClick);
    map.on("click", SITES_LAYER, handleSiteClick);
    map.on("click", CANDIDATES_LAYER, handleCandidateClick);
    for (const layerId of [DEMAND_LAYER, SITES_LAYER, CANDIDATES_LAYER]) {
      map.on("mouseenter", layerId, pointerEnter);
      map.on("mouseleave", layerId, pointerLeave);
    }
    return () => {
      map.off("click", DEMAND_LAYER, handleDemandClick);
      map.off("click", SITES_LAYER, handleSiteClick);
      map.off("click", CANDIDATES_LAYER, handleCandidateClick);
      for (const layerId of [DEMAND_LAYER, SITES_LAYER, CANDIDATES_LAYER]) {
        map.off("mouseenter", layerId, pointerEnter);
        map.off("mouseleave", layerId, pointerLeave);
      }
      activePopup.current?.remove();
      activePopup.current = null;
    };
  }, [map, coverageMinutes]);

  useEffect(() => {
    if (!map) return;
    const points: [number, number][] = [
      ...candidates.map(({ location }) => [location.lon, location.lat] as [number, number]),
      ...existingSites.map(({ location }) => [location.lon, location.lat] as [number, number]),
      ...demandNodes.map(({ location }) => [location.lon, location.lat] as [number, number]),
    ];
    if (points.length === 0) return;
    let minLon = points[0][0];
    let maxLon = points[0][0];
    let minLat = points[0][1];
    let maxLat = points[0][1];
    for (const [lon, lat] of points) {
      minLon = Math.min(minLon, lon);
      maxLon = Math.max(maxLon, lon);
      minLat = Math.min(minLat, lat);
      maxLat = Math.max(maxLat, lat);
    }
    map.fitBounds([[minLon, minLat], [maxLon, maxLat]], { padding: 48, maxZoom: 12 });
  }, [map, candidates, existingSites, demandNodes]);

  return (
    <div className="planner-map-shell">
      <div className="planner-map" ref={containerRef} aria-label="Bản đồ Goong planner" />
      <PlannerMapLegendAndEmpty
        isEmpty={candidates.length === 0 && existingSites.length === 0 && demandNodes.length === 0}
      />
    </div>
  );
}

export default function PlannerMap(props: PlannerMapProps) {
  const hasGoongKey = Boolean(import.meta.env.VITE_GOONG_MAPTILES_KEY);
  const [useFallback, setUseFallback] = useState(!hasGoongKey);
  const handleFailure = useCallback(() => setUseFallback(true), []);

  if (useFallback) return <OsmPlannerMap {...props} />;
  return <GoongPlannerMap {...props} onFailure={handleFailure} />;
}
