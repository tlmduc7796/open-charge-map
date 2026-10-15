import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import goongjs from "@goongmaps/goong-js";
import "@goongmaps/goong-js/dist/goong-js.css";
import { latLngBounds, type CircleMarker as LeafletCircleMarker } from "leaflet";
import { CircleMarker, GeoJSON, MapContainer, Popup, TileLayer, useMap } from "react-leaflet";

import { hideGoongPoiLayers } from "../goongMapStyle";
import {
  DEMAND_COLORS, DEMAND_LABELS, DEMAND_SCENARIO_LABELS, demandColor, demandFeature,
  demandAccessSummary, demandScale, visibleDemandNodes, weeklyDemand, type DemandScenario,
} from "./demandHeatmap";
import type { PlanningDemoSnapshotResponse, PlanningRecommendation } from "./types";
import StationLoadPanel from "./StationLoadPanel";
import { LOAD_STYLES, loadPercent, type LoadSimulation, type StationLoad } from "./stationLoad";

type Candidate = PlanningDemoSnapshotResponse["candidates"][number];
type ExistingSite = PlanningDemoSnapshotResponse["existing_sites"][number];
type DemandNode = PlanningDemoSnapshotResponse["demand_nodes"][number];
type BoundaryGeometry = PlanningDemoSnapshotResponse["snapshot"]["geometry"];

interface GoongLayerClickEvent {
  lngLat: { lat: number; lng: number };
  features?: Array<{ properties: Record<string, unknown> }>;
}

interface PlannerMapProps {
  loadSimulation?: LoadSimulation | null;
  loadRunId?: string | null;
  recommendations: PlanningRecommendation[];
  candidates: Candidate[];
  existingSites: ExistingSite[];
  demandNodes: DemandNode[];
  boundaryGeometry: BoundaryGeometry | null;
  coverageMinutes: number;
  demandScenario: DemandScenario;
  selectedCandidateIds: string[];
  selectedCandidateId: string | null;
  onSelect: (candidateId: string) => void;
}

interface PlannerMapDisplayProps extends PlannerMapProps {
  stationLoads: Record<string, StationLoad>;
  onlyUncovered: boolean;
  onToggleUncovered: () => void;
  showExistingSites: boolean;
  onToggleExistingSites: () => void;
}

const HCMC_CENTER: [number, number] = [106.7009, 10.7769];
const BOUNDARY_SOURCE = "planner-boundary";
const BOUNDARY_FILL_LAYER = "planner-boundary-fill";
const DEMAND_SOURCE = "planner-demand";
const DEMAND_HEAT_LAYER = "planner-demand-heatmap";
const SITES_SOURCE = "planner-sites";
const SITES_LAYER = "planner-sites-layer";
const CANDIDATES_SOURCE = "planner-candidates";
const CANDIDATES_LAYER = "planner-candidates-layer";
const MARKER_COLORS = { station: "#16a34a", selected: "#2563eb", ranked: "#7c3aed" };
const EMPTY_STATION_LOADS: Record<string, StationLoad> = {};

function candidateColor(ranked: boolean, focused: boolean) {
  if (focused) return MARKER_COLORS.selected;
  if (ranked) return MARKER_COLORS.ranked;
  return MARKER_COLORS.selected;
}

function existingSiteFeature(site: ExistingSite, load: StationLoad | undefined) {
  return {
    type: "Feature" as const,
    geometry: { type: "Point" as const, coordinates: [site.location.lon, site.location.lat] },
    properties: {
      site_id: site.site_id,
      unit_name: site.unit_name ?? "",
      charger_type: site.charger_type,
      port_count: site.port_count,
      power_kw: site.power_kw,
      source_ref: site.source_ref,
      marker_color: load ? LOAD_STYLES[load.level].color : MARKER_COLORS.station,
      marker_radius: load?.utilization !== null && load?.utilization !== undefined && load.utilization > 1 ? 7 : 5,
      load_text: load ? `${loadPercent(load.utilization)} · ${LOAD_STYLES[load.level].label}` : "",
      load_sessions: load?.sessions ?? null,
      load_capacity: load?.capacity ?? null,
    },
  };
}

