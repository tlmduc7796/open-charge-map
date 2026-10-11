import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, test } from "vitest";

import { recommendationItem, station, status } from "../test/fixtures";
import type { RecommendationItem, StationForecast, StationStatus } from "../types";
import StationDetails from "./StationDetails";

const liveStatus: StationStatus = {
  ...status,
  total_ports: 10,
  operational_ports: 10,
  available_ports: 10,
  occupied_ports: 0,
};

/** Free ports 10 → 4 over the 30-minute horizon, so interpolation is observable. */
const forecast: StationForecast = {
  station_id: station.properties.station_id,
  total_ports: 10,
  operational_ports: 10,
  generated_at: "2026-09-25T18:00:00+07:00",
  points: [0, 5, 10, 15, 20, 25, 30].map((offset, index) => ({
    offset_min: offset,
    available_ports: [10, 8, 6, 4, 4, 4, 4][index],
    prediction_source: offset === 0 ? "synthetic" : "default",
    flags: offset === 0 ? [] : ["ML_DEFAULT_VALUE"],
  })),
};

const BEYOND = "BEYOND_FORECAST_HORIZON";

/** Like the backend, flags arrivals later than the last forecast point (> 30′ after rounding). */
const item = (travel: number, wait = 5, charge = 10): RecommendationItem => ({
  ...recommendationItem,
  travel_min: travel,
  wait_min: wait,
  charge_min: charge,
  to_dest_min: 20,
  total_min: travel + wait + charge + 20,
  flags: Math.round(travel) > 30 ? [...recommendationItem.flags, BEYOND] : recommendationItem.flags,
});

function renderChart(recommendation: RecommendationItem) {
  const view = render(
    <StationDetails
      station={station}
      status={liveStatus}
      recommendation={recommendation}
      forecast={forecast}
      forecastState="ready"
    />,
  );
  const chart = view.container.querySelector("svg.forecast-chart") as SVGSVGElement;
  const cx = (offset: number) =>
    Number(chart.querySelector(`[data-offset="${offset}"]`)!.getAttribute("data-cx"));
  const arrivalX = Number(
    chart.querySelector(".chart-arrival-line")!.getAttribute("x1"),
  );
  return { chart, cx, arrivalX, unmount: view.unmount };
}

test("shows live state, arrival/wait/charge times and the 30-minute forecast", () => {
  render(
    <StationDetails
      station={station}
      status={liveStatus}
      color="green"
      recommendation={item(12)}
      forecast={forecast}
      forecastState="ready"
    />,
  );

  expect(screen.getByText("PUBLIC")).toBeInTheDocument();
  const live = screen.getByLabelText("Trạng thái hiện tại");
  expect(within(live).getByText("Còn trống")).toBeInTheDocument();
  expect(live).toHaveTextContent("10/10 cổng trống");

  const times = screen.getByLabelText("Thời gian tại trạm");
  expect(times).toHaveTextContent("Đến trạm");
  expect(times).toHaveTextContent("12 phút");
  expect(times).toHaveTextContent("Chờ");
  expect(times).toHaveTextContent("5 phút");
  expect(times).toHaveTextContent("Sạc");
  expect(times).toHaveTextContent("10 phút");
  // With a destination the total covers the whole trip: 12 + 5 + 10 + 20.
  expect(times).toHaveTextContent("Tới điểm đến");
  expect(times).toHaveTextContent("20 phút");
  expect(times).toHaveTextContent("Tổng thời gian hành trình");
  expect(times).toHaveTextContent("47 phút");

  expect(screen.getByRole("img", { name: /Số cổng trống dự báo/ })).toHaveAccessibleName(
    /sau 30 phút: 4 cổng trống/,
  );
  expect(screen.getByText(/giá trị mặc định cố định/)).toBeInTheDocument();
});

