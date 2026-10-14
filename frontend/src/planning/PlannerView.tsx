import { useEffect, useMemo, useState, type FormEvent } from "react";

import { api } from "../api";
import AppModeSwitch, { type AppMode } from "./AppModeSwitch";
import PlannerMap from "./PlannerMap";
import { DEMAND_SCENARIO_LABELS } from "./demandHeatmap";
import type {
  PlanningDemoSnapshotResponse,
  PlanningDataStatus,
  PlanningConstraintStatus,
  PlanningMetric,
  PlanningRecommendation,
  PlanningRecommendationResponse,
  PlanningRequest,
  PlanningRunStatus,
} from "./types";
import "./planner.css";

interface PlannerViewProps {
  onModeChange: (mode: AppMode) => void;
}

const M5_DEMO_CANDIDATE_IDS = [
  "cand-hcm_2025_26911-02",
  "cand-hcm_2025_26929-01",
  "cand-hcm_2025_27073-01",
];

function localDateTimeNow(): string {
  const now = new Date();
  const localOffsetMs = now.getTimezoneOffset() * 60_000;
  return new Date(now.getTime() - localOffsetMs).toISOString().slice(0, 16);
}

function statusLabel(status: PlanningDataStatus): string {
  const labels: Record<PlanningDataStatus, string> = {
    observed: "Đã quan sát",
    proxy: "Ước tính gián tiếp",
    synthetic: "Mô phỏng",
    scenario: "Theo kịch bản",
    unknown: "Chưa có dữ liệu",
    not_applicable: "Không áp dụng",
  };
  return labels[status];
}

function metricValue(metric: PlanningMetric | undefined): string {
  if (!metric || metric.value === null) return "Chưa có dữ liệu";
  const value = typeof metric.value === "number"
    ? metric.value.toLocaleString("vi-VN")
    : metric.value;
  const units: Record<string, string> = {
    sessions_per_week: "lượt/tuần", "sessions/week": "lượt/tuần",
    percent_total_demand: "% nhu cầu toàn khu vực", percent_candidate_catchment_demand: "%",
    percent: "%", score_0_100: "điểm", VND: "đồng", kW: "kW",
  };
  return `${value} ${units[metric.unit] ?? metric.unit}`;
}

