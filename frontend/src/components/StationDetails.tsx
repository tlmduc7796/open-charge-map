import { useState } from "react";

import type {
  PlannedArrival,
  RecommendationItem,
  Station,
  StationOccupancyForecast,
  StationOccupancyObservation,
  StationIncidentType,
  StationStatus,
} from "../types";

interface StationDetailsProps {
  demoMode: boolean;
  station: Station | null;
  status: StationStatus | null;
  forecast: StationOccupancyForecast | null;
  forecastUnavailable: boolean;
  history?: StationOccupancyObservation[] | null;
  historyUnavailable?: boolean;
  recommendation: RecommendationItem | null;
  activeArrival: PlannedArrival | null;
  committing: boolean;
  onCommit: () => void;
  onCancel: () => void;
  journeyId: string | null;
  journeyAccessToken: string | null;
  onReportIncident: (
    stationId: string,
    incidentType: StationIncidentType,
    description: string,
    idempotencyKey: string,
  ) => Promise<void>;
}

export default function StationDetails({
  demoMode,
  station,
  status,
  forecast,
  forecastUnavailable,
  history = null,
  historyUnavailable = false,
  recommendation,
  activeArrival,
  committing,
  onCommit,
  onCancel,
  journeyId,
  journeyAccessToken,
  onReportIncident,
}: StationDetailsProps) {
  const [incidentType, setIncidentType] = useState<StationIncidentType>("port_unavailable");
  const [incidentDescription, setIncidentDescription] = useState("");
  const [incidentKey, setIncidentKey] = useState(() => crypto.randomUUID());
  const [reportingIncident, setReportingIncident] = useState(false);
  const [incidentReported, setIncidentReported] = useState(false);
  if (!station) {
    return <aside className="station-details empty-state">Chọn một marker hoặc recommendation để xem chi tiết.</aside>;
  }
  const properties = station.properties;
  const statusUsable = Boolean(
    status &&
      (demoMode || (
        !status.is_stale &&
        !["synthetic", "unknown", "runtime"].includes(status.data_source)
      )),
  );
  const statusClass = !status
    ? "unknown"
    : status.is_stale || status.data_source === "unknown" || status.unknown_ports === status.total_ports
      ? "unknown"
      : status.operational_ports === 0
        ? "offline"
        : status.available_ports > 0
          ? "available"
          : "busy";
  return (
    <aside className="station-details">
      <div className="detail-title">
        <div>
          <span className={`access-badge access-${properties.access}`}>{properties.access}</span>
          <h2>{properties.name}</h2>
          <p>{properties.address}</p>
        </div>
        {status && <span className={`availability-dot ${statusClass}`} />}
      </div>

      {properties.notes.length > 0 && (
        <div className="notice">{properties.notes.join(" ")}</div>
      )}

      <div className="detail-grid">
        <div><span>Đầu sạc</span><strong>{properties.connectors.map((item) => `${item.type} ${item.max_power_kw} kW ×${item.count}`).join(", ")}</strong></div>
        <div><span>Cổng hoạt động</span><strong>{statusUsable && status ? `${status.operational_ports}/${status.total_ports}` : "—"}</strong></div>
        <div><span>Trạng thái chưa rõ</span><strong>{statusUsable && status ? status.unknown_ports : "—"}</strong></div>
        <div><span>Đang trống</span><strong>{statusUsable && status ? status.available_ports : "—"}</strong></div>
        <div><span>Đang sử dụng</span><strong>{statusUsable && status ? status.occupied_ports : "—"}</strong></div>
        <div><span>Hàng chờ</span><strong>{statusUsable && status ? `${status.queue_length ?? "—"} xe` : "—"}</strong></div>
        <div><span>Occupancy dự báo +15 phút</span><strong>{forecast?.predicted_occupancy_ratio == null ? "—" : `${Math.round(forecast.predicted_occupancy_ratio * 100)}%`}</strong></div>
        <div title="Ước tính tại thời điểm tới trạm, có điều chỉnh theo occupancy dự báo và hàng chờ đã quan sát."><span>Chờ dự kiến khi tới</span><strong>{recommendation ? `${Math.round(recommendation.wait_expected_min ?? recommendation.estimated_wait_min)} phút` : "—"}</strong></div>
        <div title="P90 Erlang C là xấp xỉ theo tải trạm ổn định; chưa hiệu chuẩn bằng telemetry vận hành."><span>P90 lý thuyết (Erlang C)</span><strong>{recommendation?.wait_p90_min == null ? "—" : `≈${Math.round(recommendation.wait_p90_min)} phút`}</strong></div>
        <div><span>Thời gian sạc</span><strong>{recommendation ? `${Math.round(recommendation.estimated_charge_min)} phút` : "—"}</strong></div>
      </div>

      {status && <small className="data-provenance">Nguồn trạng thái: {status.data_source} · Cập nhật {new Date(status.timestamp).toLocaleString("vi-VN")}{status.is_stale ? " · Dữ liệu đã cũ" : ""}</small>}
      {(properties.source_provider || properties.source_updated_at) && (
        <small className="data-provenance">
          Nguồn catalog: {properties.source_provider ?? "không rõ"}
          {properties.source_updated_at
            ? ` · ${properties.source_updated_at_basis === "database_updated_at" ? "Bản ghi DB cập nhật" : "Nguồn cập nhật"} ${new Date(properties.source_updated_at).toLocaleString("vi-VN")}`
            : " · Chưa có thời điểm cập nhật nguồn"}
        </small>
      )}
      {forecast && <small className="data-provenance">Nguồn dự báo: {forecast.prediction_source}{forecast.model_version ? ` · Model ${forecast.model_version}` : ""}{forecast.confidence == null ? " · Độ tin cậy chưa hiệu chuẩn" : ` · Độ tin cậy ${Math.round(forecast.confidence * 100)}%`} · Tạo {new Date(forecast.generated_at).toLocaleString("vi-VN")} · Mục tiêu {new Date(forecast.target_at).toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" })}{forecast.flags.length ? ` · ${forecast.flags.join(", ")}` : ""}</small>}
      {forecastUnavailable && <small className="fallback-note">Chưa có forecast: trạng thái trạm có thể đã cũ hoặc chưa được xác minh.</small>}

      <section className="occupancy-history" aria-label="Lịch sử occupancy quan sát">
        <strong>Lịch sử occupancy (24 giờ)</strong>
        {history?.length ? (
          <div className="occupancy-history-bars" role="img" aria-label={`${history.length} bản ghi quan sát`}>
            {history.slice(-48).map((item) => (
              <span key={item.bucket_at}
                className={item.occupancy_ratio == null ? "unknown" : undefined}
                title={`${new Date(item.bucket_at).toLocaleString("vi-VN")}: ${item.occupancy_ratio == null ? "không xác định" : `${Math.round(item.occupancy_ratio * 100)}%`} · ${item.occupied_ports}/${item.operational_ports} cổng`}
                style={{ height: `${Math.max(4, (item.occupancy_ratio ?? 0) * 100)}%` }} />
            ))}
          </div>
        ) : historyUnavailable ? (
          <small className="fallback-note">Không tải được lịch sử occupancy từ backend.</small>
        ) : (
          <small className="fallback-note">Chưa có bản ghi occupancy quan sát trong 24 giờ qua.</small>
        )}
        {history?.length ? <small className="data-provenance">{history.length} bucket 5 phút · dữ liệu observed</small> : null}
      </section>

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

      {recommendation && journeyId && journeyAccessToken && (
        <form
          className="incident-report"
          onSubmit={async (event) => {
            event.preventDefault();
            setReportingIncident(true);
            try {
              await onReportIncident(
                recommendation.station_id,
                incidentType,
                incidentDescription,
                incidentKey,
              );
              setIncidentDescription("");
              setIncidentReported(true);
              setIncidentKey(crypto.randomUUID());
            } catch {
              // The parent displays the API error and the same key can safely retry.
            } finally {
              setReportingIncident(false);
            }
          }}
        >
          <strong>Báo cáo thông tin trạm</strong>
          {incidentReported && <small role="status">Đã gửi báo cáo để xác minh.</small>}
          <select
            aria-label="Loại sự cố"
            value={incidentType}
            disabled={reportingIncident}
            onChange={(event) => setIncidentType(event.target.value as StationIncidentType)}
          >
            <option value="port_unavailable">Cổng sạc không hoạt động</option>
            <option value="queue_inaccurate">Hàng chờ không chính xác</option>
            <option value="access_problem">Vấn đề truy cập</option>
            <option value="safety_concern">Vấn đề an toàn</option>
            <option value="other">Khác</option>
          </select>
          <textarea
            value={incidentDescription}
            minLength={3}
            maxLength={500}
            required
            disabled={reportingIncident}
            placeholder="Mô tả ngắn (tối đa 500 ký tự)"
            onChange={(event) => {
              setIncidentDescription(event.target.value);
              setIncidentReported(false);
            }}
          />
          <button
            className="secondary-button"
            type="submit"
            disabled={reportingIncident || incidentDescription.trim().length < 3}
          >
            {reportingIncident ? "Đang gửi…" : "Gửi báo cáo"}
          </button>
        </form>
      )}
    </aside>
  );
}
