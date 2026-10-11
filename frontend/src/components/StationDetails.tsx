import type { RecommendationItem, Station, StationStatus } from "../types";

interface StationDetailsProps {
  station: Station | null;
  status: StationStatus | null;
  recommendation: RecommendationItem | null;
}

export default function StationDetails({ station, status, recommendation }: StationDetailsProps) {
  if (!station) {
    return <aside className="station-details empty-state">Chọn một marker hoặc recommendation để xem chi tiết.</aside>;
  }
  const properties = station.properties;
  return (
    <aside className="station-details">
      <div className="detail-title">
        <div>
          <span className={`access-badge access-${properties.access}`}>{properties.access}</span>
          <h2>{properties.name}</h2>
          <p>{properties.address}</p>
        </div>
        {status && <span className={`availability-dot ${status.operational_ports === 0 ? "offline" : status.available_ports > 0 ? "available" : "busy"}`} />}
      </div>

      <div className="detail-grid">
        <div><span>Đầu sạc</span><strong>{properties.connectors.map((item) => `${item.type} ${item.max_power_kw} kW ×${item.count}`).join(", ")}</strong></div>
        <div><span>Cổng hoạt động</span><strong>{status ? `${status.operational_ports}/${status.total_ports}` : "—"}</strong></div>
        <div><span>Đang trống</span><strong>{status?.available_ports ?? "—"}</strong></div>
        <div><span>Đang sử dụng</span><strong>{status?.occupied_ports ?? "—"}</strong></div>
        <div><span>Hàng chờ</span><strong>{status?.queue_length == null ? "—" : `${status.queue_length} xe`}</strong></div>
        <div><span>Nguồn dự báo</span><strong>{recommendation?.prediction_source ?? "—"}</strong></div>
        <div><span>Thời gian chờ</span><strong>{recommendation ? `${Math.round(recommendation.wait_min)} phút` : "—"}</strong></div>
        <div><span>Thời gian sạc</span><strong>{recommendation ? `${Math.round(recommendation.charge_min)} phút` : "—"}</strong></div>
        <div><span>Tổng thời gian</span><strong>{recommendation ? `${Math.round(recommendation.total_min)} phút` : "—"}</strong></div>
      </div>
    </aside>
  );
}
