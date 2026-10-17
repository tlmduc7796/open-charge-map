import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import { api } from "../../api";
import GapView from "./GapView";
import type {
  GapCandidate, GapDivision, GapParams, GapRunResponse, GapSnapshotResponse,
} from "./gapTypes";

vi.mock("../../api", () => ({
  api: { gapSnapshot: vi.fn(), gapRun: vi.fn() },
}));

vi.mock("./GapMap", () => ({
  default: ({ cells, stations, candidates, layer }: {
    cells: unknown[]; stations: unknown[]; candidates: unknown[]; layer: string;
  }) => (
    <div data-testid="gap-map" data-cells={cells.length} data-stations={stations.length}
      data-candidates={candidates.length} data-layer={layer} />
  ),
}));

const defaults: GapParams = {
  division: "route", w_flow: 0.5, lambda_m: 1000, normalization: "minmax", rent_mode: "divide", rent_max_kvnd: 600,
  epsilon: 0.1, own_min_distance_m: 500, own_mode: "flag", top_n: 5, min_separation_m: 1000,
  supply_basis: "ports", reference_power_kw: 60, min_demand: 0.1, with_sensitivity: true,
};

function snapshot(division: GapDivision = "route"): GapSnapshotResponse {
  const unit = {
    unit_id: "u", unit_name: "Phường Bến Thành", lat: 10.77, lon: 106.69, poi_count: 3,
    poi_weighted: 5, flow_vph: 900, rent_kvnd_m2_month: 300,
  };
  return {
    contract_version: "gap-0.1", snapshot_id: "hcmc-nine-wards-gap-v1", division,
    prepared_on: "2026-10-17", data_labels: { flow: "synthetic" }, defaults,
    roads: [],
    cells: [division === "route"
      ? {
        ...unit, cell_id: "R0001", road_name: "Lý Tự Trọng", road_names: ["Lý Tự Trọng", "Hàm Nghi"],
        road_type: "Đường chính", lanes: 4, road_length_m: 180, area_m2: 24_000, subdivided: false,
        bounds: [10.769, 106.689, 10.771, 106.691],
        polygon: [[[10.769, 106.689], [10.769, 106.691], [10.771, 106.691], [10.771, 106.689], [10.769, 106.689]]],
      }
      : { ...unit, cell_id: "G0001", bounds: [10.769, 106.689, 10.771, 106.691] }],
    stations: [{
      station_id: "OWN-01", operator_id: "OWN", operator_name: "Mạng của mình", relationship: "OWNED",
      unit_id: "u", unit_name: "Phường Bến Thành", lat: 10.77, lon: 106.69, site_type: "mall",
      opening_hours: "24/7", port_count: 6, dc_port_count: 4, ac_port_count: 2, total_power_kw: 502,
      max_port_power_kw: 120,
      port_groups: [
        { charger_type: "DC", connector_type: "CCS2", port_count: 4, power_kw_per_port: 120 },
        { charger_type: "AC", connector_type: "TYPE2", port_count: 2, power_kw_per_port: 11 },
      ],
      data_status: "synthetic",
    }],
    station_summary: {
      stations: 1, ports: 6, total_power_kw: 502,
      by_operator: { OWN: { operator_name: "Mạng của mình", relationship: "OWNED", stations: 1, ports: 6, dc_ports: 4, ac_ports: 2, total_power_kw: 502 } },
      ports_by_power_class: { "DC 120 kW": 4 }, stations_by_ward: { "Phường Bến Thành": 1 },
    },
  };
}

