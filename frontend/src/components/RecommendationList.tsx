import type {
  CandidateExclusion,
  RecommendationItem,
  Station,
  UnreachableStationFallback,
} from "../types";

interface RecommendationListProps {
  items: RecommendationItem[];
  outcome: "direct_no_charge" | "charging_stops" | "no_reachable_station" | null;
  exclusions: CandidateExclusion[];
  fallbackCandidate?: UnreachableStationFallback | null;
  resultFlags?: string[];
  candidateLimit?: number | null;
  stations: Station[];
  selectedStationId: string | null;
  hasRun: boolean;
  onSelect: (item: RecommendationItem) => void;
}

const reasonLabels: Record<string, string> = {
  NON_PUBLIC_ACCESS: "Trạm hạn chế truy cập",
  STATION_OFFLINE: "Trạm đang offline",
  UNKNOWN_PORT_STATUS: "Chưa xác định được trạng thái cổng sạc",
  NO_COMPATIBLE_CONNECTOR: "Không tương thích đầu sạc",
  INSUFFICIENT_SOC_RESERVE: "Không đủ SOC dự phòng để tới trạm",
  ROUTE_NOT_AVAILABLE: "Chưa có tuyến đường phù hợp",
  STALE_STATUS: "Trạng thái trạm đã cũ",
  SYNTHETIC_STATION_DATA: "Trạm đang dùng dữ liệu mô phỏng",
  SYNTHETIC_OR_UNVERIFIED_STATUS: "Trạng thái chưa được xác minh",
  WAIT_INPUT_UNAVAILABLE: "Thiếu dữ liệu hàng chờ hoặc thời lượng phiên sạc",
  ACTIVE_SAFETY_INCIDENT: "Trạm đang có cảnh báo an toàn đã được xác minh",
  ACTIVE_ACCESS_INCIDENT: "Trạm đang có vấn đề tiếp cận đã được xác minh",
  COMPATIBLE_PORT_TELEMETRY_UNAVAILABLE: "Thiếu trạng thái cổng tương thích",
  COMPATIBLE_PORT_STATUS_UNKNOWN: "Chưa xác định được trạng thái cổng tương thích",
  NO_COMPATIBLE_PORT_AVAILABLE: "Không có cổng tương thích đang hoạt động",
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

      {props.hasRun && props.resultFlags?.includes("RECOMMENDATION_CANDIDATE_LIMIT_REACHED") && (
        <div className="empty-state warning" role="status">
          Có nhiều trạm trong hành lang tuyến. Kết quả chỉ xét nhóm {props.candidateLimit ?? "giới hạn cấu hình"} trạm gần tuyến nhất.
        </div>
      )}

      {!props.hasRun && <div className="empty-state">Nhập hành trình để xem xếp hạng trạm sạc.</div>}
      {props.hasRun && props.items.length === 0 && (
        <div className={`empty-state ${props.outcome === "direct_no_charge" ? "success" : "warning"}`}>
          {props.outcome === "direct_no_charge"
            ? "Chưa có trạm sạc nào được đề xuất cho hành trình này."
            : "Không tìm thấy trạm sạc khả thi cho hành trình này."}
        </div>
      )}

      {props.hasRun && props.outcome === "no_reachable_station" && props.fallbackCandidate && (
        <div className="empty-state warning unreachable-fallback" role="note">
          <strong>Trạm gần nhất trong catalog: {props.fallbackCandidate.station_name}</strong>
          <span>{(props.fallbackCandidate.straight_line_distance_m / 1000).toFixed(1)} km theo đường chim bay</span>
          <span>Ứng viên này không đáp ứng điều kiện để thành khuyến nghị khả thi và không phải lựa chọn an toàn.</span>
          <small>{props.fallbackCandidate.reason_codes.map((reason) => reasonLabels[reason] ?? reason).join(", ")}</small>
        </div>
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
              <span className="total-time">{minutes(item.total_time_min)} tổng thời gian đến đích</span>
              <span className="metric-row">
                <span><b>{minutes(item.drive_to_station_min)}</b> đến trạm</span>
                <span title="Ước tính tại thời điểm tới trạm, có điều chỉnh theo occupancy dự báo và hàng chờ đã quan sát."><b>{minutes(item.wait_expected_min ?? item.estimated_wait_min)}</b> chờ dự kiến</span>
                <span><b>{minutes(item.charge_min ?? item.estimated_charge_min)}</b> sạc</span>
                <span><b>{minutes(item.drive_station_to_destination_min)}</b> đi tiếp</span>
              </span>
              <small>{Math.round(item.arrival_soc * 100)}% pin khi tới trạm · {item.soc_after_charge == null ? "—" : `${Math.round(item.soc_after_charge * 100)}% sau sạc`} · {Math.round(item.destination_soc * 100)}% khi đến đích · {item.prediction_source}{item.model_version ? ` · model ${item.model_version}` : ""}</small>
              <small>{item.predicted_free_ports == null ? "Chưa có dự báo số cổng trống" : `Dự báo ${item.predicted_free_ports.toFixed(1)} cổng trống khi tới trạm`}</small>
              <small>
                Xác suất phải chờ theo tải trạm: {item.wait_probability == null ? "—" : `${Math.round(item.wait_probability * 100)}%`} ·
                P90 lý thuyết {item.wait_p90_min == null ? "—" : minutes(item.wait_p90_min)}
                {item.wait_method === "erlang_c" ? " (Erlang C, chưa hiệu chuẩn vận hành)" : " (giới hạn chấm điểm)"}
              </small>
              {item.flags.includes("OBSERVED_HISTORY_UNAVAILABLE") && (
                <small className="fallback-note">Thiếu lịch sử occupancy quan sát được; dự báo đang dùng persistence fallback.</small>
              )}
              {item.flags.includes("LEG_METRICS_APPROXIMATED") && (
                <small className="fallback-note">Thời gian từng chặng được ước tính từ hình học tuyến.</small>
              )}
              {item.flags.includes("CONNECTOR_SCOPED_WAIT_APPROXIMATED") && (
                <small className="fallback-note">Thời gian chờ dùng số cổng tương thích; occupancy, queue khi thiếu connector detail và nhu cầu tương lai được xấp xỉ từ số liệu toàn trạm.</small>
              )}
            </span>
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
