import type { Vehicle } from "./types";

/**
 * Battery size used for range display. Mirrors the backend rule
 * (`Vehicle.calculation_battery_kwh`): usable capacity when known, otherwise nominal.
 * Display conversion only; reachability and energy are always computed by the backend.
 */
export const batteryKwh = (vehicle: Vehicle) =>
  vehicle.usable_battery_kwh ?? vehicle.battery_capacity_kwh;

export const fullRangeKm = (vehicle: Vehicle) => {
  const km = (batteryKwh(vehicle) * 1000) / vehicle.consumption_wh_km;
  return Number.isFinite(km) && km > 0 ? km : 0;
};

export const socToRangeKm = (soc: number, vehicle: Vehicle) =>
  Math.max(0, soc) * fullRangeKm(vehicle);

export const rangeKmToSoc = (rangeKm: number, vehicle: Vehicle) => {
  const fullKm = fullRangeKm(vehicle);
  return fullKm > 0 ? Math.min(1, Math.max(0, rangeKm / fullKm)) : 0;
};