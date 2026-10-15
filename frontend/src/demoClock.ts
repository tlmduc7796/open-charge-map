/** Helpers for the demo clock: all wall-clock fields are Vietnam time (UTC+7, no DST). */

const VIETNAM_OFFSET_MS = 7 * 60 * 60 * 1000;

export interface ClockFields {
  /** YYYY-MM-DD */
  date: string;
  hour: number;
  minute: number;
  second: number;
}

/** Moment the server reported, paired with the local `Date.now()` at which it was received. */
export interface ClockAnchor {
  demoMs: number;
  localMs: number;
}

/** The demo moment shown now: the anchor plus the local time elapsed since it was received. */
export function demoMsAt(anchor: ClockAnchor, localMs: number): number {
  return anchor.demoMs + (localMs - anchor.localMs);
}

/** Vietnam-time date and hour/minute/second of an instant. */
export function vietnamFields(ms: number): ClockFields {
  const shifted = new Date(ms + VIETNAM_OFFSET_MS);
  const iso = shifted.toISOString(); // YYYY-MM-DDTHH:MM:SS.sssZ, read as Vietnam time
  return {
    date: iso.slice(0, 10),
    hour: shifted.getUTCHours(),
    minute: shifted.getUTCMinutes(),
    second: shifted.getUTCSeconds(),
  };
}

const pad = (value: number) => String(value).padStart(2, "0");

/** ISO-8601 instant (with an explicit +07:00) for Vietnam-time fields, or null when invalid. */
export function toVietnamIso(fields: ClockFields): string | null {
  const { date, hour, minute, second } = fields;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return null;
  const parts = [hour, minute, second];
  if (parts.some((part) => !Number.isInteger(part))) return null;
  if (hour < 0 || hour > 23 || minute < 0 || minute > 59 || second < 0 || second > 59) return null;
  const iso = `${date}T${pad(hour)}:${pad(minute)}:${pad(second)}+07:00`;
  const parsed = Date.parse(iso);
  if (Number.isNaN(parsed)) return null;
  // Date.parse rolls an impossible day (2026-02-30) over into the next month: reject it.
  return vietnamFields(parsed).date === date ? iso : null;
}
