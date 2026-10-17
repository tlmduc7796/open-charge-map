import { expect, test } from "vitest";

import { route, station } from "./test/fixtures";
import { stationsOnRoute } from "./stationsOnRoute";
import type { Station } from "./types";

function at(id: string, lon: number, lat: number): Station {
  return {
    ...station,
    geometry: { type: "Point", coordinates: [lon, lat] },
    properties: { ...station.properties, station_id: id },
  };
}

const ids = (list: Station[]) => list.map((item) => item.properties.station_id);

test("keeps stations next to the route line and drops the rest", () => {
  // ~55 m east of the mid-point of the first leg vs ~5 km away.
  const near = at("NEAR", 106.7035, 10.7173);
  const far = at("FAR", 106.75, 10.9);

  expect(ids(stationsOnRoute([near, far], route, null))).toEqual(["NEAR"]);
});

test("measures to the segment, not just to its vertices", () => {
  // Middle of a long straight leg, far from both vertices.
  const mid = at("MID", 106.694, 10.7665);

  expect(ids(stationsOnRoute([mid], route, null))).toEqual(["MID"]);
});

test("always keeps the selected station", () => {
  const far = at("FAR", 106.75, 10.9);

  expect(ids(stationsOnRoute([far], route, "FAR"))).toEqual(["FAR"]);
});

test("honours the tolerance", () => {
  const off = at("OFF", 106.7035 + 0.005, 10.7173); // ~550 m east of the line

  expect(stationsOnRoute([off], route, null, 150)).toHaveLength(0);
  expect(stationsOnRoute([off], route, null, 1000)).toHaveLength(1);
});

test("moves a nearby station's marker onto the route line", () => {
  const vertical: typeof route = {
    ...route,
    geometry: { type: "LineString", coordinates: [[106.7, 10.7], [106.7, 10.8]] },
  };
  // ~55 m east of a straight north-south road.
  const [snapped] = stationsOnRoute([at("S", 106.7005, 10.75)], vertical, null);

  expect(snapped.geometry.coordinates[0]).toBeCloseTo(106.7, 6);
  expect(snapped.geometry.coordinates[1]).toBeCloseTo(10.75, 6);
});

test("leaves a far selected station where it is", () => {
  const far = at("FAR", 106.75, 10.9);

  expect(stationsOnRoute([far], route, "FAR")[0].geometry.coordinates).toEqual([106.75, 10.9]);
});