function candidateFeature(candidate: Candidate, item: PlanningRecommendation | undefined, selected: boolean, load?: StationLoad) {
  return {
    type: "Feature" as const,
    geometry: { type: "Point" as const, coordinates: [candidate.location.lon, candidate.location.lat] },
    properties: {
      candidate_id: candidate.candidate_id,
      label: candidate.label,
      unit_name: candidate.unit_name ?? "",
      candidate_type: candidate.candidate_type,
      ranked: Boolean(item),
      marker_color: candidateColor(Boolean(item), selected),
      rank: item?.rank ?? null,
      technical_score: item?.technical_score ?? null,
      selected,
      marker_radius: selected ? 10 : item ? 8 : 7,
      load_text: load ? `${loadPercent(load.utilization)} · ${LOAD_STYLES[load.level].label}` : "",
    },
  };
}

function PlannerMapLegendAndEmpty({
  isEmpty,
  demandNodes,
  demandScenario,
  coverageMinutes,
  onlyUncovered,
  onToggleUncovered,
  showExistingSites,
  onToggleExistingSites,
}: {
  isEmpty: boolean;
  demandNodes: DemandNode[];
  demandScenario: DemandScenario;
  coverageMinutes: number;
  onlyUncovered: boolean;
  onToggleUncovered: () => void;
  showExistingSites: boolean;
  onToggleExistingSites: () => void;
}) {
  const format = (value: number) => value.toLocaleString("vi-VN", { maximumFractionDigits: 0 });
  const access = demandAccessSummary(demandNodes, demandScenario, coverageMinutes);
  return (
    <>
      {isEmpty && (
        <div className="planner-map-empty">
          <strong>Đang tải dữ liệu bản đồ</strong>
          <span>Các vùng nhu cầu và địa điểm sẽ xuất hiện khi dữ liệu sẵn sàng.</span>
        </div>
      )}
      <div className="planner-map-legend" aria-label="Chú giải bản đồ">
        <label className="planner-station-toggle">
          <input type="checkbox" checked={showExistingSites} onChange={onToggleExistingSites} />
          <i className="planner-map-dot station" />Trạm hiện hữu
        </label>
        <span><i className="planner-map-dot ranked" />Đã có thứ hạng</span>
        <span><i className="planner-map-dot selected" />Đang chọn</span>
      </div>
      {!isEmpty && (
        <div className="planner-heatmap-legend" aria-label="Chú giải nhu cầu">
          <div className="planner-heatmap-heading"><strong>Nhu cầu sạc</strong><span>{DEMAND_SCENARIO_LABELS[demandScenario]}</span></div>
          <div className="planner-heatmap-scale">
            {DEMAND_LABELS.map((label, index) => (
              <span key={label}><i style={{ background: DEMAND_COLORS[index] }} /><b>{label}</b></span>
            ))}
          </div>
          <p>{access.missingDemand === 0 ? `${format(access.total)} lượt dự kiến/tuần` : "— lượt/tuần"}</p>
          <span className="planner-heatmap-access-key">Ngoài {coverageMinutes} phút: <b>{access.outsidePercent === null ? "—" : `${format(access.outsidePercent)}% nhu cầu`}</b></span>
          <label className="planner-heatmap-filter">
            <input type="checkbox" checked={onlyUncovered} onChange={onToggleUncovered} />
            Chỉ xem vùng xa trạm (&gt; {coverageMinutes} phút)
          </label>
          {onlyUncovered && access.outside === 0 && <p className="planner-filter-empty">Không có vùng nhu cầu ngoài ngưỡng đang chọn.</p>}
        </div>
      )}
    </>
  );
}

