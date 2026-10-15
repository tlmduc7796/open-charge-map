import { api } from "./api";

export const CURRENT_LOCATION_LABEL = "Vị trí hiện tại";

const GEOLOCATION_ERRORS: Record<number, string> = {
  1: "Trình duyệt chưa được cấp quyền vị trí. Hãy cho phép truy cập vị trí rồi thử lại.",
  2: "Không xác định được vị trí hiện tại.",
  3: "Lấy vị trí hiện tại quá lâu. Hãy thử lại.",
};

/** Browser position as `{lat, lon}`, with Vietnamese error messages. */
export function getCurrentPosition(): Promise<{ lat: number; lon: number }> {
  return new Promise((resolve, reject) => {
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      reject(new Error("Trình duyệt không hỗ trợ định vị."));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (position) => resolve({ lat: position.coords.latitude, lon: position.coords.longitude }),
      (error) => reject(new Error(GEOLOCATION_ERRORS[error.code] ?? "Không thể lấy vị trí hiện tại.")),
      { enableHighAccuracy: false, timeout: 10_000, maximumAge: 30_000 },
    );
  });
}

/**
 * Address for a coordinate, or `fallback` when reverse geocoding fails or takes longer than
 * `timeoutMs`. Never rejects.
 */
export async function resolvePlaceLabel(
  lat: number,
  lon: number,
  fallback: string,
  timeoutMs = 3000,
): Promise<string> {
  const lookup = api
    .reverseGeocode(lat, lon)
    .then((place) => place.label || fallback)
    .catch(() => fallback);
  let timer: number | undefined;
  const timeout = new Promise<string>((resolve) => {
    timer = window.setTimeout(() => resolve(fallback), timeoutMs);
  });
  try {
    return await Promise.race([lookup, timeout]);
  } finally {
    window.clearTimeout(timer);
  }
}