function candidate(division: GapDivision = "route"): GapCandidate {
  const route = division === "route";
  return {
    cell_id: route ? "R0001" : "G0001", road_name: route ? "Lý Tự Trọng" : null,
    road_names: route ? ["Lý Tự Trọng", "Hàm Nghi"] : null,
    road_type: route ? "Đường chính" : null, width_m: null, lanes: route ? 4 : null,
    road_length_m: route ? 180 : null, area_m2: route ? 24_000 : null, subdivided: false, flow_norm: 1, poi_norm: 1, demand: 0.8, supply: 1.5, supply_own: 1,
    supply_competitor: 0.5, gap: 0.32, rent_norm: 0.2, rent_missing: false, score: 1.07,
    d_own_m: 1500, d_competitor_m: 700, own_overlap: false, excluded_reason: null, rank: 1,
    selection_order: 1, unit_id: "u", unit_name: "Phường Bến Thành", lat: 10.77, lon: 106.69,
    flow_vph: 900, poi_count: 3, poi_weighted: 5, rent_kvnd_m2_month: 300, cluster_cell_ids: [],
    cluster_size: 1,
    nearby: { radius_m: 800, cell_count: 4, flow_mean_vph: 700, flow_max_vph: 1200, flow_max_roads: ["Hàm Nghi"], flow_percentile: 80, rent_mean_kvnd: 280, rent_min_kvnd: 200, rent_max_kvnd: 360, rent_percentile: 55 },
    nearest_own: { station_id: "OWN-01", operator_name: "Mạng của mình", port_count: 6, total_power_kw: 502, max_port_power_kw: 120, distance_m: 1500 },
    nearest_competitor: null, top_supply_stations: [], stability: 0.9, stability_label: "stable",
    legal_status: "unknown", pending_legal_checks: ["Quy hoạch và mục đích sử dụng tại vị trí chưa được xác minh"],
  };
}

function runResponse(params: GapParams): GapRunResponse {
  return {
    contract_version: "gap-0.1", snapshot_id: "hcmc-nine-wards-gap-v1", params,
    cells: [candidate(params.division)], candidates: [candidate(params.division)],
    summary: {
      cell_count: 1, eligible_cell_count: 1, excluded_by_reason: {}, own_overlap_cell_count: 0,
      rent_missing_cell_count: 0, sensitivity_variant_count: 9, max_gap: 0.32, max_score: 1.07,
    },
    warnings: ["Lưu lượng xe, giá thuê và danh sách trạm là dữ liệu mô phỏng."],
  };
}

beforeEach(() => {
  vi.mocked(api.gapSnapshot).mockReset().mockImplementation(async (division = "route") => snapshot(division));
  vi.mocked(api.gapRun).mockReset().mockImplementation(async (params) => runResponse(params));
});

test("loads the snapshot, runs the defaults and lists candidates with unverified legal status", async () => {
  render(<GapView onModeChange={vi.fn()} />);
  expect(await screen.findByText("Ứng viên đi khảo sát")).toBeTruthy();
  await waitFor(() => expect(api.gapRun).toHaveBeenCalledTimes(1));
  expect(vi.mocked(api.gapRun).mock.calls[0][0]).toMatchObject({ w_flow: 0.5, lambda_m: 1000, rent_mode: "divide" });
  expect(screen.getByTestId("gap-map").getAttribute("data-cells")).toBe("1");
  expect(screen.getByTestId("gap-map").getAttribute("data-candidates")).toBe("1");
  expect(screen.getAllByText("Pháp lý chưa xác minh").length).toBeGreaterThan(0);
  expect(screen.getByText("Trạm của mình và đối thủ: mô phỏng")).toBeTruthy();
  expect(screen.getByText("Lưu lượng xe, giá thuê và danh sách trạm là dữ liệu mô phỏng.")).toBeTruthy();
});

