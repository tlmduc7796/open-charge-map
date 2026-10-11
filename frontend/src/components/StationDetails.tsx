import { useLayoutEffect, useRef, useState } from "react";
import { COLOR_LABEL } from "../stationColor";
import type {
  AvailabilityPoint,
  RecommendationItem,
  Station,
  StationColor,
  StationForecast,
  StationStatus,
} from "../types";

export type ForecastState = "idle" | "loading" | "error" | "ready";

interface StationDetailsProps {
  station: Station | null;
  status: StationStatus | null;
  /** Backend-computed live colour; the chip is hidden until it is known. */
  color?: StationColor | null;

  /** Present only when the current search recommended this station; times exist only then. */
  recommendation: RecommendationItem | null;
  /** A search for the current inputs has run (so a missing `recommendation` means "not suggested"). */
  searchRan?: boolean;
  /** Why the current search excluded this station (backend `reason_codes`), if it did. */
  exclusionReasons?: string[];
  forecast?: StationForecast | null;
  forecastState?: ForecastState;
  onClose?: () => void;
}

const HORIZON_MIN = 30;
const STEP_MIN = 5;
/** Past this the x axis stops growing, so the 0–30′ bars stay readable. */
const AXIS_CAP_MIN = 60;
/** Backend flag: arrival is later than the last forecast point, so +30′ is reused. */
const BEYOND_HORIZON_FLAG = "BEYOND_FORECAST_HORIZON";
/** Exclusion reason: the battery cannot reach the station while keeping the reserve. */
const INSUFFICIENT_BATTERY_REASON = "INSUFFICIENT_SOC_RESERVE";
const UNREACHABLE_MESSAGE = "Không đủ điện để đến trạm này.";

const minutes = (value: number) => `${Math.round(value)} phút`;

function offsetLabel(offset: number): string {
  return offset === 0 ? "Bây giờ" : `+${offset}′`;
}

function sourceNote(forecast: StationForecast): string | null {
  const sources = new Set(forecast.points.filter((p) => p.offset_min > 0).map((p) => p.prediction_source));
  if (sources.has("default")) {
    return "Chưa có mô hình dự báo: số cổng trống tương lai dùng giá trị mặc định cố định, chưa phản ánh xu hướng thực.";
  }
  if (sources.has("persistence")) {
    return "Dự báo giữ nguyên mức sử dụng hiện tại (persistence), chưa dùng mô hình học máy.";
  }
  return null;
}

