import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { demoClock } from "../test/fixtures";
import type { DemoClock } from "../types";
import DemoClockControl from "./DemoClockControl";

// 2026-09-25 18:00:00 in Vietnam.
const NOW = new Date("2026-09-25T11:00:00Z");

function setup(overrides: Partial<{ clock: DemoClock; error: string | null; busy: boolean }> = {}) {
  const onApply = vi.fn();
  const onReset = vi.fn();
  render(
    <DemoClockControl
      demoNow={NOW}
      clock={overrides.clock ?? demoClock}
      busy={overrides.busy ?? false}
      error={overrides.error ?? null}
      onApply={onApply}
      onReset={onReset}
    />,
  );
  return { onApply, onReset };
}

const openForm = () => fireEvent.click(screen.getByRole("button", { name: "Đổi giờ" }));
const field = (name: string) => screen.getByLabelText(name) as HTMLInputElement;

test("shows the demo time in Vietnam time and marks it as demo time", () => {
  setup();

  expect(screen.getByText("18:00:00")).toBeInTheDocument();
  expect(screen.getByText("Giờ demo")).toBeInTheDocument();
});

test("marks real time when the clock is not shifted", () => {
  setup({ clock: { ...demoClock, is_shifted: false } });

  expect(screen.getByText("Giờ thật")).toBeInTheDocument();
});

test("the form starts from the current demo moment", () => {
  setup();
  openForm();

  expect(field("Ngày").value).toBe("2026-09-25");
  expect(field("Giờ").value).toBe("18");
  expect(field("Phút").value).toBe("0");
  expect(field("Giây").value).toBe("0");
});

test("applying sends the chosen date, hour, minute and second with the +07:00 offset", () => {
  const { onApply } = setup();
  openForm();

  fireEvent.change(field("Ngày"), { target: { value: "2026-10-03" } });
  fireEvent.change(field("Giờ"), { target: { value: "7" } });
  fireEvent.change(field("Phút"), { target: { value: "45" } });
  fireEvent.change(field("Giây"), { target: { value: "30" } });
  fireEvent.click(screen.getByRole("button", { name: "Áp dụng" }));

  expect(onApply).toHaveBeenCalledWith("2026-10-03T07:45:30+07:00");
});

test("an invalid time is not sent", () => {
  const { onApply } = setup();
  openForm();

  fireEvent.change(field("Giờ"), { target: { value: "25" } });
  fireEvent.click(screen.getByRole("button", { name: "Áp dụng" }));

  expect(onApply).not.toHaveBeenCalled();
  expect(screen.getByRole("alert")).toHaveTextContent("không hợp lệ");
});

test("bounds the date to the loaded data and warns when the moment is outside it", () => {
  setup();
  openForm();

  expect(field("Ngày")).toHaveAttribute("min", "2026-09-01");
  expect(field("Ngày")).toHaveAttribute("max", "2026-10-31");
  expect(screen.queryByText(/Ngoài khoảng dữ liệu/)).not.toBeInTheDocument();

  fireEvent.change(field("Ngày"), { target: { value: "2026-12-01" } });

  expect(screen.getByText(/Ngoài khoảng dữ liệu/)).toBeInTheDocument();
});

test("returns to real time through the reset button", () => {
  const { onReset } = setup();
  openForm();

  fireEvent.click(screen.getByRole("button", { name: "Về giờ thật" }));

  expect(onReset).toHaveBeenCalledTimes(1);
});

test("reset is unavailable while already on real time", () => {
  setup({ clock: { ...demoClock, is_shifted: false } });
  openForm();

  expect(screen.getByRole("button", { name: "Về giờ thật" })).toBeDisabled();
});

test("a locked clock offers no way to change it", () => {
  setup({ clock: { ...demoClock, writable: false } });

  expect(screen.queryByRole("button", { name: "Đổi giờ" })).not.toBeInTheDocument();
});

test("shows the error of a failed change", () => {
  setup({ error: "the demo clock is read-only" });

  expect(screen.getByRole("alert")).toHaveTextContent("the demo clock is read-only");
});
