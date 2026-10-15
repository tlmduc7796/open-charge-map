import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { api } from "../api";
import AppModeSwitch, { type AppMode } from "./AppModeSwitch";
import PlannerMap from "./PlannerMap";
import { buildPlannerReport, downloadPlannerReport } from "./plannerReport";
import type {
  PlanningDemoSnapshotResponse,
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

function metricValue(metric: PlanningMetric | undefined): string {
  if (!metric || metric.value === null) return "—";
  const value = typeof metric.value === "number"
    ? metric.value.toLocaleString("vi-VN", { maximumFractionDigits: metric.unit === "VND" ? 0 : 1 })
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

function runStatusLabel(status: PlanningRunStatus): string {
  const labels: Record<PlanningRunStatus, string> = {
    completed: "Đã đánh giá",
    completed_with_unknowns: "Đã đánh giá",
    invalid_input: "Chưa thể chạy với dữ liệu này",
    no_feasible_candidates: "Không có kết quả",
    failed: "Đánh giá chưa thành công",
  };
  return labels[status];
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
    ["Công suất", "recommended_capacity"],
    ["Chi phí ước tính", "estimated_cost"],
  ] as const;
  const componentIds = first.score_breakdown.filter((part) => part.score !== null && second.score_breakdown.some((other) => other.component_id === part.component_id && other.score !== null)).map((part) => part.component_id);
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
        <span>Chênh lệch B − A</span>
      </div>
      <div className="planner-comparison-scroll">
        <table>
          <thead><tr><th>Tiêu chí</th><th>A · {labels[first.candidate_id] ?? first.candidate_id}</th><th>B · {labels[second.candidate_id] ?? second.candidate_id}</th><th>Chênh lệch</th></tr></thead>
          <tbody>
            <tr><th>Thứ hạng</th><td>#{first.rank}</td><td>#{second.rank}</td><td>—</td></tr>
            <tr><th>Điểm kỹ thuật</th><td>{first.technical_score.toFixed(1)}/100</td><td>{second.technical_score.toFixed(1)}/100</td><td>{signedDifference(second.technical_score - first.technical_score)} điểm</td></tr>
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
          </tbody>
        </table>
      </div>
    </section>
  );
}

function CandidateExplanation({ item, label }: { item: PlanningRecommendation; label: string }) {
  const scored = item.score_breakdown.filter((part) => part.score !== null);
  if (!scored.length) return null;
  return (
    <section className="planner-explanation" aria-label={`Giải thích ${item.candidate_id}`}>
      <details>
        <summary>Điểm đánh giá · {label}</summary>
        <div className="planner-score-breakdown">
          {scored.map((part) => (
            <div className="planner-explanation-row" key={part.component_id}>
              <span>{criterionLabel(part.component_id)}</span>
              <b>{part.score?.toFixed(1)}/100{part.contribution_points !== null && <small>đóng góp {part.contribution_points.toFixed(1)} điểm</small>}</b>
            </div>
          ))}
        </div>
      </details>
    </section>
  );
}

function searchable(value: string): string {
  return value.toLocaleLowerCase("vi").normalize("NFD").replace(/\p{M}/gu, "").replaceAll("đ", "d");
}

