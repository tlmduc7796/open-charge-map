import type { Vehicle } from "./types";

export const fullRangeKm = (vehicle: Vehicle) =>
  (vehicle.usable_battery_kwh * 1000) / vehicle.consumption_wh_km;

export const socToRangeKm = (soc: number, vehicle: Vehicle) =>
  Math.max(0, soc) * fullRangeKm(vehicle);

export const rangeKmToSoc = (rangeKm: number, vehicle: Vehicle) =>
  Math.min(1, Math.max(0, rangeKm / fullRangeKm(vehicle)));
