import type { ModelStatus } from "../types";

interface StatusBarProps {
  model: ModelStatus | null;
  mapProvider: "goong" | "osm";
}

export default function StatusBar({ model, mapProvider }: StatusBarProps) {
  return (
    <div className="status-bar" aria-label="Trạng thái hệ thống">
      <span><i className="status-light online" />Backend API</span>
      <span><i className={`status-light ${mapProvider === "goong" ? "online" : "fallback"}`} />Map: {mapProvider === "goong" ? "Goong" : "OSM fallback"}</span>
      <span><i className={`status-light ${model?.prediction_source === "model" ? "online" : "fallback"}`} />Forecast: {model?.prediction_source ?? "đang tải"}</span>
    </div>
  );
}