test("the live chip follows the colour the backend computed, not the port counts", () => {
  // 10 free ports would be "green" by any local rule; the backend's colour wins.
  const cases = [
    ["yellow", "Còn ít"],
    ["red", "Hết chỗ"],
    ["grey", "Chưa có dữ liệu"],
  ] as const;
  for (const [color, label] of cases) {
    const view = render(
      <StationDetails station={station} status={liveStatus} color={color} recommendation={null} />,
    );
    const chip = within(screen.getByLabelText("Trạng thái hiện tại")).getByText(label);
    expect(chip.closest(".state-chip")).toHaveClass(`state-${color}`);
    view.unmount();
  }
});

test("shows the port count but no colour chip until the backend colour is known", () => {
  render(<StationDetails station={station} status={liveStatus} recommendation={null} />);

  const live = screen.getByLabelText("Trạng thái hiện tại");
  expect(live).toHaveTextContent("10/10 cổng trống");
  expect(live.querySelector(".state-chip")).toBeNull();
});

test("arrival line sits at the real arrival minute, between the +10 and +15 bars", () => {
  const { cx, arrivalX } = renderChart(item(12));

  // 12′ is 40% of the way from +10′ to +15′.
  expect(arrivalX).toBeGreaterThan(cx(10));
  expect(arrivalX).toBeLessThan(cx(15));
  expect((arrivalX - cx(10)) / (cx(15) - cx(10))).toBeCloseTo(0.4, 5);
});

test("arrival line lands exactly on the +5 bar and on the 'now' bar", () => {
  const five = renderChart(item(5));
  expect(five.arrivalX).toBeCloseTo(five.cx(5), 5);
  five.unmount();

  const zero = renderChart(item(0));
  expect(zero.arrivalX).toBeCloseTo(zero.cx(0), 5);
});

test("'Khi đến' is interpolated at the arrival minute and changes with it", () => {
  const view = renderChart(item(12));
  // 6 (at +10) → 4 (at +15), 40% of the way: 5.2 → 5.
  expect(screen.getByText("Khoảng 5/10 cổng trống khi bạn đến")).toBeInTheDocument();
  view.unmount();

  renderChart(item(7));
  // 8 (at +5) → 6 (at +10), 40% of the way: 7.2 → 7.
  expect(screen.getByText("Khoảng 7/10 cổng trống khi bạn đến")).toBeInTheDocument();
});

test("bars are uniform: nothing is outlined or emphasised at the arrival bucket", () => {
  const { chart } = renderChart(item(12));

  expect(chart.querySelectorAll(".is-arrival")).toHaveLength(0);
  expect(chart.querySelectorAll(".chart-bar-now")).toHaveLength(1);
  expect(chart.querySelectorAll(".chart-bar-future")).toHaveLength(6);
});

test("no 'time using the station' band: neither shading nor legend entry", () => {
  const { chart } = renderChart(item(12, 5, 10));

  expect(chart.querySelector(".chart-usage")).toBeNull();
  expect(screen.queryByText("Thời gian bạn dùng trạm")).not.toBeInTheDocument();
  // The axis follows the arrival only (max(30, 12 + 5)), not arrive + wait + charge.
  expect(chart.getAttribute("data-x-max")).toBe("30");
});

test("arrival after +30′ reuses the +30′ value, marked approximate with a note", () => {
  const { chart, cx, arrivalX } = renderChart(item(35, 10, 20));

  expect(chart.getAttribute("data-x-max")).toBe("40");
  expect(arrivalX).toBeGreaterThan(cx(30));
  // Nothing is predicted past +30, so the value is the +30′ one (4).
  expect(screen.getByText("Khoảng 4/10 cổng trống khi bạn đến")).toBeInTheDocument();
  expect(screen.getByText(/ngoài khung dự báo 30 phút/)).toBeInTheDocument();
  expect(chart.querySelector(".chart-arrival title")!.textContent).toBe(
    "Bạn đến sau 35′: khoảng 4/10 cổng trống",
  );
});

