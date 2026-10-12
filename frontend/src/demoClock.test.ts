import { expect, test } from "vitest";

import { demoMsAt, toVietnamIso, vietnamFields } from "./demoClock";

test("reads an instant as Vietnam time (UTC+7)", () => {
  expect(vietnamFields(Date.parse("2026-09-15T01:00:30Z"))).toEqual({
    date: "2026-09-15",
    hour: 8,
    minute: 0,
    second: 30,
  });
  // 18:00 UTC is already the next calendar day in Vietnam.
  expect(vietnamFields(Date.parse("2026-09-30T18:05:09Z"))).toEqual({
    date: "2026-10-01",
    hour: 1,
    minute: 5,
    second: 9,
  });
});

test("builds an ISO instant with an explicit +07:00 offset", () => {
  expect(toVietnamIso({ date: "2026-09-15", hour: 8, minute: 5, second: 9 })).toBe(
    "2026-09-15T08:05:09+07:00",
  );
});

test("round-trips through the fields", () => {
  const ms = Date.parse("2026-10-11T23:59:59+07:00");
  const iso = toVietnamIso(vietnamFields(ms));

  expect(Date.parse(iso as string)).toBe(ms);
});

test.each([
  { date: "2026-09-15", hour: 24, minute: 0, second: 0 },
  { date: "2026-09-15", hour: 8, minute: 60, second: 0 },
  { date: "2026-09-15", hour: 8, minute: 0, second: -1 },
  { date: "2026-09-15", hour: Number.NaN, minute: 0, second: 0 },
  { date: "2026-09-15", hour: 8.5, minute: 0, second: 0 },
  { date: "", hour: 8, minute: 0, second: 0 },
  { date: "2026-02-30", hour: 8, minute: 0, second: 0 },
])("rejects invalid fields %j", (fields) => {
  expect(toVietnamIso(fields)).toBeNull();
});

test("the shown moment keeps running from the anchor", () => {
  const anchor = { demoMs: Date.parse("2026-09-15T01:00:00Z"), localMs: 1_000_000 };

  expect(demoMsAt(anchor, 1_000_000)).toBe(anchor.demoMs);
  expect(demoMsAt(anchor, 1_090_000)).toBe(anchor.demoMs + 90_000);
});
