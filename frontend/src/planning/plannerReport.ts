import type { PlanningDemoSnapshotResponse, PlanningRecommendationResponse, PlanningRequest } from "./types";
import { loadPercent, simulateStationLoad } from "./stationLoad";

interface PlannerReportInput {
  demo: PlanningDemoSnapshotResponse;
  request: PlanningRequest;
  response: PlanningRecommendationResponse;
}

function cell(value: unknown): string {
  return String(value ?? "—").replaceAll("|", "\\|").replace(/\r?\n/g, " ");
}

export function buildPlannerReport({ demo, request, response }: PlannerReportInput): string {
  const labels = new Map(demo.candidates.map((candidate) => [candidate.candidate_id, candidate.label]));
  const warnings = [...new Set([...demo.warnings, ...response.warnings])];
  const lines = [
    "# Báo cáo đánh giá địa điểm trạm sạc", "",
    `- Lần đánh giá: ${response.run_id}`,
    `- Trạng thái: ${response.status}`,
    `- Bộ dữ liệu: ${response.scenario.data_snapshot_id}`,
    `- Thuật toán: ${response.scenario.algorithm_version ?? "Chưa xác định"}`,
    `- Cấu hình: ${response.scenario.config_version ?? "Chưa xác định"}`, "",
    "## Phạm vi và giả định", "",
    "Dữ liệu Planner hiện tại phục vụ mô phỏng. Thứ hạng chưa xác nhận địa điểm đủ điều kiện xây dựng. Thời gian tiếp cận và chi phí là các giá trị theo giả định của bộ dữ liệu.", "",
    "## Cảnh báo và giới hạn dữ liệu", "",
    ...warnings.map((warning) => `- ${warning}`),
    ...(warnings.length ? [] : ["Không có cảnh báo bổ sung trong phản hồi."]), "",
    "## Kết quả xếp hạng", "",
    "| Hạng | Địa điểm | Mã | Điểm /100 | Trạng thái | Tỷ trọng bằng chứng |",
    "|---|---|---|---|---|---|",
    ...response.recommendations.map((item) => `| ${item.rank} | ${cell(labels.get(item.candidate_id) ?? item.candidate_id)} | ${cell(item.candidate_id)} | ${item.technical_score.toFixed(2)} | ${item.eligibility} | ${(item.evidence_coverage * 100).toFixed(1)}% |`), "",
  ];
  for (const item of response.recommendations) {
    lines.push(
      `## Địa điểm: ${cell(labels.get(item.candidate_id) ?? item.candidate_id)}`, "",
      "### Chỉ số", "", "| Chỉ số | Giá trị | Đơn vị | Trạng thái dữ liệu |", "|---|---|---|---|",
      ...Object.entries(item.metrics).map(([key, metric]) => `| ${cell(key)} | ${cell(metric.value)} | ${cell(metric.unit)} | ${metric.status} |`), "",
      "### Thành phần điểm, gồm các tiêu chí chưa có dữ liệu", "",
      "| Tiêu chí | Điểm | Trọng số % | Đóng góp | Trạng thái | Giải thích |", "|---|---|---|---|---|---|",
      ...item.score_breakdown.map((part) => `| ${cell(part.component_id)} | ${cell(part.score)} | ${cell(part.weight_percent)} | ${cell(part.contribution_points)} | ${part.status} | ${cell(part.reason)} |`), "",
      "### Điều kiện và thông tin cần xác minh", "",
      "| Điều kiện | Trạng thái | Lý do |", "|---|---|---|",
      ...item.constraints.map((constraint) => `| ${cell(constraint.id)} | ${constraint.status} | ${cell(constraint.reason)} |`), "",
      "### Nguồn dữ liệu", "",
      ...item.provenance.map((source) => `- ${cell(source.field)}: mã nguồn=${cell(source.source_id)}; tài liệu=${cell(source.source_ref)}; trạng thái=${source.status}; mô phỏng=${source.is_synthetic}; thời điểm=${cell(source.observed_at)}; ${cell(source.note)}`), "",
    );
  }
  lines.push(
    "## Địa điểm chưa được xếp hạng", "",
    ...response.unranked_candidates.map((item) => `- ${cell(labels.get(item.candidate_id) ?? item.candidate_id)} (${cell(item.candidate_id)}): ${item.reason}`),
    ...(response.unranked_candidates.length ? [] : ["Không có."]), "",
    "## Địa điểm bị loại", "",
    ...response.excluded_candidates.map((item) => `- ${cell(labels.get(item.candidate_id) ?? item.candidate_id)} (${cell(item.candidate_id)}): ${item.constraints.map((constraint) => `${constraint.id} [${constraint.status}]: ${constraint.reason}`).join("; ")}`),
    ...(response.excluded_candidates.length ? [] : ["Không có."]), "",
    "## Thông số đầu vào để đối chiếu", "", "```json", JSON.stringify(request, null, 2), "```", "",
  );
  const simulation = simulateStationLoad({ demo, scenario: request.run.demand_scenario,
    coverageMinutes: request.technical.coverage_minutes, recommendations: response.recommendations,
    chargerOption: request.technical.charger_options[0] });
  if (simulation) {
    lines.push("## Mô phỏng tải trước và sau bổ sung", "",
      `Phiên bản mô hình: ${simulation.modelVersion}; đầu vào: ${simulation.inputs.version}. Khung cao điểm: ${simulation.intervalStart}; ${simulation.inputs.interval_minutes} phút.`, "",
      "Giả sử đồng thời mở tất cả ứng viên có thứ hạng bằng cấu hình cổng của request. Đây là so sánh mạng giả định, không phải tối ưu danh mục ngân sách, dự báo lựa chọn tài xế hay bằng chứng quá tải thực tế. Điểm xếp hạng không được dùng để nhân giảm nhu cầu.", "",
      "Hiện trạng: ưu tiên trạm trong 2 phút di chuyển, bỏ riêng 2 phút vào trạm khỏi mốc này. Ngoài nhóm gần, dùng các trạm trong ngưỡng tiếp cận. Trọng số = năng lực phục vụ / (phút di chuyển + 0,5)^2. Tổng nhu cầu được phân bổ đúng một lần; không cắt phần vượt công suất.", "",
      "Sau bổ sung: chỉ chuyển tải sang ứng viên có cùng unit_id với trạm hiện hữu đang nhường tải, đồng thời thỏa ngưỡng tổng thời gian tiếp cận trên form từ node nhu cầu gốc. Không áp trần 2 phút ở bước giảm tải theo phường. Nhu cầu chưa phân bổ dùng phường của node gốc để xét ứng viên; phần này là tăng độ phủ, không ghi thành giảm tải trạm cũ. Thiếu mã phường thì không chuyển, không đoán phường theo tên hay mã trạm.", "",
      "Ưu tiên nhu cầu chưa phân bổ, sau đó phần tải vượt ngưỡng 80% của trạm cũ. Xét trạm cũ chịu tải cao trước, tiếp theo là đường di chuyển ngắn; hạng chỉ phá hòa. Trạm mới chỉ nhận tới 80% năng lực. Đây là phương án điều phối tham lam, không dự báo khách tự chuyển trạm, không bảo đảm tối ưu toàn cục. Phần chưa chuyển được giữ ở trạm cũ.", "",
      `Tổng nhu cầu: ${simulation.baseline.totalDemand.toFixed(4)} lượt/khung. Chưa phân bổ: ${simulation.baseline.unassigned.toFixed(4)} → ${simulation.proposed.unassigned.toFixed(4)}.`,
      `Trạm hiện hữu quá tải: ${simulation.baseline.existingOverloaded} → ${simulation.proposed.existingOverloaded}.`,
      `Nhu cầu vượt công suất toàn mạng (gồm trạm mới): ${simulation.baseline.totalExcess.toFixed(4)} → ${simulation.proposed.totalExcess.toFixed(4)} lượt/khung.`, "",
      "| Trạm | Loại | Tải trước | Tải sau | Lượt sau / khung | Năng lực / khung |",
      "|---|---|---|---|---|---|",
      ...Object.values(simulation.proposed.stations).map((site) => `| ${site.id} | ${site.kind} | ${loadPercent(simulation.baseline.stations[site.id]?.utilization ?? null)} | ${loadPercent(site.utilization)} | ${site.sessions.toFixed(4)} | ${site.capacity?.toFixed(4) ?? "Chưa xác định"} |`), "",
      "### Luồng chuyển tải thực sự được chấp nhận", "",
      "| Phường chung | Node nhu cầu gốc | Trạm cũ | Ứng viên nhận tải | Phút di chuyển từ node | Lượt/khung |",
      "|---|---|---|---|---|---|",
      ...simulation.proposed.transfers.map((flow) => `| ${flow.wardId} | ${flow.nodeId} | ${flow.fromSiteId ?? "Chưa phân bổ"} | ${flow.toCandidateId} | ${flow.driveMinutes.toFixed(4)} | ${flow.sessions.toFixed(4)} |`), "",
      "Thiếu số cổng/công suất: tải giữ chưa xác định; trạm đó không tham gia chia nhu cầu. Giả định hoạt động toàn bộ cổng, mở cửa và không có sự cố tại khung cao điểm. Nhu cầu chờ từ khung trước không được mô phỏng.", "",
      "### Tham số và nhu cầu cao điểm dùng để tái lập", "", "```json", JSON.stringify(simulation.inputs, null, 2), "```", "");
  }
  return lines.join("\n");
}

export function downloadPlannerReport(markdown: string, runId: string): void {
  const url = URL.createObjectURL(new Blob([markdown], { type: "text/markdown;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `planner-${runId.replace(/[^a-zA-Z0-9_-]/g, "-")}.md`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
