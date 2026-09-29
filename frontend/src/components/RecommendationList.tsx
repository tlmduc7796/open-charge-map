import type { CandidateExclusion, RecommendationItem, Station, Vehicle } from "../types";
import { socToRangeKm } from "../vehicleRange";

interface RecommendationListProps {
  items: RecommendationItem[];
  exclusions: CandidateExclusion[];
  stations: Station[];
  vehicle: Vehicle | null;
  selectedStationId: string | null;
  hasRun: boolean;
  onSelect: (item: RecommendationItem) => void;
}

const reasonLabels: Record<string, string> = {
  NON_PUBLIC_ACCESS: "Trạm hạn chế truy cập",
  STATION_OFFLINE: "Trạm đang offline",
  NO_COMPATIBLE_CONNECTOR: "Không tương thích đầu sạc",
  INSUFFICIENT_SOC_RESERVE: "Phương tiện không đủ pin để tới",
  ROUTE_NOT_AVAILABLE: "Chưa có tuyến đường phù hợp",
};

const minutes = (value: number) => `${Math.round(value)} phút`;

export default function RecommendationList(props: RecommendationListProps) {
  const stationNames = Object.fromEntries(
    props.stations.map((station) => [station.properties.station_id, station.properties.name]),
  );
  return (
    <section className="recommendation-panel" aria-labelledby="recommendation-title">
      <div className="section-heading compact">
        <div>
          <span className="step-label">02 · Kết quả</span>
          <h2 id="recommendation-title">Trạm được đề xuất</h2>
        </div>
        {props.items.length > 0 && <span className="result-count">{props.items.length} trạm hợp lệ</span>}
      </div>

      {!props.hasRun && <div className="empty-state">Nhập hành trình để xem xếp hạng trạm sạc.</div>}
      {props.hasRun && props.items.length === 0 && (
        <div className="empty-state warning">Không có trạm tương thích và reachable cho hành trình này.</div>
      )}

      <div className="recommendation-list">
        {props.items.map((item) => (
          <button
            type="button"
            className={`recommendation-card ${props.selectedStationId === item.station_id ? "selected" : ""}`}
            key={item.station_id}
            onClick={() => props.onSelect(item)}
          >
            <span className="rank">#{item.rank}</span>
            <span className="card-main">
              <strong>{item.station_name}</strong>
              <small>{item.matched_connectors.join(" · ")} · {item.effective_power_kw} kW</small>
              <span className="metric-row">
                <span><b>{minutes(item.estimated_wait_min)}</b> chờ</span>
                <span><b>{minutes(item.estimated_charge_min)}</b> sạc</span>
                <span><b>+{item.detour_min.toFixed(1)} phút</b> detour</span>
                <span>
                  <b>{props.vehicle ? `${Math.round(socToRangeKm(item.arrival_soc, props.vehicle))} km` : "—"}</b> còn lại khi tới
                </span>
              </span>
            </span>
            <span className="score">{Math.round(item.final_score * 100)}</span>
          </button>
        ))}
      </div>

      {props.hasRun && props.exclusions.length > 0 && (
        <details className="exclusion-list">
          <summary>{props.exclusions.length} trạm đã bị loại</summary>
          {props.exclusions.map((item) => (
            <p key={item.station_id}>
              <strong>{stationNames[item.station_id] ?? item.station_id}</strong>
              <span>{item.reason_codes.map((reason) => reasonLabels[reason] ?? reason).join(", ")}</span>
            </p>
          ))}
        </details>
      )}
    </section>
  );
}