test("a very late arrival keeps the axis at 60′ and pins the marker to the edge with an arrow", () => {
  const { chart, cx, arrivalX } = renderChart(item(90, 10, 20));
  const label = chart.querySelector(".chart-arrival-label")!;

  expect(chart.getAttribute("data-x-max")).toBe("60");
  // The 0–30′ bars keep a readable width (they are not squeezed into a corner).
  expect(cx(5) - cx(0)).toBeGreaterThan(25);
  expect(arrivalX).toBeLessThanOrEqual(Number(chart.getAttribute("width")));
  // Only the time (plus an arrow when it is off the axis) — no "Bạn đến" next to the line.
  expect(label.textContent).toBe("90′ →");
  expect(screen.getByText("Khoảng 4/10 cổng trống khi bạn đến")).toBeInTheDocument();
});

test("'beyond the horizon' follows the backend flag, not a raw travel_min comparison", () => {
  // 30.4′ rounds to 30′ on the backend: not flagged, so no approximation or note.
  const unflagged = renderChart(item(30.4));
  expect(unflagged.chart.querySelector(".chart-arrival")).not.toBeNull();
  expect(screen.queryByText(/ngoài khung dự báo/)).not.toBeInTheDocument();
  expect(screen.getByText("Khoảng 4/10 cổng trống khi bạn đến")).toBeInTheDocument();
  unflagged.unmount();

  // The same arrival, but the backend did flag it.
  const flagged = renderChart({ ...item(30.4), flags: [BEYOND] });
  expect(screen.getByText("Khoảng 4/10 cổng trống khi bạn đến")).toBeInTheDocument();
  expect(screen.getByText(/ngoài khung dự báo/)).toBeInTheDocument();
  flagged.unmount();
});

test("tooltips keep reporting the exact free ports for bars and for the arrival line", () => {
  const { chart } = renderChart(item(12));

  const barTitle = chart.querySelector('[data-offset="10"] title')!.textContent;
  const lineTitle = chart.querySelector(".chart-arrival title")!.textContent;
  expect(barTitle).toBe("+10′: 6/10 cổng trống");
  expect(lineTitle).toBe("Bạn đến sau 12′: khoảng 5/10 cổng trống");
});

test("chart 'now' bar matches the live count in the header even if the forecast was polled later", () => {
  // Forecast offset 0 says 5 free (newer poll); the header status says 2 free.
  const drifted: StationForecast = {
    ...forecast,
    points: forecast.points.map((point) => (point.offset_min === 0 ? { ...point, available_ports: 5 } : point)),
  };
  render(
    <StationDetails
      station={station}
      status={{ ...liveStatus, available_ports: 2, occupied_ports: 8 }}
      recommendation={null}
      forecast={drifted}
      forecastState="ready"
    />,
  );

  expect(screen.getByLabelText("Trạng thái hiện tại")).toHaveTextContent("2/10 cổng trống");
  expect(screen.getByRole("img", { name: /Số cổng trống dự báo/ })).toHaveAccessibleName(
    /Bây giờ: 2 cổng trống/,
  );
});

test("works without a recommendation or forecast and expands connector info", () => {
  render(
    <StationDetails station={station} status={status} recommendation={null} forecastState="error" />,
  );

  expect(screen.getByText(/Tìm trạm theo hành trình/)).toBeInTheDocument();
  expect(screen.getByText("Không tải được dự báo cổng trống.")).toBeInTheDocument();
  expect(screen.queryByLabelText("Thời gian tại trạm")).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /Thông tin trạm/ }));
  expect(screen.getByText(/CCS2 150 kW/)).toBeInTheDocument();
});

test("without a recommendation the chart shows bars only, no arrival line or band", () => {
  const { container } = render(
    <StationDetails
      station={station}
      status={liveStatus}
      recommendation={null}
      forecast={forecast}
      forecastState="ready"
    />,
  );

  expect(container.querySelector(".chart-arrival")).toBeNull();
  expect(container.querySelector(".chart-usage")).toBeNull();
  expect(container.querySelector("svg.forecast-chart")!.getAttribute("data-x-max")).toBe("30");
});

