import { useEffect, useMemo, useState, type FormEvent } from "react";

import { api } from "../api";
import AppModeSwitch, { type AppMode } from "./AppModeSwitch";
import PlannerMap from "./PlannerMap";
import type {
  PlanningDataStatus,
  PlanningMetric,
  PlanningRecommendation,
  PlanningRecommendationResponse,
  PlanningRequest,
  PlanningRunStatus,
} from "./types";
import type { Station } from "../types";
import "./planner.css";

interface PlannerViewProps {
  onModeChange: (mode: AppMode) => void;
}

function localDateTimeNow(): string {
  const now = new Date();
  const localOffsetMs = now.getTimezoneOffset() * 60_000;
  return new Date(now.getTime() - localOffsetMs).toISOString().slice(0, 16);
}

function statusLabel(status: PlanningDataStatus): string {
  const labels: Record<PlanningDataStatus, string> = {
    observed: "Đã quan sát",
    proxy: "Proxy",
    synthetic: "Tổng hợp",
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
  return `${value} ${metric.unit}`;
}

function signedDifference(value: number, digits = 1): string {
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(digits)}`;
}

function runStatusLabel(status: PlanningRunStatus): string {
  const labels: Record<PlanningRunStatus, string> = {
    completed: "Hoàn tất",
    completed_with_unknowns: "Hoàn tất, còn thiếu dữ liệu",
    invalid_input: "Chưa thể chạy với dữ liệu này",
    no_feasible_candidates: "Không có candidate khả thi",
    failed: "Run thất bại",
  };
  return labels[status];
}

function MetricCell({ label, metric }: { label: string; metric: PlanningMetric | undefined }) {
  return (
    <div className="planner-metric-cell">
      <span>{label}</span>
      <strong>{metricValue(metric)}</strong>
      <small>{metric ? statusLabel(metric.status) : "Chưa có dữ liệu"}</small>
    </div>
  );
}

function CandidateCard({
  item,
  selected,
  compared,
  compareDisabled,
  onSelect,
  onCompare,
}: {
  item: PlanningRecommendation;
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
          <strong>{item.candidate_id}</strong>
          <small>{item.eligibility === "eligible" ? "Đủ điều kiện" : "Cần xác minh"} · bằng chứng {(item.evidence_coverage * 100).toFixed(0)}%</small>
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

function ComparisonTable({ items }: { items: [PlanningRecommendation, PlanningRecommendation] }) {
  const [first, second] = items;
  const metricRows = [
    ["Nhu cầu", "demand_potential"],
    ["Độ phủ tăng thêm", "coverage_gain"],
    ["Công suất gợi ý", "recommended_capacity"],
    ["Rủi ro quá tải", "overload_risk"],
    ["Chi phí ước tính", "estimated_cost"],
  ] as const;
  const componentIds = [...new Set([...first.score_breakdown, ...second.score_breakdown].map((part) => part.component_id))];
  const constraintIds = [...new Set([...first.constraints, ...second.constraints].map((constraint) => constraint.id))];
  const provenanceRows = [first, second].flatMap((item) => item.provenance.map((source, index) => ({
    id: `${source.field}|${source.source_id ?? source.source_ref ?? index}`,
    field: source.field,
  })));
  const provenanceIds = [...new Set(provenanceRows.map((source) => source.id))];
  const provenanceField = (item: PlanningRecommendation, id: string) => {
    const source = item.provenance.find((entry, index) => `${entry.field}|${entry.source_id ?? entry.source_ref ?? index}` === id);
    if (!source) return "Chưa có nguồn được trả về";
    const reference = source.source_id ?? source.source_ref ?? "Không rõ nguồn";
    const observedAt = source.observed_at ? new Date(source.observed_at).toLocaleString("vi-VN") : "chưa rõ thời điểm";
    return `${reference} · ${statusLabel(source.status)}${source.is_synthetic ? " · tổng hợp" : ""} · ${observedAt}${source.note ? ` · ${source.note}` : ""}`;
  };
  const delta = (key: (typeof metricRows)[number][1]) => {
    const left = first.metrics[key];
    const right = second.metrics[key];
    if (typeof left?.value !== "number" || typeof right?.value !== "number" || left.unit !== right.unit) {
      return "Chưa thể so sánh";
    }
    const difference = right.value - left.value;
    const formatted = Math.abs(difference).toLocaleString("vi-VN", { maximumFractionDigits: 2 });
    return `${difference > 0 ? "+" : difference < 0 ? "−" : ""}${formatted} ${left.unit}`;
  };

  return (
    <section className="planner-comparison" aria-label="So sánh hai phương án">
      <div className="planner-results-subheading">
        <h3>So sánh phương án</h3>
        <span>Chênh lệch số liệu = B − A; không tự đánh giá tốt/xấu</span>
      </div>
      <div className="planner-comparison-scroll">
        <table>
          <thead><tr><th>Tiêu chí</th><th>A · {first.candidate_id}</th><th>B · {second.candidate_id}</th><th>Chênh lệch</th></tr></thead>
          <tbody>
            <tr><th>Thứ hạng</th><td>#{first.rank}</td><td>#{second.rank}</td><td>—</td></tr>
            <tr><th>Điểm kỹ thuật</th><td>{first.technical_score.toFixed(1)}/100</td><td>{second.technical_score.toFixed(1)}/100</td><td>{signedDifference(second.technical_score - first.technical_score)} điểm</td></tr>
            <tr><th>Bằng chứng</th><td>{(first.evidence_coverage * 100).toFixed(0)}%</td><td>{(second.evidence_coverage * 100).toFixed(0)}%</td><td>{signedDifference((second.evidence_coverage - first.evidence_coverage) * 100, 0)} điểm %</td></tr>
            <tr><th>Điều kiện</th><td>{first.eligibility}</td><td>{second.eligibility}</td><td>—</td></tr>
            {metricRows.map(([label, key]) => (
              <tr key={key}>
                <th>{label}</th>
                <td>{metricValue(first.metrics[key])}<small>{first.metrics[key]?.status ?? "unknown"}</small></td>
                <td>{metricValue(second.metrics[key])}<small>{second.metrics[key]?.status ?? "unknown"}</small></td>
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
                  <th>{id.replaceAll("_", " ")}</th>
                  <td>{left?.score === null || left === undefined ? "Chưa có điểm" : `${left.score.toFixed(1)} điểm`}<small>{left?.status ? statusLabel(left.status) : "Không được trả về"} · {left?.reason ?? ""}</small></td>
                  <td>{right?.score === null || right === undefined ? "Chưa có điểm" : `${right.score.toFixed(1)} điểm`}<small>{right?.status ? statusLabel(right.status) : "Không được trả về"} · {right?.reason ?? ""}</small></td>
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
                  <th>{id.replaceAll("_", " ")}</th>
                  <td>{left?.status ?? "Không được trả về"}<small>{left?.reason}</small></td>
                  <td>{right?.status ?? "Không được trả về"}<small>{right?.reason}</small></td>
                  <td>—</td>
                </tr>
              );
            })}
            {provenanceIds.length > 0 && <tr><th colSpan={4}>Nguồn và thời điểm</th></tr>}
            {provenanceIds.map((id) => (
              <tr key={`provenance-${id}`}>
                <th>{provenanceRows.find((source) => source.id === id)?.field ?? "Nguồn"}</th>
                <td>{provenanceField(first, id)}</td>
                <td>{provenanceField(second, id)}</td>
                <td>—</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function CandidateExplanation({ item }: { item: PlanningRecommendation }) {
  return (
    <section className="planner-explanation" aria-label={`Giải thích ${item.candidate_id}`}>
      <div className="planner-explanation-heading">
        <div>
          <span className="planner-eyebrow">Giải thích candidate</span>
          <h3>{item.candidate_id}</h3>
        </div>
        <span className={`planner-eligibility ${item.eligibility}`}>{item.eligibility === "eligible" ? "Đủ điều kiện" : "Có điều kiện"}</span>
      </div>
      <div className="planner-metric-grid">
        <MetricCell label="Nhu cầu" metric={item.metrics.demand_potential} />
        <MetricCell label="Độ phủ tăng thêm" metric={item.metrics.coverage_gain} />
        <MetricCell label="Công suất gợi ý" metric={item.metrics.recommended_capacity} />
        <MetricCell label="Rủi ro quá tải" metric={item.metrics.overload_risk} />
        <MetricCell label="Chi phí ước tính" metric={item.metrics.estimated_cost} />
      </div>
      <div className="planner-explanation-grid">
        <section>
          <h4>Thành phần điểm</h4>
          {item.score_breakdown.length ? item.score_breakdown.map((part) => (
            <div className="planner-explanation-row" key={part.component_id}>
              <span>{part.component_id.replaceAll("_", " ")}<small>{part.reason} · {statusLabel(part.status)} · trọng số {part.weight_percent === null ? "chưa có" : `${part.weight_percent}%`}</small></span>
              <b>{part.score === null ? "Chưa có" : `${part.score.toFixed(1)} điểm`}<small>đóng góp {part.contribution_points === null ? "chưa có" : `${part.contribution_points.toFixed(2)} điểm`}</small></b>
            </div>
          )) : <p className="planner-muted">Chưa có breakdown từ engine.</p>}
        </section>
        <section>
          <h4>Điều kiện</h4>
          {item.constraints.length ? item.constraints.map((constraint) => (
            <div className="planner-explanation-row" key={constraint.id}>
              <span>{constraint.id.replaceAll("_", " ")}<small>{constraint.reason}</small></span>
              <b className={`constraint-${constraint.status}`}>{constraint.status}</b>
            </div>
          )) : <p className="planner-muted">Không có điều kiện cần giải thích.</p>}
        </section>
      </div>
      <section className="planner-provenance">
        <h4>Nguồn dữ liệu</h4>
        {item.provenance.length ? item.provenance.map((source, index) => (
          <div className="planner-source-row" key={`${source.field}-${source.source_id ?? index}`}>
            <span><b>{source.field}</b><small>{source.source_id ?? source.source_ref ?? "Không rõ nguồn"}{source.observed_at ? ` · ${new Date(source.observed_at).toLocaleString("vi-VN")}` : " · chưa rõ thời điểm"}{source.note ? ` · ${source.note}` : ""}</small></span>
            <span className={`provenance-tag ${source.status}`}>
              {source.is_synthetic ? "Tổng hợp · " : ""}{statusLabel(source.status)}
            </span>
          </div>
        )) : <p className="planner-muted">Response chưa có provenance cho candidate này.</p>}
      </section>
    </section>
  );
}

export default function PlannerView({ onModeChange }: PlannerViewProps) {
  const [cityId, setCityId] = useState("VN-HCMC");
  const [boundaryVersion, setBoundaryVersion] = useState("");
  const [pilotExtentId, setPilotExtentId] = useState("");
  const [asOf, setAsOf] = useState(localDateTimeNow);
  const [horizonYears, setHorizonYears] = useState(3);
  const [snapshotId, setSnapshotId] = useState("");
  const [seed, setSeed] = useState(42);
  const [configVersion, setConfigVersion] = useState("");
  const [candidateIdsText, setCandidateIdsText] = useState("");
  const [coverageMinutes, setCoverageMinutes] = useState(15);
  const [chargerType, setChargerType] = useState<"AC" | "DC">("DC");
  const [portCount, setPortCount] = useState(4);
  const [powerKw, setPowerKw] = useState(120);
  const [budgetVnd, setBudgetVnd] = useState("");
  const [response, setResponse] = useState<PlanningRecommendationResponse | null>(null);
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null);
  const [comparisonIds, setComparisonIds] = useState<string[]>([]);
  const [stationCatalog, setStationCatalog] = useState<Station[]>([]);
  const [stationCatalogError, setStationCatalogError] = useState<string | null>(null);
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

  useEffect(() => {
    let active = true;
    api.stations().then((stations) => {
      if (active) setStationCatalog(stations);
    }).catch((error: unknown) => {
      if (active) setStationCatalogError(error instanceof Error ? error.message : "Không tải được danh mục trạm.");
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
    const candidateIds = candidateIdsText
      .split(/[\s,;]+/)
      .map((candidateId) => candidateId.trim())
      .filter(Boolean);
    const request: PlanningRequest = {
      contract_version: "0.1",
      study_area: {
        city_id: cityId,
        boundary_version: boundaryVersion,
        pilot_extent_id: pilotExtentId,
      },
      run: {
        as_of: new Date(asOf).toISOString(),
        horizon_years: horizonYears,
        data_snapshot_id: snapshotId,
        seed,
        config_version: configVersion.trim() || null,
      },
      candidate_source: { mode: "provided", candidate_ids: candidateIds },
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
            <span className="planner-eyebrow">Station planning · MVP</span>
            <h1>Khám phá địa điểm đề xuất</h1>
            <p>Chạy profile kỹ thuật, xem thứ hạng và kiểm tra nguồn dữ liệu của từng phương án.</p>
          </div>

          <form className="planner-form" onSubmit={(event) => void runScenario(event)}>
            <div className="planner-form-section">
              <div className="planner-section-heading"><span>01</span><h2>Phạm vi và dữ liệu</h2></div>
              <label>
                Mã khu vực
                <input value={cityId} onChange={(event) => setCityId(event.target.value)} required />
              </label>
              <div className="planner-field-pair">
                <label>
                  Phiên bản boundary
                  <input value={boundaryVersion} onChange={(event) => setBoundaryVersion(event.target.value)} required placeholder="Mã do M1 cung cấp" />
                </label>
                <label>
                  Pilot extent ID
                  <input value={pilotExtentId} onChange={(event) => setPilotExtentId(event.target.value)} required placeholder="Mã pilot do M1 cung cấp" />
                </label>
              </div>
              <label>
                Data snapshot ID
                <input value={snapshotId} onChange={(event) => setSnapshotId(event.target.value)} required placeholder="Snapshot đã version hóa" />
              </label>
              <label>
                Candidate ID <span className="planner-label-note">(phân cách bằng dấu phẩy hoặc dòng mới)</span>
                <textarea value={candidateIdsText} onChange={(event) => setCandidateIdsText(event.target.value)} rows={2} placeholder="ID từ tập candidate của M1" />
              </label>
            </div>

            <div className="planner-form-section">
              <div className="planner-section-heading"><span>02</span><h2>Kịch bản kỹ thuật</h2></div>
              <div className="planner-profile-row">
                <span>Profile</span><strong>Technical opportunity</strong>
              </div>
              <label>
                Thời điểm đánh giá
                <input type="datetime-local" value={asOf} onChange={(event) => setAsOf(event.target.value)} required />
              </label>
              <div className="planner-field-pair">
                <label>Horizon (năm)<input type="number" min={1} value={horizonYears} onChange={(event) => setHorizonYears(Number(event.target.value))} required /></label>
                <label>Seed<input type="number" value={seed} onChange={(event) => setSeed(Number(event.target.value))} required /></label>
              </div>
              <label>
                Config version <span className="planner-label-note">(để trống dùng mặc định server)</span>
                <input value={configVersion} onChange={(event) => setConfigVersion(event.target.value)} placeholder="Tùy chọn" />
              </label>
              <div className="planner-field-pair">
                <label>Ngưỡng tiếp cận (phút)<input type="number" min={1} value={coverageMinutes} onChange={(event) => setCoverageMinutes(Number(event.target.value))} required /></label>
                <label>Ngân sách (VND)<input type="number" min={0} value={budgetVnd} onChange={(event) => setBudgetVnd(event.target.value)} placeholder="Chưa đặt" /></label>
              </div>
              <div className="planner-field-pair">
                <label>Loại sạc<select value={chargerType} onChange={(event) => setChargerType(event.target.value as "AC" | "DC")}><option value="DC">DC</option><option value="AC">AC</option></select></label>
                <label>Số cổng<input type="number" min={1} value={portCount} onChange={(event) => setPortCount(Number(event.target.value))} required /></label>
              </div>
              <label>Công suất mỗi cổng (kW)<input type="number" min={0.1} step={0.1} value={powerKw} onChange={(event) => setPowerKw(Number(event.target.value))} required /></label>
              <p className="planner-illustrative-note">Các thông số ban đầu chỉ là giá trị minh họa để chỉnh sửa, không phải tiêu chuẩn kỹ thuật hay khuyến nghị thị trường.</p>
            </div>

            <div className="planner-package-note">
              Profile policy và investor chưa bật vì chưa có package/adapter đã xác thực. Chi phí sẽ là “chưa có dữ liệu” khi chưa có nguồn phù hợp.
            </div>
            <button className="planner-run-button" type="submit" disabled={busy}>
              {busy ? "Đang chạy…" : "Chạy scenario"}
            </button>
          </form>
        </section>

        <section className="map-column planner-results-column">
          <div className="planner-results-header">
            <div><span className="planner-eyebrow">Kết quả và bản đồ</span><h2>Candidate ranking</h2></div>
            {response && <span className={`planner-run-status ${response.status}`}>{runStatusLabel(response.status)}</span>}
          </div>

          {requestError && <div className="planner-alert error" role="alert">{requestError}</div>}
          {response && (
            <>
              <div className="planner-run-meta">
                <span>Run <b>{response.run_id}</b></span>
                <span>Snapshot <b>{response.scenario.data_snapshot_id}</b></span>
                <span>Algorithm <b>{response.scenario.algorithm_version ?? "Chưa có"}</b></span>
                <span>Config <b>{response.scenario.config_version ?? "Chưa có"}</b></span>
              </div>
              {response.warnings.length > 0 && (
                <div className="planner-warnings" role="status">
                  <strong>Giới hạn của run</strong>
                  {response.warnings.map((warning, index) => <p key={`${index}-${warning}`}>{warning}</p>)}
                </div>
              )}
            </>
          )}

          <div className="planner-map-area">
            <PlannerMap
              recommendations={response?.recommendations ?? []}
              stationCatalog={stationCatalog}
              selectedCandidateId={selectedCandidateId}
              onSelect={setSelectedCandidateId}
            />
            <div className="planner-boundary-note">
              Pilot boundary và polygon coverage cần geometry đã version hóa từ M1.{stationCatalogError ? ` Danh mục trạm chưa tải được: ${stationCatalogError}` : ""}
            </div>
          </div>

          {response && response.recommendations.length > 0 && (
            <div className="planner-candidate-results">
              <div className="planner-results-subheading"><h3>Phương án được xếp hạng</h3><span>{response.recommendations.length} candidate</span></div>
              <div className="planner-candidate-list">
                {response.recommendations.map((item) => (
                  <CandidateCard
                    key={item.candidate_id}
                    item={item}
                    selected={item.candidate_id === selectedCandidateId}
                    compared={comparisonIds.includes(item.candidate_id)}
                    compareDisabled={comparisonIds.length >= 2 && !comparisonIds.includes(item.candidate_id)}
                    onSelect={() => setSelectedCandidateId(item.candidate_id)}
                    onCompare={() => toggleComparison(item.candidate_id)}
                  />
                ))}
              </div>
              {comparisonIds.length === 1 && <p className="planner-comparison-hint">Chọn thêm một candidate để xem chênh lệch giữa hai phương án.</p>}
              {comparisonItems && <ComparisonTable items={comparisonItems} />}
              {selectedCandidate && <CandidateExplanation item={selectedCandidate} />}
            </div>
          )}

          {response && response.recommendations.length === 0 && (
            <div className="planner-empty-state">
              <strong>{response.status === "no_feasible_candidates" ? "Không có candidate khả thi" : "Chưa có kết quả để xếp hạng"}</strong>
              <p>Không có điểm số hoặc vị trí nào được tự tạo khi repository chưa xác nhận dữ liệu đầu vào.</p>
            </div>
          )}

          {response && (response.unranked_candidates.length > 0 || response.excluded_candidates.length > 0) && (
            <div className="planner-other-candidates">
              {response.unranked_candidates.length > 0 && (
                <details open>
                  <summary>Chưa đủ bằng chứng để xếp hạng · {response.unranked_candidates.length}</summary>
                  {response.unranked_candidates.map((candidate) => <p key={candidate.candidate_id}><b>{candidate.candidate_id}</b> — {candidate.reason}</p>)}
                </details>
              )}
              {response.excluded_candidates.length > 0 && (
                <details open>
                  <summary>Bị loại do hard constraint · {response.excluded_candidates.length}</summary>
                  {response.excluded_candidates.map((candidate) => <p key={candidate.candidate_id}><b>{candidate.candidate_id}</b> — {candidate.constraints.map((constraint) => constraint.reason).join("; ")}</p>)}
                </details>
              )}
            </div>
          )}

          {!response && !requestError && !busy && (
            <div className="planner-empty-state initial">
              <strong>Chưa chạy scenario</strong>
              <p>Nhập boundary, snapshot và candidate ID do M1 cung cấp để gửi request tới API planning.</p>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
