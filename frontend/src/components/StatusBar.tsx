import type { ModelStatus } from "../types";

interface StatusBarProps {
  demoMode: boolean;
  model: ModelStatus | null;
  mapProvider: "goong" | "osm";
  activeEvents: string[];
  statusFeedUnavailable: boolean;
}

export default function StatusBar({
  demoMode,
  model,
  mapProvider,
  activeEvents,
  statusFeedUnavailable,
}: StatusBarProps) {
  return (
    <div className="status-bar" aria-label={demoMode ? "Trạng thái demo" : "Trạng thái dịch vụ"}>
      <span>
        <i className={`status-light ${statusFeedUnavailable ? "unavailable" : "online"}`} />
        Station status: {statusFeedUnavailable ? "unavailable; last data marked stale" : "connected"}
      </span>
      <span><i className={`status-light ${mapProvider === "goong" ? "online" : "fallback"}`} />Map: {mapProvider === "goong" ? "Goong" : "OSM fallback"}</span>
      <span title={model?.serving_reason ?? undefined}><i className={`status-light ${model?.prediction_source === "model" ? "online" : "fallback"}`} />Forecast: {model?.prediction_source ?? "đang tải"}{model?.model_profile ? ` · ${model.model_profile}` : ""}</span>
      {demoMode && <span><i className={`status-light ${activeEvents.length ? "event" : "online"}`} />Event: {activeEvents.length ? activeEvents.join(", ") : "none"}</span>}
    </div>
  );
}