export default function PlannerView({ onModeChange }: PlannerViewProps) {
  const [demo, setDemo] = useState<PlanningDemoSnapshotResponse | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [asOf] = useState(localDateTimeNow);
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
  const [reportRequest, setReportRequest] = useState<PlanningRequest | null>(null);
  const [candidateQuery, setCandidateQuery] = useState("");
  const [controlsOpen, setControlsOpen] = useState(false);
  const [mapExpanded, setMapExpanded] = useState(false);
  const resultsHeadingRef = useRef<HTMLHeadingElement>(null);
  const visibleCandidates = useMemo(() => (demo?.candidates ?? []).filter((candidate) => searchable(candidate.label).includes(searchable(candidateQuery))), [demo, candidateQuery]);
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
    setReportRequest(null);
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

  useEffect(() => {
    if (!mapExpanded) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMapExpanded(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [mapExpanded]);

  useEffect(() => {
    if (!response || window.innerWidth > 820) return;
    const frame = requestAnimationFrame(() => resultsHeadingRef.current?.closest(".planner-results-header")?.scrollIntoView?.({ behavior: "smooth", block: "start" }));
    return () => cancelAnimationFrame(frame);
  }, [response]);

  const runScenario = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    setRequestError(null);
    setResponse(null);
    setReportRequest(null);
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
      setReportRequest(request);
      setControlsOpen(false);
      resultsHeadingRef.current?.focus({ preventScroll: true });
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
    <main className={`app-shell planner-app-shell${mapExpanded ? " planner-map-expanded" : ""}`}>
      <div className="workspace planner-workspace">
        <section className={`control-column planner-control-column${controlsOpen ? " controls-open" : ""}`} aria-label="Thiết lập Planner">
          <AppModeSwitch active="planner" onChange={onModeChange} />
          <div className="planner-heading">
            <div><span className="planner-eyebrow">Planner · Demo</span><h1>Quy hoạch trạm sạc</h1></div>
            <button type="button" className="planner-mobile-settings-toggle" aria-expanded={controlsOpen} aria-controls="planner-settings" onClick={() => setControlsOpen((open) => !open)}>
              {controlsOpen ? "Đóng thiết lập" : "Thiết lập"}
            </button>
          </div>
          <form id="planner-settings" className="planner-form" onSubmit={(event) => void runScenario(event)}>
            <fieldset className="planner-form-fields" disabled={busy || catalogLoading}>
              {catalogLoading && <p className="planner-muted">Đang tải địa điểm…</p>}
              <section className="planner-form-section">
                <div className="planner-section-heading"><span>01</span><h2>Kịch bản đánh giá</h2></div>
                <label>Mức nhu cầu sạc
                  <select value={demandScenario} onChange={(event) => { clearResultsForInputChange(); setDemandScenario(event.target.value as "low" | "base" | "high"); }}>
                    <option value="low">Thấp</option><option value="base">Thông thường</option><option value="high">Cao</option>
                  </select>
                </label>
                <label>Thời gian đến trạm tối đa (phút)<input type="number" min={1} value={coverageMinutes} onChange={(event) => { clearResultsForInputChange(); setCoverageMinutes(Number(event.target.value)); }} required /></label>
                <label>Chi phí xây mỗi trạm tối đa (đồng)<input type="number" min={0} value={budgetVnd} onChange={(event) => { clearResultsForInputChange(); setBudgetVnd(event.target.value); }} placeholder="Không giới hạn" /></label>
                <details className="planner-extra-settings">
                  <summary>Cấu hình trạm <span>{chargerType} · {portCount} cổng × {powerKw} kW</span></summary>
                  <label>Loại sạc<select value={chargerType} onChange={(event) => { clearResultsForInputChange(); setChargerType(event.target.value as "AC" | "DC"); }}><option value="DC">Sạc nhanh (DC)</option><option value="AC">Sạc thường (AC)</option></select></label>
                  <div className="planner-field-pair">
                    <label>Số cổng sạc mỗi trạm<input type="number" min={1} value={portCount} onChange={(event) => { clearResultsForInputChange(); setPortCount(Number(event.target.value)); }} required /></label>
                    <label>Công suất mỗi cổng (kW)<input type="number" min={0.1} step={0.1} value={powerKw} onChange={(event) => { clearResultsForInputChange(); setPowerKw(Number(event.target.value)); }} required /></label>
                  </div>
                </details>
              </section>
              {demo && (
                <section className="planner-form-section">
                  <div className="planner-section-heading"><span>02</span><h2>Chọn địa điểm</h2><b>{selectedCandidateIds.length}/{demo.candidates.length}</b></div>
                  <input className="planner-candidate-search" type="search" aria-label="Tìm địa điểm" placeholder="Tìm tên địa điểm…" value={candidateQuery} onChange={(event) => setCandidateQuery(event.target.value)} />
                  <div className="planner-candidate-select-actions">
                    <span>{selectedCandidateIds.length} đã chọn</span>
                    <button type="button" onClick={() => { clearResultsForInputChange(); setSelectedCandidateIds((current) => [...new Set([...current, ...visibleCandidates.map((item) => item.candidate_id)])]); }}>{candidateQuery ? "Chọn kết quả" : "Chọn tất cả"}</button>
                    <button type="button" onClick={() => { clearResultsForInputChange(); const visibleIds = new Set(visibleCandidates.map((item) => item.candidate_id)); setSelectedCandidateIds((current) => current.filter((id) => !visibleIds.has(id))); }}>Bỏ chọn</button>
                  </div>
                  <div className="planner-candidate-select-list" role="group" aria-label="Địa điểm muốn so sánh">
                    {visibleCandidates.map((candidate) => (
                      <label key={candidate.candidate_id} className={selectedCandidateIds.includes(candidate.candidate_id) ? "is-selected" : ""}>
                        <input type="checkbox" checked={selectedCandidateIds.includes(candidate.candidate_id)} onChange={() => toggleCandidate(candidate.candidate_id)} />
                        <span>{candidate.label}</span>
                      </label>
                    ))}
                    {visibleCandidates.length === 0 && <p className="planner-muted">Không tìm thấy địa điểm.</p>}
                  </div>
                  {selectedCandidateIds.length === 0 && <small className="planner-field-error">Chọn ít nhất một địa điểm để đánh giá.</small>}
                </section>
              )}
            </fieldset>
            <div className="planner-form-actions">
              <button className="planner-run-button" type="submit" disabled={busy || catalogLoading || !demo || selectedCandidateIds.length === 0}>
                {busy ? "Đang đánh giá…" : `Đánh giá địa điểm${selectedCandidateIds.length ? ` (${selectedCandidateIds.length})` : ""}`}
              </button>
            </div>
          </form>
        </section>

        <section className="planner-results-column" aria-label="Bản đồ và kết quả Planner">
          <div className="planner-results-header">
            <div><span className="planner-eyebrow">{demo?.study_area.city_id === "VN-HCMC" ? "TP. Hồ Chí Minh" : "Khu vực khảo sát"}</span><h2 ref={resultsHeadingRef} tabIndex={-1}>Bản đồ quy hoạch</h2></div>
            <div className="planner-header-actions">
              {response && <span className={`planner-run-status ${response.status}`}>{runStatusLabel(response.status)}</span>}
              <button type="button" className="planner-secondary-button" disabled={!response || !reportRequest || busy} onClick={() => {
                if (demo && response && reportRequest) downloadPlannerReport(buildPlannerReport({ demo, request: reportRequest, response }), response.run_id);
              }}>Tải báo cáo</button>
            </div>
          </div>
          {(catalogError || requestError) && <div className="planner-alert error" role="alert">{catalogError ?? requestError}</div>}
          <div className="planner-map-area">
            <div className="planner-map-toolbar">
              <div className="planner-map-context"><span><b>{demo?.existing_sites.length ?? "—"}</b> trạm hiện hữu</span><span><b>{demo?.candidates.length ?? "—"}</b> địa điểm</span></div>
              <div className="planner-map-actions">
                {response && response.recommendations.length > 0 && !mapExpanded && <a href="#planner-results">Xem kết quả ({response.recommendations.length})</a>}
                <button type="button" className="planner-expand-button" aria-pressed={mapExpanded} onClick={() => setMapExpanded((expanded) => !expanded)}>{mapExpanded ? "Thu gọn bản đồ" : "Phóng to bản đồ"}</button>
              </div>
            </div>
            <PlannerMap recommendations={response?.recommendations ?? []} candidates={demo?.candidates ?? []} existingSites={demo?.existing_sites ?? []}
              demandNodes={demo?.demand_nodes ?? []} boundaryGeometry={demo?.snapshot.geometry ?? null} coverageMinutes={coverageMinutes}
              demandScenario={demandScenario} selectedCandidateIds={selectedCandidateIds} selectedCandidateId={selectedCandidateId} onSelect={setSelectedCandidateId} />
          </div>

          {!mapExpanded && response && response.recommendations.length > 0 && (
            <div id="planner-results" className="planner-candidate-results">
              <div className="planner-results-subheading"><h3>Phương án được xếp hạng</h3><span>{response.recommendations.length} địa điểm</span></div>
              <div className="planner-candidate-list">
                {response.recommendations.map((item) => <CandidateCard key={item.candidate_id} item={item} label={candidateLabels[item.candidate_id] ?? item.candidate_id}
                  selected={item.candidate_id === selectedCandidateId} compared={comparisonIds.includes(item.candidate_id)}
                  compareDisabled={comparisonIds.length >= 2 && !comparisonIds.includes(item.candidate_id)} onSelect={() => setSelectedCandidateId(item.candidate_id)} onCompare={() => toggleComparison(item.candidate_id)} />)}
              </div>
              {comparisonIds.length === 1 && <p className="planner-comparison-hint">Chọn thêm một địa điểm để so sánh.</p>}
              {comparisonItems && <ComparisonTable items={comparisonItems} labels={candidateLabels} />}
              {selectedCandidate && <CandidateExplanation item={selectedCandidate} label={candidateLabels[selectedCandidate.candidate_id] ?? selectedCandidate.candidate_id} />}
            </div>
          )}
          {!mapExpanded && response && response.recommendations.length === 0 && <div className="planner-empty-state"><strong>Không có kết quả với thiết lập này</strong><p>Thay đổi thiết lập hoặc tải báo cáo để xem chi tiết.</p></div>}
          {!mapExpanded && !response && !requestError && !busy && <p className="planner-start-hint">Chọn địa điểm và đánh giá để xem thứ hạng trên bản đồ.</p>}
        </section>
      </div>
    </main>
  );
}
