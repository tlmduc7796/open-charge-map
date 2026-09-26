import type { ModelStatus } from "../types";

interface StatusBarProps {
  model: ModelStatus | null;
  mapProvider: "goong" | "osm";
  activeEvents: string[];
}

export default function StatusBar({ model, mapProvider, activeEvents }: StatusBarProps) {
  return (
    <div className="status-bar" aria-label="Trạng thái demo">
      <span><i className="status-light online" />Backend API</span>
      <span><i className={`status-light ${mapProvider === "goong" ? "online" : "fallback"}`} />Map: {mapProvider === "goong" ? "Goong" : "OSM fallback"}</span>
      <span><i className={`status-light ${model?.prediction_source === "model" ? "online" : "fallback"}`} />Forecast: {model?.prediction_source ?? "đang tải"}</span>
      <span><i className={`status-light ${activeEvents.length ? "event" : "online"}`} />Event: {activeEvents.length ? activeEvents.join(", ") : "none"}</span>
    </div>
  );
}
