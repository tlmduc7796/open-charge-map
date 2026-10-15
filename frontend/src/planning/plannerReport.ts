import type { PlanningDemoSnapshotResponse, PlanningRecommendationResponse, PlanningRequest } from "./types";

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
