import type { StationColor } from "./types";

/** Label for each backend colour; the thresholds themselves live in the backend's app_config. */
export const COLOR_LABEL: Record<StationColor, string> = {
  green: "Còn trống",
  yellow: "Còn ít",
  red: "Hết chỗ",
  grey: "Chưa có dữ liệu",
};

/** Same hues as the Goong station GL layer's "circle-color" match expression, for the Leaflet fallback map. */
export const COLOR_HEX: Record<StationColor, string> = {
  green: "#22c55e",
  yellow: "#f59e0b",
  red: "#ef4444",
  grey: "#64748b",
};
