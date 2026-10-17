import { useEffect, useMemo, useState } from "react";

import { api } from "../../api";
import AppModeSwitch, { type AppMode } from "../AppModeSwitch";
import GapMap from "./GapMap";
import {
  CANDIDATE_LIMIT, DIVISION_LABELS, EXCLUDED_LABELS, GAP_LAYERS, candidatesToCsv, formatDistance,
  formatNumber, formatPower, relationshipLabel, siteTypeLabel, stabilityLabel, stationColorOf,
  type GapLayer,
} from "./gapFormat";
import type {
  GapCandidate, GapCellResult, GapDivision, GapExcludedReason, GapParams, GapRunResponse,
  GapSnapshotResponse,
} from "./gapTypes";
import "../planner.css";
import "./gap.css";

interface GapViewProps {
  onModeChange: (mode: AppMode) => void;
}

function downloadCsv(candidates: GapCandidate[]) {
  const blob = new Blob([candidatesToCsv(candidates)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "ung-vien-khao-sat.csv";
  link.click();
  URL.revokeObjectURL(url);
}

function candidateTitle(candidate: GapCandidate): string {
  return candidate.road_names?.length
    ? `${candidate.road_names.join(", ")} · ${candidate.unit_name}`
    : `${candidate.unit_name} · ${candidate.cell_id}`;
}

function CandidateCard({ candidate, selected, onToggle }: { candidate: GapCandidate; selected: boolean; onToggle: () => void }) {
  const competitor = candidate.nearest_competitor;
  return (
    <button type="button" className={`gap-candidate${selected ? " selected" : ""}`} aria-pressed={selected} onClick={onToggle}>
      <span className="planner-rank">{candidate.selection_order}</span>
      <span className="gap-candidate-main">
        <strong>{candidateTitle(candidate)}</strong>
        <span className="planner-card-metrics">
          <span>Điểm lưu lượng <b>{formatNumber(candidate.flow_norm * 100, 0)}</b><small>{formatNumber(candidate.flow_vph, 0)} xe/giờ</small></span>
          <span>Giá thuê <b>{formatNumber(candidate.rent_kvnd_m2_month, 0)}</b><small>nghìn đ/m²/tháng</small></span>
          <span>Đối thủ gần nhất <b>{formatDistance(competitor?.distance_m)}</b><small>{competitor ? competitor.station_id : "không có"}</small></span>
        </span>
        <span className="gap-candidate-chips">
          {candidate.own_overlap && <span className="gap-chip warn">Gần trạm của mình</span>}
          {candidate.subdivided && <span className="gap-chip unknown">Chia nhỏ từ vùng trống</span>}
          {candidate.stability_label && <span className={`gap-chip ${candidate.stability_label}`}>{stabilityLabel(candidate)}</span>}
          <span className="gap-chip unknown">Pháp lý chưa xác minh</span>
        </span>
      </span>
    </button>
  );
}

function roadSummary(candidate: GapCandidate): string {
  const parts = [candidate.road_type,
    candidate.lanes ? `${candidate.lanes} làn` : null,
    candidate.road_length_m ? `${formatNumber(candidate.road_length_m, 0)} m đường bao quanh` : null];
  return parts.filter(Boolean).join(" · ");
}

function NearbyContext({ candidate }: { candidate: GapCandidate }) {
  const { nearby } = candidate;
  const radius = formatDistance(nearby.radius_m);
  const rentRange = nearby.rent_min_kvnd === null || nearby.rent_max_kvnd === null
    ? "—"
    : `${formatNumber(nearby.rent_min_kvnd, 0)} – ${formatNumber(nearby.rent_max_kvnd, 0)} nghìn`;
  return (
    <>
      <h4>Lưu lượng và giá bất động sản xung quanh (bán kính {radius}, {nearby.cell_count} {DIVISION_LABELS[candidate.road_names ? "route" : "grid"].units})</h4>
      <div className="gap-nearby-grid">
        <section aria-label="Lưu lượng quanh ứng viên">
          <h5>Lưu lượng tuyến đường <em>mô phỏng</em></h5>
          <dl className="gap-facts">
            <dt>Tại khối này</dt>
            <dd>{formatNumber(candidate.flow_vph, 0)} xe/giờ cao điểm · cao hơn {formatNumber(nearby.flow_percentile, 0)}% khối trong 9 phường</dd>
            <dt>Trung bình quanh</dt><dd>{formatNumber(nearby.flow_mean_vph, 0)} xe/giờ</dd>
            <dt>Cao nhất quanh</dt>
            <dd>{formatNumber(nearby.flow_max_vph, 0)} xe/giờ{nearby.flow_max_roads?.length ? ` · ${nearby.flow_max_roads.join(", ")}` : ""}</dd>
          </dl>
        </section>
        <section aria-label="Giá bất động sản quanh ứng viên">
          <h5>Giá nhà (giá thuê) <em>mô phỏng</em></h5>
          <dl className="gap-facts">
            <dt>Tại khối này</dt>
            <dd>{candidate.rent_kvnd_m2_month === null ? "—" : `${formatNumber(candidate.rent_kvnd_m2_month, 0)} nghìn đ/m²/tháng`}
              {nearby.rent_percentile !== null && ` · đắt hơn ${formatNumber(nearby.rent_percentile, 0)}% khối trong 9 phường`}</dd>
            <dt>Trung bình quanh</dt><dd>{nearby.rent_mean_kvnd === null ? "—" : `${formatNumber(nearby.rent_mean_kvnd, 0)} nghìn đ/m²/tháng`}</dd>
            <dt>Khoảng giá quanh</dt><dd>{rentRange}</dd>
          </dl>
        </section>
      </div>
    </>
  );
}

function CandidateDetail({ candidate, onClose }: { candidate: GapCandidate; onClose: () => void }) {
  return (
    <section className="gap-detail" aria-label={`Chi tiết ứng viên ${candidate.cell_id}`}>
      <header>
        <div>
          <span className="planner-eyebrow">Ứng viên #{candidate.selection_order} · ô {candidate.cell_id}</span>
          <h3>{candidate.road_names?.length ? candidate.road_names.join(", ") : candidate.unit_name}</h3>
          {candidate.road_names?.length ? <small className="planner-muted">{candidate.unit_name}</small> : null}
        </div>
        <button type="button" className="planner-secondary-button" onClick={onClose}>Đóng</button>
      </header>
      <div className="gap-detail-grid">
        <div><small>Nhu cầu D</small><b>{formatNumber(candidate.demand, 2)}</b><span>Flow {formatNumber(candidate.flow_norm, 2)} · POI {formatNumber(candidate.poi_norm, 2)}</span></div>
        <div><small>Nguồn cung quanh ô</small><b>{formatNumber(candidate.supply, 2)}</b><span>của mình {formatNumber(candidate.supply_own, 2)} · đối thủ {formatNumber(candidate.supply_competitor, 2)}</span></div>
        <div><small>Gap = D / (1 + Cung)</small><b>{formatNumber(candidate.gap, 4)}</b><span>Điểm sau giá thuê {formatNumber(candidate.score, 4)}</span></div>
        <div><small>Giá thuê tham khảo</small><b>{candidate.rent_kvnd_m2_month === null ? "—" : `${formatNumber(candidate.rent_kvnd_m2_month, 0)} nghìn`}</b><span>đồng/m²/tháng · mô phỏng</span></div>
      </div>
      <dl className="gap-facts">
        {candidate.road_names?.length ? <><dt>Giới hạn bởi</dt><dd>{candidate.road_names.join(", ")}{roadSummary(candidate) && ` · ${roadSummary(candidate)}`}</dd></> : null}
        <dt>Lưu lượng xe</dt><dd>{formatNumber(candidate.flow_vph, 0)} xe/giờ cao điểm <em>mô phỏng</em></dd>
        <dt>POI</dt><dd>{formatNumber(candidate.poi_count, 0)} điểm, trọng số {formatNumber(candidate.poi_weighted, 1)} <em>dữ liệu thu thập</em></dd>
        <dt>Trạm của mình gần nhất</dt>
        <dd>{candidate.nearest_own ? `${candidate.nearest_own.station_id} · ${formatDistance(candidate.nearest_own.distance_m)} · ${candidate.nearest_own.port_count} cổng, ${formatNumber(candidate.nearest_own.total_power_kw, 0)} kW` : "—"}
          {candidate.own_overlap && <span className="gap-chip warn">Có thể lấy khách của trạm cũ</span>}</dd>
        <dt>Trạm đối thủ gần nhất</dt>
        <dd>{candidate.nearest_competitor ? `${candidate.nearest_competitor.station_id} (${candidate.nearest_competitor.operator_name}) · ${formatDistance(candidate.nearest_competitor.distance_m)} · ${candidate.nearest_competitor.port_count} cổng, ${formatNumber(candidate.nearest_competitor.total_power_kw, 0)} kW` : "—"}</dd>
        {candidate.area_m2 ? <><dt>Diện tích</dt><dd>{formatNumber(candidate.area_m2 / 10000, 1)} ha{candidate.subdivided && <span className="gap-chip warn">Chia nhỏ từ vùng trống lớn, chưa có đường bao đủ</span>}</dd></> : null}
        <dt>Cụm</dt><dd>{candidate.cluster_size} {DIVISION_LABELS[candidate.road_names ? "route" : "grid"].units} liền kề được gộp</dd>
        <dt>Độ ổn định</dt><dd>{stabilityLabel(candidate)}{candidate.stability !== null && <small> khi đổi w₁ và λ</small>}</dd>
      </dl>
      <NearbyContext candidate={candidate} />
      <h4>Trạm đóng góp nhiều nhất vào Cung</h4>
      <table className="gap-table">
        <thead><tr><th>Trạm</th><th>Mạng</th><th>Cổng</th><th>Công suất</th><th>Cách</th><th>Đóng góp</th></tr></thead>
        <tbody>
          {candidate.top_supply_stations.map((station) => (
            <tr key={station.station_id}>
              <td>{station.station_id}</td><td>{station.operator_name}</td><td>{station.port_count}</td>
              <td>{formatNumber(station.total_power_kw, 0)} kW</td><td>{formatDistance(station.distance_m)}</td>
              <td>{formatNumber(station.contribution, 2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h4>Pháp lý: chưa xác minh</h4>
      <ul className="gap-checklist">
        {candidate.pending_legal_checks.map((check) => <li key={check}>{check}</li>)}
      </ul>
    </section>
  );
}

const STATION_KINDS = ["OWNED", "OTHER_NETWORK"] as const;

function kindTotals(stations: GapSnapshotResponse["stations"], relationship: string) {
  const own = stations.filter((station) => station.relationship === relationship);
  return {
    stations: own.length,
    ports: own.reduce((sum, station) => sum + station.port_count, 0),
    dc: own.reduce((sum, station) => sum + station.dc_port_count, 0),
    ac: own.reduce((sum, station) => sum + station.ac_port_count, 0),
    kw: own.reduce((sum, station) => sum + station.total_power_kw, 0),
    maxPort: own.reduce((max, station) => Math.max(max, station.max_port_power_kw), 0),
  };
}

function StationInventory({ snapshot }: { snapshot: GapSnapshotResponse }) {
  const summary = snapshot.station_summary;
  return (
    <section className="gap-inventory" aria-label="Danh sách trạm mô phỏng">
      <div className="planner-results-subheading">
        <h3>Trạm của mình và trạm đối thủ (mô phỏng)</h3>
        <span>{summary.stations} trạm · {summary.ports} cổng · {formatNumber(summary.total_power_kw / 1000, 2)} MW</span>
      </div>
      <table className="gap-table">
        <thead><tr><th>Loại trạm</th><th>Số trạm</th><th>Số cổng</th><th>DC</th><th>AC</th><th>Tổng công suất</th><th>Cổng mạnh nhất</th></tr></thead>
        <tbody>
          {STATION_KINDS.map((kind) => {
            const totals = kindTotals(snapshot.stations, kind);
            return (
              <tr key={kind}>
                <td><i className="gap-dot" style={{ background: stationColorOf(kind) }} />{relationshipLabel(kind)}</td>
                <td>{totals.stations}</td><td>{totals.ports}</td><td>{totals.dc}</td><td>{totals.ac}</td>
                <td>{formatNumber(totals.kw, 0)} kW</td><td>{formatNumber(totals.maxPort, 0)} kW</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <details>
        <summary>Chi tiết từng trạm ({snapshot.stations.length})</summary>
        <div className="gap-table-scroll">
          <table className="gap-table">
            <thead><tr><th>Mã</th><th>Loại trạm</th><th>Phường</th><th>Loại điểm</th><th>Cấu hình cổng</th><th>Số cổng</th><th>Tổng kW</th><th>Giờ mở cửa</th></tr></thead>
            <tbody>
              {snapshot.stations.map((station) => (
                <tr key={station.station_id}>
                  <td>{station.station_id}</td><td>{relationshipLabel(station.relationship)}</td><td>{station.unit_name}</td>
                  <td>{siteTypeLabel(station.site_type)}</td><td>{formatPower(station.port_groups)}</td>
                  <td>{station.port_count}</td><td>{formatNumber(station.total_power_kw, 1)}</td><td>{station.opening_hours}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}

export default function GapView({ onModeChange }: GapViewProps) {
  const [snapshot, setSnapshot] = useState<GapSnapshotResponse | null>(null);
  const [snapshotError, setSnapshotError] = useState<string | null>(null);
  const [result, setResult] = useState<GapRunResponse | null>(null);
  const [running, setRunning] = useState(true);
  const [runError, setRunError] = useState<string | null>(null);
  const [layer, setLayer] = useState<GapLayer>("score");
  const [showStations, setShowStations] = useState(true);
  const [selectedCellId, setSelectedCellId] = useState<string | null>(null);

  // The setup form is gone: the snapshot defaults (with the fixed candidate count) run once.
  useEffect(() => {
    const controller = new AbortController();
    api.gapSnapshot().then((loaded) => {
      if (controller.signal.aborted) return;
      setSnapshot(loaded);
      const params: GapParams = {
        ...loaded.defaults, division: loaded.defaults.division ?? loaded.division, top_n: CANDIDATE_LIMIT,
        with_sensitivity: true,
      };
      return api.gapRun(params, controller.signal).then((response) => {
        if (!controller.signal.aborted) setResult(response);
      }).catch((error: unknown) => {
        if (!controller.signal.aborted) setRunError(error instanceof Error ? error.message : "Không chạy được phân tích.");
      });
    }, (error: unknown) => {
      if (!controller.signal.aborted) setSnapshotError(error instanceof Error ? error.message : "Không tải được dữ liệu khoảng trống.");
    }).finally(() => {
      if (!controller.signal.aborted) setRunning(false);
    });
    return () => controller.abort();
  }, []);

  const division: GapDivision = snapshot?.division ?? "route";
  const results = useMemo(() => new Map<string, GapCellResult>((result?.cells ?? []).map((cell) => [cell.cell_id, cell])), [result]);
  const candidates = result?.candidates ?? [];
  const selected = candidates.find((candidate) => candidate.cell_id === selectedCellId) ?? null;
  const excluded = result ? Object.entries(result.summary.excluded_by_reason) : [];
  const toggle = (cellId: string) => setSelectedCellId((current) => (current === cellId ? null : cellId));

  return (
    <main className="app-shell planner-app-shell">
      <div className="workspace planner-workspace">
        <section className="control-column planner-control-column" aria-label="Ứng viên khảo sát">
          <AppModeSwitch active="gap" onChange={onModeChange} />
          <div className="planner-heading">
            <div><span className="planner-eyebrow">Planner · 9 phường</span><h1>Khoảng trống trạm sạc</h1></div>
          </div>
          <div className="gap-candidate-panel">
            <div className="planner-results-subheading">
              <h3>Ứng viên đi khảo sát</h3>
              <span>{running && candidates.length === 0 ? "Đang tính…" : `Top ${candidates.length}`}</span>
            </div>
            {(snapshotError || runError) && <div className="planner-alert error" role="alert">{snapshotError ?? runError}</div>}
            {running && !snapshot && !snapshotError && <p className="planner-muted">Đang tải dữ liệu…</p>}
            {result && candidates.length === 0 && (
              <div className="planner-empty-state"><strong>Không có ứng viên</strong><p>Không còn khối nào đủ điều kiện.</p></div>
            )}
            {candidates.length > 0 && (
              <ol className="gap-candidate-list">
                {candidates.map((candidate) => (
                  <li key={candidate.cell_id}>
                    <CandidateCard candidate={candidate} selected={candidate.cell_id === selectedCellId} onToggle={() => toggle(candidate.cell_id)} />
                  </li>
                ))}
              </ol>
            )}
          </div>
        </section>

        <section className="planner-results-column gap-results-column" aria-label="Bản đồ và kết quả khoảng trống">
          <div className="planner-results-header">
            <div><span className="planner-eyebrow">TP. Hồ Chí Minh · 9 phường · {snapshot ? DIVISION_LABELS[division].name.toLowerCase() : "—"}</span><h2>Bản đồ điểm khoảng trống</h2></div>
            <div className="planner-header-actions">
              {running && <span className="planner-run-status">Đang tính…</span>}
              <button type="button" className="planner-secondary-button" disabled={!candidates.length} onClick={() => downloadCsv(candidates)}>Tải CSV</button>
            </div>
          </div>
          {snapshot && (
            <ul className="gap-data-labels" aria-label="Nguồn dữ liệu">
              <li className="real">POI: dữ liệu thu thập</li>
              <li className="synthetic">Lưu lượng xe (khối và tuyến đường): mô phỏng</li>
              <li className="synthetic">Giá thuê: mô phỏng</li>
              <li className="synthetic">Trạm của mình và đối thủ: mô phỏng</li>
              <li className="unknown">Pháp lý: chưa xác minh</li>
            </ul>
          )}
          <div className="planner-map-area gap-map-area">
            <div className="planner-map-toolbar">
              <div className="gap-mode-switch" role="group" aria-label="Chế độ hiển thị">
                {GAP_LAYERS.map((item) => (
                  <button key={item.id} type="button" className={layer === item.id ? "active" : ""} aria-pressed={layer === item.id} title={item.hint} onClick={() => setLayer(item.id)}>
                    {item.label}
                  </button>
                ))}
              </div>
              <label className="gap-toggle"><input type="checkbox" checked={showStations} onChange={(event) => setShowStations(event.target.checked)} />Hiện trạm sạc</label>
              <div className="gap-operator-legend">
                {snapshot && STATION_KINDS.map((kind) => (
                  <span key={kind}><i className="gap-dot" style={{ background: stationColorOf(kind) }} />{relationshipLabel(kind)}</span>
                ))}
              </div>
            </div>
            {snapshot
              ? <GapMap cells={snapshot.cells} roads={snapshot.roads} results={results} layer={layer} stations={snapshot.stations} showStations={showStations}
                  candidates={candidates} selectedCandidateId={selectedCellId} onSelectCandidate={setSelectedCellId} />
              : <div className="gap-map-placeholder">{snapshotError ? "Không có dữ liệu bản đồ." : "Đang tải bản đồ…"}</div>}
          </div>

          {result && (
            <div className="gap-lower">
              <p className="gap-summary">
                {result.summary.eligible_cell_count}/{result.summary.cell_count} {DIVISION_LABELS[division].units} đủ điều kiện
                {excluded.map(([reason, count]) => ` · ${count} ${DIVISION_LABELS[division].units} bị loại: ${EXCLUDED_LABELS[reason as GapExcludedReason] ?? reason}`)}
                {result.summary.own_overlap_cell_count > 0 && ` · ${result.summary.own_overlap_cell_count} ${DIVISION_LABELS[division].units} gần trạm của mình`}
              </p>
              {result.warnings.length > 0 && <ul className="gap-warnings">{result.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>}
              {selected && <CandidateDetail candidate={selected} onClose={() => setSelectedCellId(null)} />}
            </div>
          )}
          {snapshot && <StationInventory snapshot={snapshot} />}
        </section>
      </div>
    </main>
  );
}
