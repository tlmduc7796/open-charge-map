import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { recommendationItem, station } from "../test/fixtures";
import RecommendationList from "./RecommendationList";

test("renders recommendation metrics and selection", () => {
  const onSelect = vi.fn();
  const modelItem = { ...recommendationItem, model_version: "occupancy-test-v2" };
  render(
    <RecommendationList
      items={[modelItem]}
      outcome="charging_stops"
      exclusions={[]}
      stations={[station]}
      selectedStationId={null}
      hasRun
      onSelect={onSelect}
    />,
  );

  expect(screen.getByText(station.properties.name)).toBeInTheDocument();
  expect(screen.getByText(/model occupancy-test-v2/)).toBeInTheDocument();
  expect(screen.getByText("14 phút")).toBeInTheDocument();
  expect(screen.getByText(/P90 lý thuyết 0 phút/)).toBeInTheDocument();
  expect(screen.queryByText(/cost|giá điện/i)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: new RegExp(station.properties.name) }));
  expect(onSelect).toHaveBeenCalledWith(modelItem);
});

test("renders empty and exclusion states", () => {
  render(
    <RecommendationList
      items={[]}
      outcome="no_reachable_station"
      exclusions={[{ station_id: station.properties.station_id, reason_codes: ["STATION_OFFLINE"] }]}
      fallbackCandidate={{
        station_id: station.properties.station_id,
        station_name: station.properties.name,
        straight_line_distance_m: 2400,
        is_reachable: false,
        reason_codes: ["INSUFFICIENT_SOC_RESERVE"],
      }}
      stations={[station]}
      selectedStationId={null}
      hasRun
      onSelect={vi.fn()}
    />,
  );

  expect(screen.getByText(/Không tìm thấy trạm sạc khả thi/i)).toBeInTheDocument();
  fireEvent.click(screen.getByText(/1 trạm đã bị loại/i));
  expect(screen.getByText("Trạm đang offline")).toBeInTheDocument();
});

test("does not tell users to skip charging when an older result has no station items", () => {
  render(
    <RecommendationList
      items={[]}
      outcome="direct_no_charge"
      exclusions={[]}
      stations={[]}
      selectedStationId={null}
      hasRun
      onSelect={vi.fn()}
    />,
  );

  expect(screen.getByText("Chưa có trạm sạc nào được đề xuất cho hành trình này.")).toBeInTheDocument();
  expect(screen.queryByText(/pin hiện tại đủ|không cần dừng sạc/i)).not.toBeInTheDocument();
});

test("discloses the nearest station only as an unreachable fallback", () => {
  render(
    <RecommendationList
      items={[]}
      outcome="no_reachable_station"
      exclusions={[]}
      fallbackCandidate={{
        station_id: station.properties.station_id,
        station_name: station.properties.name,
        straight_line_distance_m: 2400,
        is_reachable: false,
        reason_codes: ["INSUFFICIENT_SOC_RESERVE"],
      }}
      stations={[]}
      selectedStationId={null}
      hasRun
      onSelect={vi.fn()}
    />,
  );

  const fallback = screen.getByRole("note");
  expect(fallback).toHaveTextContent(station.properties.name);
  expect(fallback).toHaveTextContent("Trạm gần nhất trong catalog");
  expect(fallback).toHaveTextContent("2.4 km");
  expect(fallback).toHaveTextContent("theo đường chim bay");
  expect(fallback).toHaveTextContent("không phải lựa chọn an toàn");
  expect(fallback).toHaveTextContent("Không đủ SOC");
});

test("discloses when candidate recommendations were bounded", () => {
  render(
    <RecommendationList
      items={[]}
      outcome="no_reachable_station"
      exclusions={[]}
      resultFlags={["RECOMMENDATION_CANDIDATE_LIMIT_REACHED"]}
      candidateLimit={50}
      stations={[]}
      selectedStationId={null}
      hasRun
      onSelect={vi.fn()}
    />,
  );

  expect(screen.getByRole("status")).toHaveTextContent("50 trạm gần tuyến nhất");
});