function signedDifference(value: number, digits = 1): string {
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(digits)}`;
}

function criterionLabel(id: string): string {
  const labels: Record<string, string> = {
    demand_potential: "Nhu cầu sạc", demand_coverage: "Nhu cầu sạc", marginal_coverage: "Nhu cầu được phủ thêm",
    grid_site_readiness: "Điều kiện mặt bằng và nguồn điện", network_segment_fit: "Phù hợp với khu vực",
    network_gap_fit: "Khoảng trống trạm hiện có", inside_boundary: "Trong khu vực khảo sát",
    site_access: "Lối vào địa điểm", safety_permit: "Giấy phép và an toàn", grid_capacity: "Nguồn điện",
    road_access: "Đường tiếp cận", charger_configuration: "Cấu hình trạm sạc",
    candidate_type: "Loại địa điểm", site_rights: "Quyền sử dụng đất",
    candidate_spacing: "Khoảng cách tới trạm hiện có", individual_budget: "Ngân sách xây trạm",
  };
  return labels[id] ?? id.replaceAll("_", " ");
}

function constraintStatusLabel(status: PlanningConstraintStatus | undefined): string {
  const labels = { pass: "Đạt", fail: "Không đạt", conditional: "Cần xác minh", unknown: "Cần xác minh", not_applicable: "Không áp dụng" };
  return status ? labels[status] : "Chưa có dữ liệu";
}

function runStatusLabel(status: PlanningRunStatus): string {
  const labels: Record<PlanningRunStatus, string> = {
    completed: "Hoàn tất",
    completed_with_unknowns: "Hoàn tất, còn thiếu dữ liệu",
    invalid_input: "Chưa thể chạy với dữ liệu này",
    no_feasible_candidates: "Không có địa điểm phù hợp",
    failed: "Đánh giá chưa thành công",
  };
  return labels[status];
}

function MetricCell({ label, metric }: { label: string; metric: PlanningMetric | undefined }) {
  return (
    <div className="planner-metric-cell">
      <span>{label}</span>
      <strong>{metricValue(metric)}</strong>
    </div>
  );
}

function CandidateCard({
  item,
  label,
  selected,
  compared,
  compareDisabled,
  onSelect,
  onCompare,
}: {
  item: PlanningRecommendation;
  label: string;
  selected: boolean;
  compared: boolean;
  compareDisabled: boolean;
  onSelect: () => void;
  onCompare: () => void;
}) {
  return (
    <article className={`planner-candidate-card${selected ? " selected" : ""}`}>
      <button type="button" className="planner-candidate-focus" aria-pressed={selected} onClick={onSelect}>
        <span className="planner-rank">{item.rank}</span>
        <span className="planner-candidate-main">
          <strong>{label}</strong>
          <small>{item.eligibility === "eligible" ? "Đạt điều kiện sàng lọc" : "Cần xác minh"}</small>
          <span className="planner-card-metrics">
            <span>Nhu cầu <b>{metricValue(item.metrics.demand_potential)}</b></span>
            <span>Độ phủ <b>{metricValue(item.metrics.coverage_gain)}</b></span>
            <span>Công suất <b>{metricValue(item.metrics.recommended_capacity)}</b></span>
            <span>Chi phí <b>{metricValue(item.metrics.estimated_cost)}</b></span>
          </span>
        </span>
        <span className="planner-score">{item.technical_score.toFixed(0)}<small>/100</small></span>
      </button>
      <button
        type="button"
        className="planner-compare-button"
        aria-pressed={compared}
        disabled={compareDisabled}
        onClick={onCompare}
      >
        {compared ? "Bỏ khỏi so sánh" : "So sánh"}
      </button>
    </article>
  );
}

function ComparisonTable({ items, labels }: { items: [PlanningRecommendation, PlanningRecommendation]; labels: Record<string, string> }) {
  const [first, second] = items;
  const metricRows = [
    ["Nhu cầu", "demand_potential"],
    ["Độ phủ tăng thêm", "coverage_gain"],
    ["Công suất gợi ý", "recommended_capacity"],
    ["Chi phí ước tính", "estimated_cost"],
  ] as const;
  const componentIds = [...new Set([...first.score_breakdown, ...second.score_breakdown].map((part) => part.component_id))];
  const constraintIds = [...new Set([...first.constraints, ...second.constraints].map((constraint) => constraint.id))];
  const delta = (key: (typeof metricRows)[number][1]) => {
    const left = first.metrics[key];
    const right = second.metrics[key];
    if (typeof left?.value !== "number" || typeof right?.value !== "number" || left.unit !== right.unit) {
      return "Chưa thể so sánh";
    }
    const difference = right.value - left.value;
    return `${difference > 0 ? "+" : difference < 0 ? "−" : ""}${metricValue({ ...left, value: Math.abs(difference) })}`;
  };

  return (
    <section className="planner-comparison" aria-label="So sánh hai phương án">
      <div className="planner-results-subheading">
        <h3>So sánh phương án</h3>
        <span>Chênh lệch số liệu = B − A; không tự đánh giá tốt/xấu</span>
      </div>
      <div className="planner-comparison-scroll">
        <table>
          <thead><tr><th>Tiêu chí</th><th>A · {labels[first.candidate_id] ?? first.candidate_id}</th><th>B · {labels[second.candidate_id] ?? second.candidate_id}</th><th>Chênh lệch</th></tr></thead>
          <tbody>
            <tr><th>Thứ hạng</th><td>#{first.rank}</td><td>#{second.rank}</td><td>—</td></tr>
            <tr><th>Điểm kỹ thuật</th><td>{first.technical_score.toFixed(1)}/100</td><td>{second.technical_score.toFixed(1)}/100</td><td>{signedDifference(second.technical_score - first.technical_score)} điểm</td></tr>
            <tr><th>Điều kiện</th><td>{first.eligibility === "eligible" ? "Đạt sàng lọc" : "Cần xác minh"}</td><td>{second.eligibility === "eligible" ? "Đạt sàng lọc" : "Cần xác minh"}</td><td>—</td></tr>
            {metricRows.map(([label, key]) => (
              <tr key={key}>
                <th>{label}</th>
                <td>{metricValue(first.metrics[key])}</td>
                <td>{metricValue(second.metrics[key])}</td>
                <td>{delta(key)}</td>
              </tr>
            ))}
            {componentIds.length > 0 && <tr><th colSpan={4}>Thành phần điểm</th></tr>}
            {componentIds.map((id) => {
              const left = first.score_breakdown.find((part) => part.component_id === id);
              const right = second.score_breakdown.find((part) => part.component_id === id);
              const scoreDelta = typeof left?.score === "number" && typeof right?.score === "number"
                ? `${(right.score - left.score).toFixed(1)} điểm`
                : "Chưa thể so sánh";
              return (
                <tr key={`component-${id}`}>
                  <th>{criterionLabel(id)}</th>
                  <td>{left?.score === null || left === undefined ? "Chưa có điểm" : `${left.score.toFixed(1)} điểm`}</td>
                  <td>{right?.score === null || right === undefined ? "Chưa có điểm" : `${right.score.toFixed(1)} điểm`}</td>
                  <td>{scoreDelta}</td>
                </tr>
              );
            })}
            {constraintIds.length > 0 && <tr><th colSpan={4}>Điều kiện</th></tr>}
            {constraintIds.map((id) => {
              const left = first.constraints.find((constraint) => constraint.id === id);
              const right = second.constraints.find((constraint) => constraint.id === id);
              return (
                <tr key={`constraint-${id}`}>
                  <th>{criterionLabel(id)}</th>
                  <td>{constraintStatusLabel(left?.status)}</td>
                  <td>{constraintStatusLabel(right?.status)}</td>
                  <td>—</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function CandidateExplanation({ item, label }: { item: PlanningRecommendation; label: string }) {
  const scored = item.score_breakdown.filter((part) => part.score !== null);
  const missing = item.score_breakdown.filter((part) => part.score === null);
  const pending = item.constraints.filter((constraint) => constraint.status === "unknown" || constraint.status === "conditional");
  const failed = item.constraints.filter((constraint) => constraint.status === "fail");
  const dataStatuses = [...new Set(item.provenance.map((source) => source.status))]
    .filter((status) => status !== "unknown" && status !== "not_applicable");
  return (
    <section className="planner-explanation" aria-label={`Giải thích ${item.candidate_id}`}>
      <div className="planner-explanation-heading">
        <div>
          <span className="planner-eyebrow">Giải thích địa điểm · hạng {item.rank}</span>
          <h3>{label}</h3>
        </div>
        <span className={`planner-eligibility ${item.eligibility}`}>{item.eligibility === "eligible" ? "Đạt sàng lọc" : "Cần xác minh"}</span>
      </div>
      <div className="planner-metric-grid">
        <MetricCell label="Nhu cầu" metric={item.metrics.demand_potential} />
        <MetricCell label="Độ phủ tăng thêm" metric={item.metrics.coverage_gain} />
        <MetricCell label="Công suất gợi ý" metric={item.metrics.recommended_capacity} />
        <MetricCell label="Chi phí ước tính" metric={item.metrics.estimated_cost} />
      </div>
      <div className="planner-explanation-grid">
        <section>
          <h4>Thành phần điểm</h4>
          {scored.length ? scored.map((part) => (
            <div className="planner-explanation-row" key={part.component_id}>
              <span>{criterionLabel(part.component_id)}</span>
              <b>{part.score?.toFixed(1)}/100{part.contribution_points !== null && <small>đóng góp {part.contribution_points.toFixed(1)} điểm</small>}</b>
            </div>
          )) : <p className="planner-summary-note">Chưa đủ dữ liệu để giải thích điểm.</p>}
          {missing.length > 0 && <p className="planner-summary-note">Chưa chấm: {missing.map((part) => criterionLabel(part.component_id).toLowerCase()).join(", ")}.</p>}
          <p className="planner-summary-note">Điểm chỉ dựa trên các tiêu chí đã có dữ liệu.</p>
        </section>
        <section>
          <h4>Cần xác minh</h4>
          {pending.length > 0
            ? <ul className="planner-checklist">{pending.map((constraint) => <li key={constraint.id}>{criterionLabel(constraint.id)}</li>)}</ul>
            : <p className="planner-summary-note">Không còn điều kiện chờ xác minh trong dữ liệu hiện tại.</p>}
          {failed.length > 0 && <p className="planner-summary-note constraint-fail">Không đạt: {failed.map((constraint) => criterionLabel(constraint.id)).join(", ")}.</p>}
        </section>
      </div>
      <section className="planner-provenance">
        <h4>Nguồn dữ liệu</h4>
        <p className="planner-summary-note">{dataStatuses.length ? dataStatuses.map(statusLabel).join(" · ") : "Chưa có nguồn được xác minh"}. Kết quả dùng để sàng lọc địa điểm.</p>
      </section>
    </section>
  );
}

export default function PlannerView({ onModeChange }: PlannerViewProps) {
  const [demo, setDemo] = useState<PlanningDemoSnapshotResponse | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [asOf, setAsOf] = useState(localDateTimeNow);
  const [horizonYears, setHorizonYears] = useState(3);
  const [seed, setSeed] = useState(20261013);
  const [configVersion, setConfigVersion] = useState("technical-demo-v1");
  const [demandScenario, setDemandScenario] = useState<"low" | "base" | "high">("base");
  const [selectedCandidateIds, setSelectedCandidateIds] = useState<string[]>([]);
  const [coverageMinutes, setCoverageMinutes] = useState(15);
  const [chargerType, setChargerType] = useState<"AC" | "DC">("DC");
  const [portCount, setPortCount] = useState(4);
  const [powerKw, setPowerKw] = useState(80);
  const [budgetVnd, setBudgetVnd] = useState("");
  const [response, setResponse] = useState<PlanningRecommendationResponse | null>(null);
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null);
  const candidateLabels = useMemo(() => Object.fromEntries((demo?.candidates ?? []).map((candidate) => [candidate.candidate_id, candidate.label])), [demo]);
  const [comparisonIds, setComparisonIds] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [requestError, setRequestError] = useState<string | null>(null);

  const selectedCandidate = useMemo(
    () => response?.recommendations.find((item) => item.candidate_id === selectedCandidateId) ?? null,
    [response, selectedCandidateId],
  );
  const comparisonItems = useMemo(() => {
    if (comparisonIds.length !== 2) return null;
    const first = response?.recommendations.find((item) => item.candidate_id === comparisonIds[0]);
    const second = response?.recommendations.find((item) => item.candidate_id === comparisonIds[1]);
    return first && second ? [first, second] as [PlanningRecommendation, PlanningRecommendation] : null;
  }, [comparisonIds, response]);

  const clearResultsForInputChange = () => {
    setResponse(null);
    setSelectedCandidateId(null);
    setComparisonIds([]);
    setRequestError(null);
  };

  useEffect(() => {
    let active = true;
    api.planningDemoSnapshot().then((snapshot) => {
      if (!active) return;
      setDemo(snapshot);
      setHorizonYears(snapshot.defaults.horizon_years);
      setSeed(snapshot.defaults.seed);
      setConfigVersion(snapshot.defaults.config_version);
      setDemandScenario(snapshot.defaults.demand_scenario);
      setCoverageMinutes(snapshot.defaults.coverage_minutes);
      setChargerType(snapshot.defaults.charger_option.charger_type);
      setPortCount(snapshot.defaults.charger_option.port_count);
      setPowerKw(snapshot.defaults.charger_option.power_kw_per_port);
      setBudgetVnd(snapshot.defaults.budget_vnd === null ? "" : String(snapshot.defaults.budget_vnd));
      const availableCandidateIds = new Set(snapshot.candidates.map((candidate) => candidate.candidate_id));
      const demoCandidateIds = M5_DEMO_CANDIDATE_IDS.filter((candidateId) => availableCandidateIds.has(candidateId));
      setSelectedCandidateIds(
        demoCandidateIds.length === M5_DEMO_CANDIDATE_IDS.length
          ? demoCandidateIds
          : snapshot.candidates.slice(0, 3).map((candidate) => candidate.candidate_id),
      );
    }).catch((error: unknown) => {
      if (active) setCatalogError(error instanceof Error ? error.message : "Không tải được snapshot planning.");
    }).finally(() => {
      if (active) setCatalogLoading(false);
    });
    return () => { active = false; };
  }, []);

  const runScenario = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    setRequestError(null);
    setResponse(null);
    setSelectedCandidateId(null);
    setComparisonIds([]);
    if (!demo || selectedCandidateIds.length === 0) {
      setBusy(false);
      setRequestError("Chọn ít nhất một địa điểm để đánh giá.");
      return;
    }
    const request: PlanningRequest = {
      contract_version: "0.1",
      study_area: demo.study_area,
      run: {
        as_of: new Date(asOf).toISOString(),
        horizon_years: horizonYears,
        data_snapshot_id: demo.snapshot.data_snapshot_id,
        seed,
        config_version: configVersion.trim() || null,
        demand_scenario: demandScenario,
      },
      candidate_source: { mode: "provided", candidate_ids: selectedCandidateIds },
      profile: "technical_opportunity",
      technical: {
        coverage_minutes: coverageMinutes,
        charger_options: [{ charger_type: chargerType, port_count: portCount, power_kw_per_port: powerKw }],
        budget_vnd: budgetVnd.trim() ? Number(budgetVnd) : null,
      },
      policy_package: null,
      finance_package: null,
    };
    try {
      const result = await api.planningRecommendations(request);
      setResponse(result);
      setSelectedCandidateId(result.recommendations[0]?.candidate_id ?? null);
    } catch (error) {
      setRequestError(error instanceof Error ? error.message : "Không thể gọi API planning.");
    } finally {
      setBusy(false);
    }
  };

  const toggleCandidate = (candidateId: string) => {
    clearResultsForInputChange();
    setSelectedCandidateIds((current) => current.includes(candidateId)
      ? current.filter((id) => id !== candidateId)
      : [...current, candidateId]);
  };

  const toggleComparison = (candidateId: string) => {
    setComparisonIds((current) => {
      if (current.includes(candidateId)) return current.filter((id) => id !== candidateId);
      if (current.length >= 2) return current;
      return [...current, candidateId];
    });
  };

  return (
    <main className="app-shell planner-app-shell">
      <div className="workspace planner-workspace">
        <section className="control-column planner-control-column">
          <AppModeSwitch active="planner" onChange={onModeChange} />
          <div className="planner-heading">
            <span className="planner-eyebrow">Quy hoạch trạm sạc · Demo</span>
            <h1>Khám phá địa điểm đề xuất</h1>
            <p>Xem nơi có nhu cầu sạc cao và so sánh các địa điểm có thể đặt trạm.</p>
          </div>

          <form className="planner-form" onSubmit={(event) => void runScenario(event)}>
            <div className="planner-form-section">
              <div className="planner-section-heading"><span>01</span><h2>Phạm vi và dữ liệu</h2></div>
              {catalogLoading && <p className="planner-muted">Đang tải dữ liệu khu vực…</p>}
              {catalogError && <div className="planner-alert error" role="alert">{catalogError}</div>}
              {demo && (
                <>
                  <div className="planner-demo-meta">
                    <span>Khu vực <b>{demo.study_area.city_id}</b></span>
                    <span>Phạm vi <b>9 phường</b></span>
                    <span>Địa điểm <b>{demo.candidates.length}</b></span>
                    <details className="planner-data-details"><summary>Thông tin bộ dữ liệu</summary><span>{demo.snapshot.data_snapshot_id}</span><span>Ranh giới {demo.study_area.boundary_version}</span></details>
                  </div>
                  <fieldset className="planner-candidate-select" disabled={catalogLoading || busy}>
                    <legend>Địa điểm muốn so sánh</legend>
                    <div className="planner-candidate-select-actions">
                      <span>{selectedCandidateIds.length} đã chọn</span>
                      <button type="button" onClick={() => { clearResultsForInputChange(); setSelectedCandidateIds(demo.candidates.map((item) => item.candidate_id)); }}>Chọn tất cả</button>
                      <button type="button" onClick={() => { clearResultsForInputChange(); setSelectedCandidateIds([]); }}>Bỏ chọn</button>
                    </div>
                    <div className="planner-candidate-select-list">
                      {demo.candidates.map((candidate) => (
                        <label key={candidate.candidate_id}>
                          <input
                            type="checkbox"
                            checked={selectedCandidateIds.includes(candidate.candidate_id)}
                            onChange={() => toggleCandidate(candidate.candidate_id)}
                          />
                          <span><b>{candidate.label}</b><small>{candidate.candidate_id} · vị trí giả lập</small></span>
                        </label>
                      ))}
                    </div>
                    {selectedCandidateIds.length === 0 && <small className="planner-field-error">Chọn ít nhất một địa điểm để đánh giá.</small>}
                  </fieldset>
                </>
              )}
            </div>

            <div className="planner-form-section">
              <div className="planner-section-heading"><span>02</span><h2>Nhu cầu và trạm sạc</h2></div>
              <div className="planner-profile-row">
                <span>Cách đánh giá</span><strong>Nhu cầu và độ phủ</strong>
              </div>
              <label>
                Mức nhu cầu sạc
                <select value={demandScenario} onChange={(event) => { clearResultsForInputChange(); setDemandScenario(event.target.value as "low" | "base" | "high"); }}>
                  <option value="low">Thấp · 60% mức thông thường</option>
                  <option value="base">Thông thường</option>
                  <option value="high">Cao · 160% mức thông thường</option>
                </select>
                <span className="planner-label-note">Màu trên bản đồ cập nhật ngay theo lượt sạc dự kiến trong một tuần mô phỏng.</span>
              </label>
              <div className="planner-field-pair">
                <label>Thời gian đến trạm tối đa (phút)<input type="number" min={1} value={coverageMinutes} onChange={(event) => { clearResultsForInputChange(); setCoverageMinutes(Number(event.target.value)); }} required /></label>
                <label>Chi phí xây mỗi trạm tối đa (đồng)<input type="number" min={0} value={budgetVnd} onChange={(event) => { clearResultsForInputChange(); setBudgetVnd(event.target.value); }} placeholder="Không giới hạn" /></label>
              </div>
              <div className="planner-field-pair">
                <label>Loại sạc<select value={chargerType} onChange={(event) => { clearResultsForInputChange(); setChargerType(event.target.value as "AC" | "DC"); }}><option value="DC">Sạc nhanh (DC)</option><option value="AC">Sạc thường (AC)</option></select></label>
                <label>Số cổng sạc mỗi trạm<input type="number" min={1} value={portCount} onChange={(event) => { clearResultsForInputChange(); setPortCount(Number(event.target.value)); }} required /></label>
              </div>
              <label>Công suất mỗi cổng (kW)<input type="number" min={0.1} step={0.1} value={powerKw} onChange={(event) => { clearResultsForInputChange(); setPowerKw(Number(event.target.value)); }} required /></label>
              <p className="planner-illustrative-note">Thời gian đến trạm là ước tính. Chi phí mẫu áp dụng cho trạm sạc nhanh 4 cổng × 80 kW; để trống ngân sách nếu chưa muốn giới hạn.</p>
              <details className="planner-extra-settings">
                <summary>Thông tin lần đánh giá</summary>
                <label>Thời điểm đánh giá<input type="datetime-local" value={asOf} onChange={(event) => { clearResultsForInputChange(); setAsOf(event.target.value); }} required /></label>
                <label>Thời gian dự kiến (năm)<input type="number" min={1} value={horizonYears} onChange={(event) => { clearResultsForInputChange(); setHorizonYears(Number(event.target.value)); }} required /></label>
                <p className="planner-label-note">Hai thông tin này được lưu cùng lần đánh giá. Demo vẫn dùng một tuần dữ liệu mẫu, chưa dự báo nhu cầu theo năm.</p>
              </details>
            </div>

            <div className="planner-package-note">
              Demo chưa tính lợi nhuận hay thời gian hoàn vốn. Chi phí là số liệu mô phỏng; đổi cấu hình trạm có thể khiến chi phí chưa xác định.
            </div>
            <button className="planner-run-button" type="submit" disabled={busy || catalogLoading || !demo || selectedCandidateIds.length === 0}>
              {busy ? "Đang đánh giá…" : "Đánh giá địa điểm"}
            </button>
          </form>
        </section>

        <section className="map-column planner-results-column">
          <div className="planner-results-header">
            <div><span className="planner-eyebrow">Kết quả và bản đồ</span><h2>Bản đồ nhu cầu và địa điểm</h2></div>
            {response && <span className={`planner-run-status ${response.status}`}>{runStatusLabel(response.status)}</span>}
          </div>

          {requestError && <div className="planner-alert error" role="alert">{requestError}</div>}
          {response && (
            <>
              <details className="planner-run-details">
                <summary>Thông tin lần đánh giá</summary>
                <div className="planner-run-meta">
                <span>Run <b>{response.run_id}</b></span>
                <span>Snapshot <b>{response.scenario.data_snapshot_id}</b></span>
                <span>Nhu cầu <b>{DEMAND_SCENARIO_LABELS[response.scenario.demand_scenario]}</b></span>
                <span>Algorithm <b>{response.scenario.algorithm_version ?? "Chưa có"}</b></span>
                <span>Config <b>{response.scenario.config_version ?? "Chưa có"}</b></span>
                </div>
              </details>
              {response.warnings.length > 0 && (
                <div className="planner-warnings" role="status">
                  <p>Dữ liệu mô phỏng cho 9 phường. Thời gian tiếp cận là ước tính; điều kiện đất, điện và giấy phép cần xác minh.</p>
                </div>
              )}
            </>
          )}

          <div className="planner-map-area">
            <PlannerMap
              recommendations={response?.recommendations ?? []}
              candidates={demo?.candidates ?? []}
              existingSites={demo?.existing_sites ?? []}
              demandNodes={demo?.demand_nodes ?? []}
              boundaryGeometry={demo?.snapshot.geometry ?? null}
              coverageMinutes={coverageMinutes}
              demandScenario={demandScenario}
              selectedCandidateIds={selectedCandidateIds}
              selectedCandidateId={selectedCandidateId}
              onSelect={setSelectedCandidateId}
            />
            <div className="planner-boundary-note">
              Vàng → đỏ: nhu cầu từ thấp đến cao. Vùng màu được làm mượt từ dữ liệu mô phỏng, không phải ranh giới phục vụ. Đổi thời gian đến trạm rồi đánh giá lại để cập nhật độ phủ và thứ hạng.
            </div>
          </div>

          {response && response.recommendations.length > 0 && (
            <div className="planner-candidate-results">
              <div className="planner-results-subheading"><h3>Phương án được xếp hạng</h3><span>{response.recommendations.length} địa điểm</span></div>
              <p className="planner-ranking-note">Thứ hạng so sánh điểm đánh giá trong kịch bản hiện tại; địa điểm vẫn cần xác minh thực tế trước khi xây trạm.</p>
              <div className="planner-candidate-list">
                {response.recommendations.map((item) => (
                  <CandidateCard
                    key={item.candidate_id}
                    item={item}
                    label={candidateLabels[item.candidate_id] ?? item.candidate_id}
                    selected={item.candidate_id === selectedCandidateId}
                    compared={comparisonIds.includes(item.candidate_id)}
                    compareDisabled={comparisonIds.length >= 2 && !comparisonIds.includes(item.candidate_id)}
                    onSelect={() => setSelectedCandidateId(item.candidate_id)}
                    onCompare={() => toggleComparison(item.candidate_id)}
                  />
                ))}
              </div>
              {comparisonIds.length === 1 && <p className="planner-comparison-hint">Chọn thêm một địa điểm để so sánh hai phương án.</p>}
              {comparisonItems && <ComparisonTable items={comparisonItems} labels={candidateLabels} />}
              {selectedCandidate && <CandidateExplanation item={selectedCandidate} label={candidateLabels[selectedCandidate.candidate_id] ?? selectedCandidate.candidate_id} />}
            </div>
          )}

          {response && response.recommendations.length === 0 && (
            <div className="planner-empty-state">
              <strong>{response.status === "no_feasible_candidates" ? "Không có địa điểm phù hợp" : "Chưa có kết quả để xếp hạng"}</strong>
              <p>Kiểm tra dữ liệu, địa điểm đã chọn và giới hạn ngân sách rồi đánh giá lại.</p>
            </div>
          )}

          {response && (response.unranked_candidates.length > 0 || response.excluded_candidates.length > 0) && (
            <div className="planner-other-candidates">
              {response.unranked_candidates.length > 0 && (
                <details open>
                  <summary>Chưa đủ bằng chứng để xếp hạng · {response.unranked_candidates.length}</summary>
                  {response.unranked_candidates.map((candidate) => <p key={candidate.candidate_id}><b>{candidateLabels[candidate.candidate_id] ?? candidate.candidate_id}</b> — chưa đủ dữ liệu để chấm điểm.</p>)}
                </details>
              )}
              {response.excluded_candidates.length > 0 && (
                <details open>
                  <summary>Không đáp ứng điều kiện · {response.excluded_candidates.length}</summary>
                  {response.excluded_candidates.map((candidate) => <p key={candidate.candidate_id}><b>{candidateLabels[candidate.candidate_id] ?? candidate.candidate_id}</b> — {candidate.constraints.map((constraint) => `${criterionLabel(constraint.id)}: ${constraintStatusLabel(constraint.status).toLowerCase()}`).join("; ")}</p>)}
                </details>
              )}
            </div>
          )}

          {!response && !requestError && !busy && (
            <div className="planner-empty-state initial">
              <strong>{catalogLoading ? "Đang tải dữ liệu" : "Chưa đánh giá địa điểm"}</strong>
              <p>{catalogLoading ? "Đang tải khu vực, nhu cầu và các trạm sạc." : "Chọn mức nhu cầu và địa điểm bên trái, sau đó bấm Đánh giá địa điểm để xem kết quả."}</p>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