// The fallback draws the same data-driven heat colors on a canvas below map markers.
// No plugin or extra tile service is needed; pan/zoom keep the overlay aligned with Leaflet.
function LeafletDemandHeatmap({ demandNodes, demandScenario, coverageMinutes, onlyUncovered }: Pick<PlannerMapDisplayProps, "demandNodes" | "demandScenario" | "coverageMinutes" | "onlyUncovered">) {
  const map = useMap();
  useEffect(() => {
    const pane = map.getPane("planner-demand-heat") ?? map.createPane("planner-demand-heat");
    pane.style.zIndex = "350";
    pane.style.pointerEvents = "none";
    const canvas = document.createElement("canvas");
    canvas.style.position = "absolute";
    canvas.style.pointerEvents = "none";
    canvas.setAttribute("aria-hidden", "true");
    pane.appendChild(canvas);
    const scale = demandScale(demandNodes);
    const draw = () => {
      const size = map.getSize();
      const topLeft = map.containerPointToLayerPoint([0, 0]);
      const ratio = window.devicePixelRatio || 1;
      canvas.width = size.x * ratio;
      canvas.height = size.y * ratio;
      Object.assign(canvas.style, { width: `${size.x}px`, height: `${size.y}px`, left: `${topLeft.x}px`, top: `${topLeft.y}px` });
      const context = canvas.getContext("2d");
      if (!context) return;
      context.scale(ratio, ratio);
      const radius = Math.max(24, Math.min(72, 24 + (map.getZoom() - 10) * 8));
      for (const node of visibleDemandNodes(demandNodes, demandScenario, coverageMinutes, onlyUncovered)) {
        const value = weeklyDemand(node, demandScenario);
        if (value === null || value <= 0) continue;
        const point = map.latLngToContainerPoint([node.location.lat, node.location.lon]);
        const color = demandColor(value, scale.thresholds);
        const gradient = context.createRadialGradient(point.x, point.y, 0, point.x, point.y, radius);
        gradient.addColorStop(0, `${color}b3`);
        gradient.addColorStop(0.45, `${color}60`);
        gradient.addColorStop(1, `${color}00`);
        context.globalAlpha = 0.35 + 0.65 * value / scale.maximum;
        context.fillStyle = gradient;
        context.fillRect(point.x - radius, point.y - radius, radius * 2, radius * 2);
      }
    };
    draw();
    map.on("move zoom resize", draw);
    return () => { map.off("move zoom resize", draw); canvas.remove(); };
  }, [map, demandNodes, demandScenario, coverageMinutes, onlyUncovered]);
  return null;
}

