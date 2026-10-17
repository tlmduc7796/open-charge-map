import { useEffect, useMemo } from "react";
import { divIcon, latLngBounds } from "leaflet";
import { CircleMarker, MapContainer, Marker, Polygon, Polyline, Popup, TileLayer, Tooltip, useMap } from "react-leaflet";

import GapLegend from "./GapLegend";
import {
  cellOwnerId, cellStyles, cellTooltipLines, clusterIdsOf, roadTooltipLines, sortedRoads,
  stationColor, stationPopupHtml, stationRadius, type GapMapProps,
} from "./gapGeo";
import { roadFlowRange, roadWidth, trafficColor, type CellView } from "./gapFormat";
import type { GapCellItem } from "./gapTypes";

/** OpenStreetMap fallback used when there is no Goong maptiles key or Goong fails to load. */
function FitToCells({ cells }: { cells: GapCellItem[] }) {
  const map = useMap();
  useEffect(() => {
    if (!cells.length) return;
    const bounds = latLngBounds(cells.flatMap((cell) => [[cell.bounds[0], cell.bounds[1]], [cell.bounds[2], cell.bounds[3]]] as [number, number][]));
    map.fitBounds(bounds, { padding: [16, 16] });
  }, [cells, map]);
  return null;
}

function rankIcon(order: number, selected: boolean) {
  return divIcon({
    className: "gap-rank-marker-wrapper",
    html: `<span class="gap-rank-marker${selected ? " selected" : ""}">${order}</span>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  });
}

export default function GapLeafletMap({
  cells, roads, results, layer, stations, showStations, candidates, selectedCandidateId, onSelectCandidate,
}: GapMapProps) {
  const views = useMemo<CellView[]>(() => cells.map((item) => ({ item, result: results.get(item.cell_id) })), [cells, results]);
  const styles = useMemo(() => cellStyles(cells, results, layer), [cells, results, layer]);
  const flowRoads = useMemo(() => (layer === "flow" ? sortedRoads(roads) : []), [roads, layer]);
  const flowRange = useMemo(() => roadFlowRange(roads), [roads]);
  const clusterIds = useMemo(() => clusterIdsOf(candidates, selectedCandidateId), [candidates, selectedCandidateId]);

  return (
    <div className="gap-map-wrap">
      <MapContainer center={[10.78, 106.69]} zoom={13} className="gap-map" scrollWheelZoom preferCanvas>
        <TileLayer attribution="&copy; OpenStreetMap contributors" url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" />
        <FitToCells cells={cells} />
        {views.map(({ item, result }) => {
          const style = styles.get(item.cell_id);
          const inCluster = clusterIds.has(item.cell_id);
          const ownRing = Boolean(result?.own_overlap) && !result?.excluded_reason;
          const [title, ...rest] = cellTooltipLines(item, result);
          return (
            <Polygon
              key={item.cell_id}
              positions={item.polygon?.length ? item.polygon : [[
                [item.bounds[0], item.bounds[1]], [item.bounds[0], item.bounds[3]],
                [item.bounds[2], item.bounds[3]], [item.bounds[2], item.bounds[1]],
              ]]}
              pathOptions={{
                color: inCluster ? "#111827" : ownRing ? "#0f766e" : "#ffffff",
                weight: inCluster ? 2.5 : ownRing ? 1.4 : 0.4,
                dashArray: ownRing && !inCluster ? "4 3" : undefined,
                fillColor: style?.fillColor,
                fillOpacity: style?.fillOpacity,
              }}
              eventHandlers={{ click: () => onSelectCandidate(cellOwnerId(item.cell_id, candidates)) }}
            >
              <Tooltip sticky>
                <strong>{title}</strong>
                {rest.map((line) => <span key={line}><br />{line}</span>)}
              </Tooltip>
            </Polygon>
          );
        })}
        {flowRoads.map((road) => {
          const [title, ...rest] = roadTooltipLines(road, roads);
          return (
            <Polyline
              key={road.road_id}
              positions={road.coordinates}
              pathOptions={{
                color: trafficColor(road.flow_vph, flowRange[0], flowRange[1]), opacity: 0.92,
                weight: roadWidth(road.road_type) * 1.4, lineCap: "round", lineJoin: "round",
              }}
            >
              <Tooltip sticky>
                <strong>{title}</strong>
                {rest.map((line) => <span key={line}><br />{line}</span>)}
              </Tooltip>
            </Polyline>
          );
        })}
        {showStations && stations.map((station) => (
          <CircleMarker
            key={station.station_id}
            center={[station.lat, station.lon]}
            radius={stationRadius(station)}
            pathOptions={{ color: "#ffffff", weight: 1.5, fillOpacity: 0.95, fillColor: stationColor(station) }}
          >
            <Popup maxWidth={360} minWidth={300}>
              <div dangerouslySetInnerHTML={{ __html: stationPopupHtml(station) }} />
            </Popup>
          </CircleMarker>
        ))}
        {candidates.map((candidate) => (
          <Marker
            key={candidate.cell_id}
            position={[candidate.lat, candidate.lon]}
            icon={rankIcon(candidate.selection_order, candidate.cell_id === selectedCandidateId)}
            eventHandlers={{ click: () => onSelectCandidate(candidate.cell_id) }}
            zIndexOffset={candidate.cell_id === selectedCandidateId ? 1000 : 0}
          />
        ))}
      </MapContainer>
      <GapLegend layer={layer} views={views} roads={roads} />
    </div>
  );
}