test("without a destination the total stops at the end of charging", () => {
  render(
    <StationDetails
      station={station}
      status={liveStatus}
      recommendation={{ ...item(12), to_dest_min: null, total_min: 27 }}
      forecast={forecast}
      forecastState="ready"
    />,
  );

  const times = screen.getByLabelText("Thời gian tại trạm");
  expect(times).toHaveTextContent("Thời gian tới khi sạc xong");
  expect(times).toHaveTextContent("27 phút");
  expect(times).not.toHaveTextContent("Tới điểm đến");
});

test("a station outside the recommendations explains why there is no time estimate", () => {
  const { container } = render(
    <StationDetails
      station={station}
      status={liveStatus}
      recommendation={null}
      searchRan
      forecast={forecast}
      forecastState="ready"
    />,
  );

  expect(screen.getByText("Trạm này không được đề xuất cho lần tìm kiếm hiện tại.")).toBeInTheDocument();
  expect(screen.queryByLabelText("Thời gian tại trạm")).not.toBeInTheDocument();
  expect(container.querySelector(".chart-arrival")).toBeNull();
  expect(container.querySelector("svg.forecast-chart")).not.toBeNull();
});

test("a station the battery cannot reach shows a red line in the same slot and style as the hint", () => {
  const { container } = render(
    <StationDetails
      station={station}
      status={liveStatus}
      recommendation={null}
      searchRan
      exclusionReasons={["INSUFFICIENT_SOC_RESERVE"]}
      forecast={forecast}
      forecastState="ready"
    />,
  );

  const message = screen.getByText("Không đủ điện để đến trạm này.");
  expect(message.tagName).toBe("P");
  expect(message).toHaveClass("detail-hint", "detail-hint-error");
  // It replaces the generic hint rather than adding a second line.
  expect(screen.queryByText(/không được đề xuất cho lần tìm kiếm/)).not.toBeInTheDocument();
  expect(screen.queryByText(/khi bạn đến/)).not.toBeInTheDocument();
  expect(container.querySelectorAll(".detail-hint")).toHaveLength(1);
  // The forecast bars are still shown for the station.
  expect(container.querySelector("svg.forecast-chart")).not.toBeNull();
});

test("other exclusion reasons do not claim the battery is insufficient", () => {
  render(
    <StationDetails
      station={station}
      status={liveStatus}
      recommendation={null}
      searchRan
      exclusionReasons={["NON_PUBLIC_ACCESS", "STATION_OFFLINE"]}
      forecast={forecast}
      forecastState="ready"
    />,
  );

  expect(screen.queryByText("Không đủ điện để đến trạm này.")).not.toBeInTheDocument();
});

test("the unreachable message still appears while the forecast is loading", () => {
  render(
    <StationDetails
      station={station}
      status={liveStatus}
      recommendation={null}
      searchRan
      exclusionReasons={["INSUFFICIENT_SOC_RESERVE"]}
      forecastState="loading"
    />,
  );

  expect(screen.getByText("Không đủ điện để đến trạm này.")).toHaveClass("detail-hint-error");
  expect(screen.getByText("Đang tải dự báo cổng trống…")).toBeInTheDocument();
});

test("every non-recommended station gets the same message, whatever the exclusion reason", () => {
  const { unmount } = render(
    <StationDetails
      station={station}
      status={liveStatus}
      recommendation={null}
      searchRan
      exclusionReasons={["STATION_OFFLINE"]}
      forecast={forecast}
      forecastState="ready"
    />,
  );
  expect(screen.getByText("Trạm này không được đề xuất cho lần tìm kiếm hiện tại.")).toBeInTheDocument();
  unmount();

  render(
    <StationDetails
      station={station}
      status={liveStatus}
      recommendation={null}
      searchRan
      forecast={forecast}
      forecastState="ready"
    />,
  );
  expect(screen.getByText("Trạm này không được đề xuất cho lần tìm kiếm hiện tại.")).toBeInTheDocument();
});