/** Bar with rounded top corners, anchored to the baseline. */
function barPath(x: number, y: number, w: number, h: number): string {
  const r = Math.min(4, h, w / 2);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

function JourneyBreakdown({ item }: { item: RecommendationItem }) {
  // `to_dest_min` is null when the search had no destination ("Tìm trạm trong tầm pin").
  const hasDestination = item.to_dest_min !== null;
  const parts = [
    { key: "travel", label: "Đến trạm", value: item.travel_min },
    { key: "wait", label: "Chờ", value: item.wait_min },
    { key: "charge", label: "Sạc", value: item.charge_min },
    ...(item.to_dest_min !== null
      ? [{ key: "dest", label: "Tới điểm đến", value: item.to_dest_min }]
      : []),
  ];
  const sum = parts.reduce((total, part) => total + Math.max(0, part.value), 0);
  return (
    <section className="detail-section" aria-label="Thời gian tại trạm">
      <div className="detail-section-head">
        <h3>{hasDestination ? "Tổng thời gian hành trình" : "Thời gian tới khi sạc xong"}</h3>
        <strong>{minutes(sum)}</strong>
      </div>
      <div className="time-bar" role="img" aria-label={parts.map((p) => `${p.label} ${minutes(p.value)}`).join(", ")}>
        {parts.map((part) => (
          part.value > 0 && sum > 0
            ? <span key={part.key} className={`time-seg time-${part.key}`} style={{ flexGrow: part.value }} />
            : null
        ))}
      </div>
      <dl className="time-legend">
        {parts.map((part) => (
          <div key={part.key}>
            <dt><i className={`time-swatch time-${part.key}`} />{part.label}</dt>
            <dd>{minutes(part.value)}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

/** Free ports at an arbitrary minute: linear interpolation between the two neighbouring points. */
function valueAt(points: AvailabilityPoint[], minute: number): number {
  const first = points[0];
  const last = points[points.length - 1];
  if (minute <= first.offset_min) return first.available_ports;
  if (minute >= last.offset_min) return last.available_ports;
  const upper = points.findIndex((point) => point.offset_min >= minute);
  const a = points[upper - 1];
  const b = points[upper];
  const fraction = (minute - a.offset_min) / (b.offset_min - a.offset_min);
  return Math.round(a.available_ports + (b.available_ports - a.available_ports) * fraction);
}

/** Width of the element in CSS px, so chart text keeps its size on a narrow card. */
function useElementWidth(fallback: number) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(fallback);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver((entries) => {
      const next = Math.round(entries[0]?.contentRect.width ?? 0);
      if (next > 0) setWidth(next);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

function ForecastChart({
  forecast,
  arrivalMin,
  beyondHorizon,
}: {
  forecast: StationForecast;
  /** Minutes until the driver reaches the station ("Đến trạm"), not snapped to a bar. */
  arrivalMin: number | null;
  /** The search had to reuse the last forecast point for this arrival (backend flag). */
  beyondHorizon: boolean;
}) {
  const [containerRef, width] = useElementWidth(420);
  const height = 160;
  const pad = { left: 30, right: 8, top: 34, bottom: 24 };
  const half = 10; // keeps the first/last bar inside the axis
  const usable = Math.max(1, width - pad.left - pad.right - 2 * half);
  const plotH = height - pad.top - pad.bottom;
  const baseline = pad.top + plotH;
  const xMax = Math.min(AXIS_CAP_MIN, Math.max(HORIZON_MIN, Math.ceil(arrivalMin ?? 0) + STEP_MIN));
  const x = (minute: number) => pad.left + half + (minute / xMax) * usable;
  const stepPx = (usable * STEP_MIN) / xMax;
  // Slim bars: at most 14px, and never more than ~40% of the 5-minute slot.
  const barW = Math.min(14, Math.max(5, stepPx * 0.4));
  const tickStep = [5, 10, 15, 30].find((step) => (usable * step) / xMax >= 40) ?? 30;
  const ticks = Array.from({ length: Math.floor(xMax / tickStep) + 1 }, (_, i) => i * tickStep);
  const cap = Math.max(forecast.operational_ports, ...forecast.points.map((p) => p.available_ports), 1);
  const lastPoint = forecast.points[forecast.points.length - 1];

  const hasArrival = arrivalMin !== null;
  // Arrivals beyond the capped axis are pinned to the right edge and labelled with an arrow.
  const offAxis = hasArrival && arrivalMin > xMax;
  const arrivalX = hasArrival ? x(Math.min(arrivalMin, xMax)) : 0;
  const arrivalValue = hasArrival ? valueAt(forecast.points, arrivalMin) : null;
  const arrivalLabel = hasArrival ? `${Math.round(arrivalMin)}′` : "";
  const note = sourceNote(forecast);

  const summary = [
    ...forecast.points.map(
      (p) => `${p.offset_min === 0 ? "Bây giờ" : `sau ${p.offset_min} phút`}: ${p.available_ports} cổng trống`,
    ),
    ...(arrivalValue !== null
      ? [`Bạn đến sau ${Math.round(arrivalMin ?? 0)} phút: khoảng ${arrivalValue} cổng trống`]
      : []),
  ].join("; ");

  const labelAnchor = arrivalX < pad.left + 50 ? "start" : arrivalX > width - 60 || offAxis ? "end" : "middle";
  return (
    <section className="detail-section" aria-label="Dự báo cổng trống">
      <div className="detail-section-head">
        <h3>Cổng trống 30 phút tới</h3>
        {arrivalValue !== null && (
          <strong className="arrival-summary">
            Khoảng {arrivalValue}/{forecast.operational_ports} cổng trống khi bạn đến
          </strong>
        )}
      </div>
      <div ref={containerRef}>
        <svg
          className="forecast-chart"
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          data-x-max={xMax}
          role="img"
          aria-label={`Số cổng trống dự báo. ${summary}`}
        >
          <line className="chart-grid" x1={pad.left} x2={width - pad.right} y1={pad.top} y2={pad.top} />
          <line className="chart-axis" x1={pad.left} x2={width - pad.right} y1={baseline} y2={baseline} />
          <text className="chart-tick" x={pad.left - 6} y={pad.top + 3} textAnchor="end">{cap}</text>
          <text className="chart-tick" x={pad.left - 6} y={baseline + 3} textAnchor="end">0</text>

          {ticks.map((minute) => (
            <text key={minute} className="chart-x" x={x(minute)} y={height - 7} textAnchor="middle">
              {offsetLabel(minute)}
            </text>
          ))}

          {forecast.points.map((point) => {
            const barH = (point.available_ports / cap) * plotH;
            const cx = x(point.offset_min);
            return (
              <g
                key={point.offset_min}
                className={`chart-bar chart-bar-${point.offset_min === 0 ? "now" : "future"}`}
                data-offset={point.offset_min}
                data-cx={cx}
              >
                <title>{`${offsetLabel(point.offset_min)}: ${point.available_ports}/${forecast.operational_ports} cổng trống`}</title>
                {/* Full-slot hit area so the tooltip works on short or empty bars. */}
                <rect x={cx - stepPx / 2} y={pad.top} width={stepPx} height={plotH} fill="transparent" />
                {barH > 0 && <path d={barPath(cx - barW / 2, baseline - barH, barW, barH)} />}
                <text className="chart-value" x={cx} y={Math.max(pad.top - 4, baseline - barH - 5)} textAnchor="middle">
                  {point.available_ports}
                </text>
              </g>
            );
          })}

          {hasArrival && arrivalValue !== null && (
            <g className="chart-arrival" data-minute={arrivalMin}>
              <title>{`Bạn đến sau ${arrivalLabel}: khoảng ${arrivalValue}/${forecast.operational_ports} cổng trống`}</title>
              <line x1={arrivalX} x2={arrivalX} y1={pad.top - 8} y2={baseline} stroke="transparent" strokeWidth="14" />
              <line className="chart-arrival-line" x1={arrivalX} x2={arrivalX} y1={pad.top - 8} y2={baseline} />
              <text className="chart-arrival-label" x={arrivalX} y={11} textAnchor={labelAnchor}>
                {offAxis ? `${arrivalLabel} →` : arrivalLabel}
              </text>
            </g>
          )}
        </svg>
      </div>
      <div className="chart-legend">
        <span><i className="legend-swatch now" />Hiện tại</span>
        <span><i className="legend-swatch future" />Dự báo</span>
        {hasArrival && <span><i className="legend-swatch arrival" />Bạn đến</span>}
      </div>
      {hasArrival && beyondHorizon && (
        <p className="chart-note">
          Bạn đến sau {arrivalLabel}, ngoài khung dự báo {lastPoint.offset_min} phút: số cổng trống lấy theo mốc +{lastPoint.offset_min}′.
        </p>
      )}
      {note && <p className="chart-note">{note}</p>}
    </section>
  );
}

export default function StationDetails({
  station,
  status,
  color = null,
  recommendation,
  searchRan = false,
  exclusionReasons,
  forecast = null,
  forecastState = "idle",
  onClose,
}: StationDetailsProps) {
  const [expanded, setExpanded] = useState(false);
  if (!station) return null;
  const properties = station.properties;
  // The header and the chart's "now" bar must show the same number: the live reading wins
  // over the forecast endpoint's own offset-0 point, which may come from a different poll.
  const alignedForecast = forecast && status
    ? {
        ...forecast,
        operational_ports: status.operational_ports,
        points: forecast.points.map((point) => (
          point.offset_min === 0 ? { ...point, available_ports: status.available_ports } : point
        )),
      }
    : forecast;
  // Only an explicit backend reason counts: a station outside the search corridor has none.
  const unreachable =
    recommendation === null && (exclusionReasons?.includes(INSUFFICIENT_BATTERY_REASON) ?? false);
  const directionsUrl = recommendation
    ? `https://www.google.com/maps/dir/?api=1&destination=${station.geometry.coordinates[1]},${station.geometry.coordinates[0]}&travelmode=driving`
    : `https://www.google.com/maps/search/?api=1&query=${station.geometry.coordinates[1]},${station.geometry.coordinates[0]}`;
  return (
    <aside className={`station-details ${expanded ? "expanded" : ""}`} aria-label="Chi tiết trạm">
      <button className="detail-close" type="button" aria-label="Đóng chi tiết trạm" onClick={onClose}>×</button>
      <div className="detail-title">
        <div>
          <span className={`access-badge access-${properties.access}`}>{properties.access === "public" ? "PUBLIC" : properties.access}</span>
          <h2>{properties.name}</h2>
          <p>{properties.address}</p>
        </div>
      </div>

      <div className="detail-now" aria-label="Trạng thái hiện tại">
        {status ? (
          <>
            {color && (
              <span className={`state-chip state-${color}`}><i className={`availability-dot ${color}`} />{COLOR_LABEL[color]}</span>
            )}
            <span className="detail-now-count">
              <strong>{status.available_ports}</strong>/{status.operational_ports} cổng trống
            </span>
          </>
        ) : (
          <span className="detail-muted">Chưa có dữ liệu cổng</span>
        )}
      </div>

      {recommendation
        ? <JourneyBreakdown item={recommendation} />
        : (
          <p className={`detail-hint${unreachable ? " detail-hint-error" : ""}`}>
            {unreachable
              ? UNREACHABLE_MESSAGE
              : searchRan
                ? "Trạm này không được đề xuất cho lần tìm kiếm hiện tại."
                : "Tìm trạm theo hành trình để xem thời gian đến, chờ và sạc."}
          </p>
        )}

      {forecastState === "ready" && alignedForecast && (
        <ForecastChart
          forecast={alignedForecast}
          arrivalMin={recommendation?.travel_min ?? null}
          beyondHorizon={recommendation?.flags.includes(BEYOND_HORIZON_FLAG) ?? false}
        />
      )}
      {forecastState === "loading" && <p className="detail-hint" role="status">Đang tải dự báo cổng trống…</p>}
      {forecastState === "error" && <p className="detail-hint" role="status">Không tải được dự báo cổng trống.</p>}

      <a className="primary-button directions-button" href={directionsUrl} target="_blank" rel="noreferrer">Chỉ đường</a>

      <button className="detail-expand" type="button" aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>
        {expanded ? "Thu gọn" : "Thông tin trạm"} <span aria-hidden="true">{expanded ? "⌃" : "⌄"}</span>
      </button>
      {expanded && <div className="detail-grid">
        <div><span>Đầu sạc</span><strong>{properties.connectors.map((item) => `${item.type} ${item.max_power_kw} kW ×${item.count}`).join(", ")}</strong></div>
        <div><span>Cổng hoạt động</span><strong>{status ? `${status.operational_ports}/${status.total_ports}` : "—"}</strong></div>
        <div><span>Đang trống</span><strong>{status?.available_ports ?? "—"}</strong></div>
        <div><span>Đang sử dụng</span><strong>{status?.occupied_ports ?? "—"}</strong></div>
      </div>}
    </aside>
  );
}
