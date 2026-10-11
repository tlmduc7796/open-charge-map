import type { CandidateExclusion, RecommendationItem, Station, Vehicle } from "../types";
import { socToRangeKm } from "../vehicleRange";

interface RecommendationListProps {
  items: RecommendationItem[];
  exclusions: CandidateExclusion[];
  stations: Station[];
  vehicle: Vehicle | null;
  selectedStationId: string | null;
  hasRun: boolean;
  notice?: string | null;
  title?: string;
  emptyMessage?: string;
  onSelect: (item: RecommendationItem) => void;
}

const reasonLabels: Record<string, string> = {
  NON_PUBLIC_ACCESS: "Trạm hạn chế truy cập",
  STATION_OFFLINE: "Trạm đang offline hoặc chưa có trạng thái",
  NO_COMPATIBLE_CONNECTOR: "Không tương thích đầu sạc",
  INSUFFICIENT_SOC_RESERVE: "Phương tiện không đủ pin để tới",
  ROUTE_NOT_AVAILABLE: "Chưa có tuyến đường phù hợp",
  WAIT_INPUT_UNAVAILABLE: "Chưa có dữ liệu hàng chờ để ước lượng",
  OPENING_HOURS_UNVERIFIED: "Chưa xác minh giờ mở cửa",
};

const minutes = (value: number) => `${Math.round(value)} phút`;

export default function RecommendationList(props: RecommendationListProps) {
  const stationsById = Object.fromEntries(
    props.stations.map((station) => [station.properties.station_id, station]),
  );
  return (
    <section className="recommendation-panel" aria-labelledby="recommendation-title">
      <div className="section-heading compact">
        <div>
          <span className="step-label">02 · Kết quả</span>
          <h2 id="recommendation-title">{props.title ?? "Trạm được đề xuất"}</h2>
        </div>
        {props.items.length > 0 && <span className="result-count">{props.items.length} trạm hợp lệ</span>}
      </div>

      {!props.hasRun && <div className="empty-state">Nhập thông tin để xem trạm sạc phù hợp.</div>}
      {props.hasRun && props.notice && <div className="empty-state">{props.notice}</div>}
      {props.hasRun && !props.notice && props.items.length === 0 && (
        <div className="empty-state warning">{props.emptyMessage ?? "Không có trạm tương thích và tới được với mức pin hiện tại."}</div>
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
              <strong>{stationsById[item.station_id]?.properties.name ?? item.station_name}</strong>
              <small>
                {stationsById[item.station_id]?.properties.connectors
                  .map((connector) => `${connector.type} ${connector.max_power_kw} kW ×${connector.count}`)
                  .join(" · ") ?? item.connectors.join(" · ")}
              </small>
              <span className="metric-row">
                <span><b>{minutes(item.travel_min)}</b> di chuyển</span>
                <span>
                  <b>
                    {minutes(item.wait_min)}
                    {item.flags.includes("WAIT_DEFAULTED_MISSING_INPUTS") ? " · mặc định" : ""}
                  </b>
                  chờ
                </span>
                <span><b>{minutes(item.charge_min)}</b> sạc</span>
                <span>
                  <b>{props.vehicle ? `${Math.round(socToRangeKm(item.arrive_battery_pct / 100, props.vehicle))} km` : "—"}</b> còn lại khi tới
                </span>
              </span>
            </span>
            <span className="score" title="Tổng thời gian">{Math.round(item.total_min)}′</span>
          </button>
        ))}
      </div>

      {props.hasRun && props.exclusions.length > 0 && (
        <details className="exclusion-list">
          <summary>{props.exclusions.length} trạm đã bị loại</summary>
          {props.exclusions.map((item) => (
            <p key={item.station_id}>
              <strong>{stationsById[item.station_id]?.properties.name ?? item.station_id}</strong>
              <span>{item.reason_codes.map((reason) => reasonLabels[reason] ?? reason).join(", ")}</span>
            </p>
          ))}
        </details>
      )}
    </section>
  );
}