test("selecting a candidate opens its detail with nearest stations and legal checklist", async () => {
  render(<GapView onModeChange={vi.fn()} />);
  const card = await screen.findByRole("button", { name: /Lý Tự Trọng, Hàm Nghi · Phường Bến Thành/ });
  fireEvent.click(card);
  expect(await screen.findByLabelText("Chi tiết ứng viên R0001")).toBeTruthy();
  expect(screen.getByText(/Đường chính · 4 làn · 180 m đường bao quanh/)).toBeTruthy();
  expect(screen.getByText(/2,4 ha/)).toBeTruthy();
  expect(screen.getByText(/OWN-01 · 1,5 km · 6 cổng, 502 kW/)).toBeTruthy();
  expect(screen.getByText("Quy hoạch và mục đích sử dụng tại vị trí chưa được xác minh")).toBeTruthy();
  const traffic = screen.getByLabelText("Lưu lượng quanh ứng viên");
  expect(traffic.textContent).toContain("cao hơn 80% khối trong 9 phường");
  expect(traffic.textContent).toContain("1.200 xe/giờ · Hàm Nghi");
  const price = screen.getByLabelText("Giá bất động sản quanh ứng viên");
  expect(price.textContent).toContain("đắt hơn 55% khối trong 9 phường");
  expect(price.textContent).toContain("200 – 360 nghìn");
});

test("offers exactly three map modes and always asks for five candidates", async () => {
  render(<GapView onModeChange={vi.fn()} />);
  await screen.findByText("Ứng viên đi khảo sát");
  const modes = screen.getByRole("group", { name: "Chế độ hiển thị" });
  expect(Array.from(modes.querySelectorAll("button")).map((b) => b.textContent)).toEqual([
    "Lưu lượng tuyến đường", "Giá nhà", "Điểm dự đoán",
  ]);
  expect(screen.getByTestId("gap-map").getAttribute("data-layer")).toBe("score");
  fireEvent.click(screen.getByRole("button", { name: "Giá nhà" }));
  expect(screen.getByTestId("gap-map").getAttribute("data-layer")).toBe("rent");
  fireEvent.click(screen.getByRole("button", { name: "Lưu lượng tuyến đường" }));
  expect(screen.getByTestId("gap-map").getAttribute("data-layer")).toBe("flow");
  expect(vi.mocked(api.gapRun).mock.calls[0][0]).toMatchObject({ top_n: 5 });
  expect(screen.queryByLabelText("Kịch bản")).toBeNull();
  expect(screen.queryByText("Số ứng viên")).toBeNull();
});

test("shows the station inventory with ports and power for the two kinds", async () => {
  render(<GapView onModeChange={vi.fn()} />);
  expect(await screen.findByText("Trạm của mình và trạm đối thủ (mô phỏng)")).toBeTruthy();
  expect(screen.getAllByText("Trạm của mình").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Trạm đối thủ").length).toBeGreaterThan(0);
  expect(screen.getAllByText("502 kW").length).toBeGreaterThan(0);
  expect(screen.queryByText("Đối thủ A")).toBeNull();
});

test("reports a snapshot loading error", async () => {
  vi.mocked(api.gapSnapshot).mockRejectedValueOnce(new Error("Gap snapshot unavailable"));
  render(<GapView onModeChange={vi.fn()} />);
  expect((await screen.findByRole("alert")).textContent).toContain("Gap snapshot unavailable");
  expect(api.gapRun).not.toHaveBeenCalled();
});

test("lists the candidates in the left panel with flow score, rent and nearest competitor", async () => {
  vi.mocked(api.gapRun).mockImplementation(async (params) => {
    const response = runResponse(params);
    const first = response.candidates[0];
    first.nearest_competitor = {
      station_id: "CMP-A-05", operator_name: "Đối thủ A", port_count: 6, total_power_kw: 720,
      max_port_power_kw: 120, distance_m: 640,
    };
    first.flow_norm = 0.82;
    return response;
  });
  render(<GapView onModeChange={vi.fn()} />);
  const card = await screen.findByRole("button", { name: /Lý Tự Trọng, Hàm Nghi · Phường Bến Thành/ });
  expect(card.closest("section")?.getAttribute("aria-label")).toBe("Ứng viên khảo sát");
  expect(card.textContent).toContain("Điểm lưu lượng 82900 xe/giờ");
  expect(card.textContent).toContain("Giá thuê 300nghìn đ/m²/tháng");
  expect(card.textContent).toContain("Đối thủ gần nhất 640 mCMP-A-05");
  expect(api.gapRun).toHaveBeenCalledTimes(1);
});
