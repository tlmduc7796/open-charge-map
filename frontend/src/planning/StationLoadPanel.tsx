import { LOAD_STYLES, type LoadSimulation } from "./stationLoad";

export default function StationLoadPanel({ simulation, showBaseline, onBaselineChange }: {
  simulation: LoadSimulation;
  showBaseline: boolean;
  onBaselineChange: (value: boolean) => void;
}) {
  const hasProposal = simulation.addedIds.length > 0;
  const before = simulation.baseline.existingOverloaded;
  const after = simulation.proposed.existingOverloaded;
  const current = hasProposal && !showBaseline ? simulation.proposed : simulation.baseline;
  const time = new Intl.DateTimeFormat("vi-VN", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Ho_Chi_Minh" }).format(new Date(simulation.intervalStart));
  return <section className="planner-load-panel" aria-label="Mô phỏng tải trạm">
    <div className="planner-load-heading">
      <strong>Tải trạm hiện hữu <small>· Mô phỏng cao điểm {time}</small></strong>
      <div className="planner-load-modes" role="group" aria-label="So sánh tải trạm">
        <button type="button" aria-pressed={!hasProposal || showBaseline} onClick={() => onBaselineChange(true)}>Trước bổ sung</button>
        <button type="button" aria-pressed={hasProposal && !showBaseline} disabled={!hasProposal}
          onClick={() => onBaselineChange(false)}>Sau bổ sung{hasProposal ? ` (${simulation.addedIds.length} trạm)` : ""}</button>
      </div>
    </div>
    <div className="planner-load-legend" aria-label="Chú giải mức tải trạm">
      {(["normal", "busy", "overloaded", "severe"] as const).map((level, index) => <span key={level}>
        <i style={{ background: LOAD_STYLES[level].color }} />
        {LOAD_STYLES[level].label} <b>{[`≤ ${simulation.inputs.comfortable_utilization * 100}%`, "≤ 100%", "≤ 125%", "> 125%"][index]}</b>
      </span>)}
    </div>
    <p><b>{current.existingOverloaded}</b> trạm hiện hữu quá tải
      {hasProposal && <span> · Chuyển tải sang trạm mới cùng phường</span>}
      {hasProposal && <span> · Trước → sau: <b>{before} → {after}</b></span>}
      {hasProposal && <span> · Nhu cầu vượt công suất toàn mạng: <b>{simulation.baseline.totalExcess.toLocaleString("vi-VN", { maximumFractionDigits: 1 })} → {simulation.proposed.totalExcess.toLocaleString("vi-VN", { maximumFractionDigits: 1 })}</b> lượt/{simulation.inputs.interval_minutes} phút</span>}
    </p>
  </section>;
}