function FitMapItems({
  candidates,
  existingSites,
  demandNodes,
}: Pick<PlannerMapProps, "candidates" | "existingSites" | "demandNodes">) {
  const map = useMap();
  useEffect(() => {
    const observer = new ResizeObserver(() => map.invalidateSize({ pan: false, debounceMoveend: true }));
    observer.observe(map.getContainer());
    return () => observer.disconnect();
  }, [map]);
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
  demandScenario,
  selectedCandidateIds,
  selectedCandidateId,
  onSelect,
  onlyUncovered,
  onToggleUncovered,
  showExistingSites,
  onToggleExistingSites,
  stationLoads,
}: PlannerMapDisplayProps) {
  const byCandidateId = new Map(recommendations.map((item) => [item.candidate_id, item]));
  const siteMarkers = useRef(new Map<string, LeafletCircleMarker>());
  const candidateMarkers = useRef(new Map<string, LeafletCircleMarker>());
  useEffect(() => {
    // Keep selected candidates above existing stations.
    for (const marker of siteMarkers.current.values()) marker.bringToFront();
    for (const marker of candidateMarkers.current.values()) marker.bringToFront();
  }, [candidates, existingSites, recommendations, selectedCandidateId, selectedCandidateIds, showExistingSites]);
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
        <LeafletDemandHeatmap demandNodes={demandNodes} demandScenario={demandScenario} coverageMinutes={coverageMinutes} onlyUncovered={onlyUncovered} />
        {boundaryFeature && (
          <GeoJSON
            data={boundaryFeature as GeoJSON.GeoJsonObject}
            interactive={false}
            style={() => ({ stroke: false, fillColor: "#b9dfcd", fillOpacity: 0.12 })}
          />
        )}
        {showExistingSites && existingSites.map((site) => (
          <CircleMarker
            key={`site-${site.site_id}`}
            ref={(marker) => { if (marker) siteMarkers.current.set(site.site_id, marker); else siteMarkers.current.delete(site.site_id); }}
            center={[site.location.lat, site.location.lon]}
            radius={(stationLoads[site.site_id]?.utilization ?? 0) > 1 ? 7 : 5}
            pathOptions={{ color: "#ffffff", weight: 1.2,
              fillColor: stationLoads[site.site_id] ? LOAD_STYLES[stationLoads[site.site_id].level].color : MARKER_COLORS.station, fillOpacity: 0.9 }}
          >
            <Popup>
              <strong>Trạm hiện hữu · {site.site_id}</strong>
              {site.unit_name && <><br />{site.unit_name}</>}
              <br />{site.charger_type} · {site.port_count ?? "?"} cổng · {site.power_kw ?? "Chưa rõ"} kW
              {stationLoads[site.site_id] && <><br />Mức tải: {loadPercent(stationLoads[site.site_id].utilization)} · {LOAD_STYLES[stationLoads[site.site_id].level].label}</>}
            </Popup>
          </CircleMarker>
        ))}
        {candidates.filter((candidate) => selectedCandidateIds.includes(candidate.candidate_id)).map((candidate) => {
          const item = byCandidateId.get(candidate.candidate_id);
          const selected = candidate.candidate_id === selectedCandidateId;
          return (
            <CircleMarker
              key={candidate.candidate_id}
              ref={(marker) => { if (marker) candidateMarkers.current.set(candidate.candidate_id, marker); else candidateMarkers.current.delete(candidate.candidate_id); }}
              center={[candidate.location.lat, candidate.location.lon]}
              radius={selected ? 10 : item ? 8 : 7}
              pathOptions={{
                color: selected ? "#1e3a8a" : "#ffffff",
                weight: selected ? 3.5 : 1.5,
                fillColor: candidateColor(Boolean(item), selected),
                fillOpacity: 0.95,
              }}
              eventHandlers={{ click: () => onSelect(candidate.candidate_id) }}
            >
              <Popup>
                <strong>{item ? `#${item.rank} · ` : "Ứng viên · "}{candidate.label}</strong>
                {candidate.unit_name && <><br />{candidate.unit_name}</>}
                {item && <><br />Điểm kỹ thuật: {item.technical_score.toFixed(1)}/100</>}
                {stationLoads[candidate.candidate_id] && <><br />Mức tải khi bổ sung: {loadPercent(stationLoads[candidate.candidate_id].utilization)}</>}
              </Popup>
            </CircleMarker>
          );
        })}
      </MapContainer>
      <PlannerMapLegendAndEmpty
        isEmpty={candidates.length === 0 && existingSites.length === 0 && demandNodes.length === 0}
        demandNodes={demandNodes} demandScenario={demandScenario}
        coverageMinutes={coverageMinutes} onlyUncovered={onlyUncovered} onToggleUncovered={onToggleUncovered}
        showExistingSites={showExistingSites} onToggleExistingSites={onToggleExistingSites}
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
  demandScenario,
  selectedCandidateIds,
  selectedCandidateId,
  onSelect,
  onFailure,
  onlyUncovered,
  onToggleUncovered,
  showExistingSites,
  onToggleExistingSites,
  stationLoads,
}: PlannerMapDisplayProps & { onFailure: () => void }) {
  const scale = useMemo(() => demandScale(demandNodes), [demandNodes]);
  const containerRef = useRef<HTMLDivElement>(null);
  const activePopup = useRef<InstanceType<typeof goongjs.Popup> | null>(null);
  const activePopupIsSite = useRef(false);
  const activePopupCandidateId = useRef<string | null>(null);
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
      paint: { "fill-color": "#b9dfcd", "fill-opacity": 0.12, "fill-antialias": false },
    });
  }, [map, boundaryGeometry]);

  // Demand points feed the heat layer internally; only station and candidate markers are shown.
  useEffect(() => {
    if (!map) return;
    const data = { type: "FeatureCollection" as const, features: visibleDemandNodes(demandNodes, demandScenario, coverageMinutes, onlyUncovered).map((node) => demandFeature(node, demandScenario, coverageMinutes, scale)) };
    const source = map.getSource(DEMAND_SOURCE);
    if (source) {
      source.setData(data);
      return;
    }
    map.addSource(DEMAND_SOURCE, { type: "geojson", data });
    map.addLayer({
      id: DEMAND_HEAT_LAYER,
      type: "heatmap",
      source: DEMAND_SOURCE,
      paint: {
        "heatmap-weight": ["get", "heat_weight"],
        "heatmap-intensity": 3.2,
        "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 10, 24, 13, 48, 16, 72],
        "heatmap-opacity": 0.65,
        "heatmap-color": ["interpolate", ["linear"], ["heatmap-density"],
          0, "rgba(250,204,21,0)", 0.2, "rgba(250,204,21,0.35)",
          0.4, "#fb923c", 0.65, "#f97316", 1, "#dc2626"],
      },
    });
  }, [map, demandNodes, coverageMinutes, demandScenario, scale, onlyUncovered]);

  useEffect(() => {
    if (!map) return;
    const data = { type: "FeatureCollection" as const, features: existingSites.map((site) => existingSiteFeature(site, stationLoads[site.site_id])) };
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
        "circle-radius": ["get", "marker_radius"],
        "circle-color": ["get", "marker_color"],
        "circle-stroke-width": 1.2,
        "circle-stroke-color": "#ffffff",
        "circle-opacity": 0.9,
      },
    });
  }, [map, existingSites, stationLoads]);

  useEffect(() => {
    // Popups must not retain numbers from the other comparison mode.
    activePopup.current?.remove();
    activePopup.current = null;
    activePopupCandidateId.current = null;
  }, [stationLoads]);

  useEffect(() => {
    if (!map || !map.getLayer(SITES_LAYER)) return;
    map.setLayoutProperty(SITES_LAYER, "visibility", showExistingSites ? "visible" : "none");
    if (!showExistingSites && activePopupIsSite.current) {
      activePopup.current?.remove();
      activePopup.current = null;
      activePopupIsSite.current = false;
    }
  }, [map, showExistingSites]);

  useEffect(() => {
    if (!map) return;
    if (activePopupCandidateId.current && !selectedCandidateIds.includes(activePopupCandidateId.current)) {
      activePopup.current?.remove();
      activePopup.current = null;
      activePopupCandidateId.current = null;
    }
    const byCandidateId = new Map(recommendations.map((item) => [item.candidate_id, item]));
    const data = {
      type: "FeatureCollection" as const,
      features: candidates.filter((candidate) => selectedCandidateIds.includes(candidate.candidate_id)).map((candidate) =>
        candidateFeature(candidate, byCandidateId.get(candidate.candidate_id), candidate.candidate_id === selectedCandidateId, stationLoads[candidate.candidate_id]),
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
        "circle-radius": ["get", "marker_radius"],
        "circle-color": ["get", "marker_color"],
        "circle-stroke-color": ["case", ["get", "selected"], "#1e3a8a", "#ffffff"],
        "circle-stroke-width": ["case", ["get", "selected"], 3.5, 1.5],
        "circle-opacity": 0.95,
      },
    });
  }, [map, candidates, recommendations, selectedCandidateIds, selectedCandidateId, stationLoads]);

  // Click/hover handlers are registered once: layer ids are stable, so this never re-runs
  // while panning/zooming or when the underlying data changes (setData above is enough).
  useEffect(() => {
    if (!map) return;
    const canvas = map.getCanvas();
    const openPopup = (lngLat: { lat: number; lng: number }, html: string, isSite = false) => {
      activePopup.current?.remove();
      activePopupIsSite.current = isSite;
      activePopupCandidateId.current = null;
      activePopup.current = new goongjs.Popup({ offset: 10 })
        .setLngLat([lngLat.lng, lngLat.lat])
        .setHTML(html)
        .addTo(map);
    };
    const handleSiteClick = (event: GoongLayerClickEvent) => {
      const props = event.features?.[0]?.properties;
      if (!props) return;
      openPopup(
        event.lngLat,
        `<strong>Trạm hiện hữu · ${props.site_id}</strong><br/>` +
          (props.unit_name ? `${props.unit_name}<br/>` : "") +
          `${props.charger_type} · ${props.port_count ?? "—"} cổng · ${props.power_kw ?? "—"} kW` +
          (props.load_text ? `<br/>Mức tải: ${props.load_text}` : ""),
        true,
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
        `<strong>${ranked ? `#${props.rank} · ` : "Ứng viên · "}${props.label}</strong><br/>` +
          (props.unit_name ? `${props.unit_name}<br/>` : "") +
          (ranked ? `Điểm kỹ thuật: ${Number(props.technical_score).toFixed(1)}/100` : "Địa điểm ứng viên") +
          (props.load_text ? `<br/>Mức tải khi bổ sung: ${props.load_text}` : ""),
      );
      activePopupCandidateId.current = candidateId;
    };
    const pointerEnter = () => { canvas.style.cursor = "pointer"; };
    const pointerLeave = () => { canvas.style.cursor = ""; };
    map.on("click", SITES_LAYER, handleSiteClick);
    map.on("click", CANDIDATES_LAYER, handleCandidateClick);
    for (const layerId of [SITES_LAYER, CANDIDATES_LAYER]) {
      map.on("mouseenter", layerId, pointerEnter);
      map.on("mouseleave", layerId, pointerLeave);
    }
    return () => {
      map.off("click", SITES_LAYER, handleSiteClick);
      map.off("click", CANDIDATES_LAYER, handleCandidateClick);
      for (const layerId of [SITES_LAYER, CANDIDATES_LAYER]) {
        map.off("mouseenter", layerId, pointerEnter);
        map.off("mouseleave", layerId, pointerLeave);
      }
      activePopup.current?.remove();
      activePopup.current = null;
    };
  }, [map]);

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
        demandNodes={demandNodes} demandScenario={demandScenario}
        coverageMinutes={coverageMinutes} onlyUncovered={onlyUncovered} onToggleUncovered={onToggleUncovered}
        showExistingSites={showExistingSites} onToggleExistingSites={onToggleExistingSites}
      />
    </div>
  );
}

