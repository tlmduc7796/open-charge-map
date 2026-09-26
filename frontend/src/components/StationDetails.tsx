import type { PlannedArrival, RecommendationItem, Station, StationStatus } from "../types";

interface StationDetailsProps {
  station: Station | null;
  status: StationStatus | null;
  recommendation: RecommendationItem | null;
  activeArrival: PlannedArrival | null;
  committing: boolean;
  onCommit: () => void;
  onCancel: () => void;
}

export default function StationDetails({
  station,
  status,
  recommendation,
  activeArrival,
  committing,
  onCommit,
  onCancel,
}: StationDetailsProps) {
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

      {properties.notes.length > 0 && (
        <div className="notice">{properties.notes.join(" ")}</div>
      )}

      <div className="detail-grid">
        <div><span>Đầu sạc</span><strong>{properties.connectors.map((item) => `${item.type} ${item.max_power_kw} kW ×${item.count}`).join(", ")}</strong></div>
        <div><span>Cổng hoạt động</span><strong>{status ? `${status.operational_ports}/${status.total_ports}` : "—"}</strong></div>
        <div><span>Đang trống</span><strong>{status?.available_ports ?? "—"}</strong></div>
        <div><span>Đang sử dụng</span><strong>{status?.occupied_ports ?? "—"}</strong></div>
        <div><span>Hàng chờ</span><strong>{status?.queue_length ?? "—"} xe</strong></div>
        <div><span>Occupancy dự báo</span><strong>{recommendation?.predicted_occupancy_ratio == null ? "—" : `${Math.round(recommendation.predicted_occupancy_ratio * 100)}%`}</strong></div>
        <div><span>Thời gian chờ</span><strong>{recommendation ? `${Math.round(recommendation.estimated_wait_min)} phút` : "—"}</strong></div>
        <div><span>Thời gian sạc</span><strong>{recommendation ? `${Math.round(recommendation.estimated_charge_min)} phút` : "—"}</strong></div>
      </div>

      {recommendation && (
        <div className="arrival-actions">
          {activeArrival?.status === "planned" && activeArrival.station_id === recommendation.station_id ? (
            <>
              <div className="arrival-confirmed">
                <strong>Đã xác nhận tuyến</strong>
                <span>ETA {new Date(activeArrival.eta_at).toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" })}</span>
              </div>
              <button className="secondary-button" type="button" disabled={committing} onClick={onCancel}>
                Hủy planned arrival
              </button>
            </>
          ) : (
            <button className="primary-button" type="button" disabled={committing} onClick={onCommit}>
              {committing ? "Đang xác nhận…" : "Xác nhận tuyến đến trạm"}
            </button>
          )}
        </div>
      )}
    </aside>
  );
}
