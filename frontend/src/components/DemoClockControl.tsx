import { useState, type FormEvent } from "react";

import { toVietnamIso, vietnamFields, type ClockFields } from "../demoClock";
import type { DemoClock } from "../types";

interface DemoClockControlProps {
  /** The demo moment shown now; the parent advances it every second. */
  demoNow: Date;
  /** Last answer of the server: data bounds, whether the time is shifted, whether it may change. */
  clock: DemoClock | null;
  busy: boolean;
  error: string | null;
  onApply: (isoWithOffset: string) => void;
  onReset: () => void;
}

const dayFormat = (date: Date) =>
  date.toLocaleDateString("vi-VN", {
    timeZone: "Asia/Ho_Chi_Minh",
    weekday: "long",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });

const timeFormat = (date: Date) =>
  date.toLocaleTimeString("vi-VN", {
    timeZone: "Asia/Ho_Chi_Minh",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });

const shortDay = (iso: string) => {
  const { date } = vietnamFields(Date.parse(iso));
  const [year, month, day] = date.split("-");
  return `${day}/${month}/${year}`;
};

/** Current demo date and time with a form to jump to another moment (date, hour, minute, second). */
export default function DemoClockControl({
  demoNow,
  clock,
  busy,
  error,
  onApply,
  onReset,
}: DemoClockControlProps) {
  const [open, setOpen] = useState(false);
  const [fields, setFields] = useState<ClockFields>(() => vietnamFields(demoNow.getTime()));
  const [formError, setFormError] = useState<string | null>(null);

  const writable = clock?.writable ?? true;
  const dataStart = clock?.data_start ?? null;
  const dataEnd = clock?.data_end ?? null;
  const minDate = dataStart ? vietnamFields(Date.parse(dataStart)).date : undefined;
  const maxDate = dataEnd ? vietnamFields(Date.parse(dataEnd)).date : undefined;

  const openForm = () => {
    setFields(vietnamFields(demoNow.getTime()));
    setFormError(null);
    setOpen(true);
  };

  const number = (value: string) => (value === "" ? Number.NaN : Number(value));
  const setField = (key: "hour" | "minute" | "second") => (value: string) =>
    setFields((current) => ({ ...current, [key]: number(value) }));

  const iso = toVietnamIso(fields);
  const outside =
    iso !== null
    && dataStart !== null
    && dataEnd !== null
    && (Date.parse(iso) < Date.parse(dataStart) || Date.parse(iso) > Date.parse(dataEnd));

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (iso === null) {
      setFormError("Ngày hoặc giờ không hợp lệ.");
      return;
    }
    setFormError(null);
    onApply(iso);
    setOpen(false);
  };

  const shifted = clock?.is_shifted ?? false;
  return (
    <div className="current-datetime" aria-label="Ngày giờ hiện tại">
      <div className="demo-clock-head">
        <span className="current-datetime-date">{dayFormat(demoNow)}</span>
        <span className={`demo-clock-badge${shifted ? " shifted" : ""}`}>
          {shifted ? "Giờ demo" : "Giờ thật"}
        </span>
      </div>
      <div className="demo-clock-row">
        <time className="current-datetime-time" dateTime={demoNow.toISOString()}>
          {timeFormat(demoNow)}
        </time>
        {writable && (
          <button
            type="button"
            className="demo-clock-toggle"
            aria-expanded={open}
            aria-controls="demo-clock-form"
            onClick={() => (open ? setOpen(false) : openForm())}
          >
            Đổi giờ
          </button>
        )}
      </div>
      {error && <p className="demo-clock-error" role="alert">{error}</p>}
      {open && (
        <form id="demo-clock-form" className="demo-clock-form" onSubmit={submit} noValidate>
          <label className="demo-clock-field wide">
            <span>Ngày</span>
            <input
              type="date"
              value={fields.date}
              min={minDate}
              max={maxDate}
              required
              onChange={(event) => setFields((current) => ({ ...current, date: event.target.value }))}
            />
          </label>
          <label className="demo-clock-field">
            <span>Giờ</span>
            <input
              type="number"
              inputMode="numeric"
              min={0}
              max={23}
              value={Number.isNaN(fields.hour) ? "" : fields.hour}
              onChange={(event) => setField("hour")(event.target.value)}
            />
          </label>
          <label className="demo-clock-field">
            <span>Phút</span>
            <input
              type="number"
              inputMode="numeric"
              min={0}
              max={59}
              value={Number.isNaN(fields.minute) ? "" : fields.minute}
              onChange={(event) => setField("minute")(event.target.value)}
            />
          </label>
          <label className="demo-clock-field">
            <span>Giây</span>
            <input
              type="number"
              inputMode="numeric"
              min={0}
              max={59}
              value={Number.isNaN(fields.second) ? "" : fields.second}
              onChange={(event) => setField("second")(event.target.value)}
            />
          </label>
          {dataStart && dataEnd && (
            <p className="demo-clock-hint">
              Dữ liệu: {shortDay(dataStart)} – {shortDay(dataEnd)}. Đồng hồ chạy tiếp từ thời điểm bạn chọn.
            </p>
          )}
          {outside && (
            <p className="demo-clock-warning" role="status">
              Ngoài khoảng dữ liệu: các trạm sẽ hiện không có dữ liệu.
            </p>
          )}
          {formError && <p className="demo-clock-error" role="alert">{formError}</p>}
          <div className="demo-clock-actions">
            <button type="submit" className="primary" disabled={busy}>Áp dụng</button>
            <button
              type="button"
              disabled={busy || !shifted}
              onClick={() => {
                onReset();
                setOpen(false);
              }}
            >
              Về giờ thật
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
