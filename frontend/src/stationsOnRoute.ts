import type { Coordinates, RouteResult, Station } from "./types";

/** A station this close to the route line counts as "on" it (route snapping + road width). */
export const ON_ROUTE_TOLERANCE_M = 150;

const EARTH_RADIUS_M = 6_371_000;

interface Nearest {
  distanceM: number;
  point: Coordinates;
}

/** Closest point to p on segment a-b, on a local equirectangular plane centred on p. */
function nearestOnSegment(p: Coordinates, a: Coordinates, b: Coordinates): Nearest {
  const metresPerDegLat = (Math.PI * EARTH_RADIUS_M) / 180;
  const metresPerDegLon = metresPerDegLat * Math.cos((p[1] * Math.PI) / 180);
  const ax = (a[0] - p[0]) * metresPerDegLon;
  const ay = (a[1] - p[1]) * metresPerDegLat;
  const dx = (b[0] - a[0]) * metresPerDegLon;
  const dy = (b[1] - a[1]) * metresPerDegLat;
  const lengthSq = dx * dx + dy * dy;
  // Projection of the origin (= p) onto the segment, clamped to its ends.
  const t = lengthSq === 0 ? 0 : Math.max(0, Math.min(1, -(ax * dx + ay * dy) / lengthSq));
  return {
    distanceM: Math.hypot(ax + t * dx, ay + t * dy),
    point: [a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])],
  };
}

function nearestOnRoute(p: Coordinates, line: Coordinates[]): Nearest | null {
  let best: Nearest | null = null;
  for (let i = 1; i < line.length; i += 1) {
    const candidate = nearestOnSegment(p, line[i - 1], line[i]);
    if (!best || candidate.distanceM < best.distanceM) best = candidate;
  }
  return best;
}

/**
 * The stations that lie on the drawn route, plus the selected one (it must stay visible and
 * clickable). Each station within the tolerance is moved onto the route line, so its marker sits
 * on the road the route follows rather than beside it; the selected station keeps its own
 * position if it is farther than that. Order is preserved.
 */
export function stationsOnRoute(
  stations: Station[],
  route: RouteResult,
  selectedStationId: string | null,
  toleranceM: number = ON_ROUTE_TOLERANCE_M,
): Station[] {
  const line = route.geometry.coordinates;
  const result: Station[] = [];
  for (const station of stations) {
    const nearest = nearestOnRoute(station.geometry.coordinates, line);
    if (nearest && nearest.distanceM <= toleranceM) {
      result.push({ ...station, geometry: { ...station.geometry, coordinates: nearest.point } });
    } else if (station.properties.station_id === selectedStationId) {
      result.push(station);
    }
  }
  return result;
}
