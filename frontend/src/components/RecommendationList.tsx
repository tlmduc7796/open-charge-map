import { useMemo, useState } from "react";
import type { CandidateExclusion, RecommendationItem, Station, StationStatus } from "../types";

interface RecommendationListProps {
  items: RecommendationItem[];
  exclusions: CandidateExclusion[];
  stations: Station[];
  selectedStationId: string | null;
  hasRun: boolean;
  notice?: string | null;
  title?: string;
  emptyMessage?: string;
  onSelect: (item: RecommendationItem) => void;
  statuses?: Record<string, StationStatus>;
  hoveredStationId?: string | null;
  onHover?: (stationId: string | null) => void;
  onSortChange?: (sortBy: "fastest" | "nearest" | "available") => void;
  /** "Enough" case: a first card for going straight (no stop), shaped like a station card. */
  onSelectDirect?: () => void;
  directSelected?: boolean;
  /** Minutes of the direct route, shown as the card's score. */
  directMinutes?: number;
  /** Offered when the battery is enough but the driver may still want to stop. */
  onRequestOptionalStops?: () => void;
  optionalStopsLoading?: boolean;
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
  const [sortBy, setSortBy] = useState<"fastest" | "nearest" | "available">("fastest");
  const stationsById = Object.fromEntries(
    props.stations.map((station) => [station.properties.station_id, station]),
  );
  const items = useMemo(() => [...props.items].sort((a, b) => {
    if (sortBy === "nearest") return a.distance_km - b.distance_km;
    if (sortBy === "available") return (props.statuses?.[b.station_id]?.available_ports ?? 0) - (props.statuses?.[a.station_id]?.available_ports ?? 0);
    return a.total_min - b.total_min;
  }), [props.items, props.statuses, sortBy]);
  return (
    <section className="recommendation-panel" aria-labelledby="recommendation-title">
      <div className="section-heading compact">
        <div>
          <span className="step-label">02 · Kết quả</span>
          <h2 id="recommendation-title">{props.title ?? "Trạm được đề xuất"}</h2>
        </div>
        {props.items.length > 0 && <span className="result-count">{props.items.length} trạm hợp lệ</span>}
      </div>

      {props.items.length > 0 && <div className="sort-chips" aria-label="Sắp xếp trạm">
        <button className={sortBy === "fastest" ? "active" : ""} onClick={() => { setSortBy("fastest"); props.onSortChange?.("fastest"); }}>Nhanh nhất</button>
        <button className={sortBy === "nearest" ? "active" : ""} onClick={() => { setSortBy("nearest"); props.onSortChange?.("nearest"); }}>Gần nhất</button>
        <button className={sortBy === "available" ? "active" : ""} onClick={() => { setSortBy("available"); props.onSortChange?.("available"); }}>Trống nhất</button>
      </div>}

      {!props.hasRun && <div className="empty-state">Nhập thông tin để xem trạm sạc phù hợp.</div>}
      {props.hasRun && props.notice && !props.onSelectDirect && (
        <div className="empty-state">{props.notice}</div>
      )}
      {props.hasRun && !props.notice && props.items.length === 0 && (
        <div className="empty-state warning">{props.emptyMessage ?? "Không có trạm tương thích và tới được với mức pin hiện tại."}</div>
      )}

      <div className="recommendation-list">
        {props.hasRun && props.onSelectDirect && (
          <button
            type="button"
            className={`recommendation-card direct-card ${props.directSelected ? "selected" : ""}`}
            aria-pressed={props.directSelected}
            onClick={props.onSelectDirect}
          >
            <span className="rank" aria-hidden="true">→</span>
            <span className="card-main">
              <strong>Đi thẳng tới điểm đến</strong>
              <small>Pin đủ, không cần sạc</small>
              {props.notice && <span className="direct-hint">{props.notice}</span>}
            </span>
            <span className="score" title="Tổng thời gian">
              {Math.round(props.directMinutes ?? 0)}<small>phút</small>
            </span>
          </button>
        )}
        {props.hasRun && props.onRequestOptionalStops && (
          <button
            type="button"
            className="optional-stops-button"
            disabled={props.optionalStopsLoading}
            onClick={props.onRequestOptionalStops}
          >
            {props.optionalStopsLoading ? "Đang tìm trạm…" : "Ghé trạm dọc đường"}
          </button>
        )}
        {items.map((item, index) => (
          <button
            type="button"
            className={`recommendation-card ${props.selectedStationId === item.station_id ? "selected" : ""}`}
            key={item.station_id}
            onClick={() => props.onSelect(item)}
            onMouseEnter={() => props.onHover?.(item.station_id)}
            onMouseLeave={() => props.onHover?.(null)}
            onFocus={() => props.onHover?.(item.station_id)}
            onBlur={() => props.onHover?.(null)}
          >
            <span className="rank">#{index + 1}</span>
            <span className="card-main">
              <strong>{stationsById[item.station_id]?.properties.name ?? item.station_name}</strong>
              <small>
                {stationsById[item.station_id]?.properties.connectors
                  .map((connector) => `${connector.type} ${connector.max_power_kw} kW ×${connector.count}`)
                  .join(" · ") ?? item.connectors.join(" · ")}
              </small>
              <span className="metric-row">
                <span><b>{props.statuses?.[item.station_id]?.available_ports ?? "—"} cổng</b> đang trống</span>
                <span><b>{minutes(item.travel_min)}</b> di chuyển</span>
                <span>
                  <b>
                    {minutes(item.wait_min)}
                  </b>
                  chờ ước tính{item.flags.includes("WAIT_DEFAULTED_MISSING_INPUTS") ? " · dữ liệu hạn chế" : ""}
                </span>
                <span><b>{minutes(item.charge_min)}</b> sạc</span>
              </span>
            </span>
            <span className="score" title="Tổng thời gian">{Math.round(item.total_min)}<small>phút</small></span>
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