export default function PlannerMap(props: PlannerMapProps) {
  const hasGoongKey = Boolean(import.meta.env.VITE_GOONG_MAPTILES_KEY);
  const [useFallback, setUseFallback] = useState(!hasGoongKey);
  const [onlyUncovered, setOnlyUncovered] = useState(false);
  const [showExistingSites, setShowExistingSites] = useState(true);
  const [baselineRunId, setBaselineRunId] = useState<string | null>(null);
  const showBaseline = Boolean(props.loadRunId && baselineRunId === props.loadRunId);
  const handleFailure = useCallback(() => setUseFallback(true), []);
  const displayProps = {
    ...props,
    onlyUncovered, onToggleUncovered: () => setOnlyUncovered((value) => !value),
    showExistingSites, onToggleExistingSites: () => setShowExistingSites((value) => !value),
    stationLoads: (showBaseline ? props.loadSimulation?.baseline : props.loadSimulation?.proposed)?.stations ?? EMPTY_STATION_LOADS,
  };

  return <>
    {props.loadSimulation && <StationLoadPanel simulation={props.loadSimulation} showBaseline={showBaseline}
      onBaselineChange={(value) => setBaselineRunId(value ? props.loadRunId ?? null : null)} />}
    {useFallback ? <OsmPlannerMap {...displayProps} /> : <GoongPlannerMap {...displayProps} onFailure={handleFailure} />}
  </>;
}
