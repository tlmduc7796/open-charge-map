import { describe, expect, it } from "vitest";

import { vehicle } from "./test/fixtures";
import type { Vehicle } from "./types";
import { batteryKwh, fullRangeKm, rangeKmToSoc, socToRangeKm } from "./vehicleRange";

const withBattery = (overrides: Partial<Vehicle>): Vehicle => ({ ...vehicle, ...overrides });

describe("vehicleRange", () => {
  it("uses usable battery capacity when it is known", () => {
    const v = withBattery({ battery_capacity_kwh: 60, usable_battery_kwh: 50, consumption_wh_km: 125 });

    expect(batteryKwh(v)).toBe(50);
    expect(fullRangeKm(v)).toBeCloseTo(400);
  });

  it("falls back to nominal capacity when usable capacity is null", () => {
    const v = withBattery({ battery_capacity_kwh: 60, usable_battery_kwh: null, consumption_wh_km: 125 });

    expect(batteryKwh(v)).toBe(60);
    expect(fullRangeKm(v)).toBeCloseTo(480);
    expect(Number.isNaN(socToRangeKm(0.5, v))).toBe(false);
  });

  it("converts between SOC and range symmetrically and clamps to [0, 1]", () => {
    const v = withBattery({ usable_battery_kwh: 50, consumption_wh_km: 125 });

    expect(socToRangeKm(0.5, v)).toBeCloseTo(200);
    expect(rangeKmToSoc(200, v)).toBeCloseTo(0.5);
    expect(rangeKmToSoc(9999, v)).toBe(1);
    expect(rangeKmToSoc(-10, v)).toBe(0);
    expect(socToRangeKm(-0.2, v)).toBe(0);
  });

  it("never returns NaN or Infinity for degenerate vehicle data", () => {
    const v = withBattery({ usable_battery_kwh: null, battery_capacity_kwh: 0, consumption_wh_km: 0 });

    expect(fullRangeKm(v)).toBe(0);
    expect(socToRangeKm(0.5, v)).toBe(0);
    expect(rangeKmToSoc(100, v)).toBe(0);
  });
});