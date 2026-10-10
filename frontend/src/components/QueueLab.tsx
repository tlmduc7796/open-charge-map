import { useCallback, useEffect, useState } from "react";

import { api } from "../api";
import type {
  QueueLabPort,
  QueueLabRequest,
  QueueLabResult,
  QueueLabVehicle,
  SyntheticDuration,
} from "../types";

const fixed = (value_min: number): SyntheticDuration => ({ kind: "fixed", value_min });

function connectorText(connectors: string[]) {
  return connectors.join(", ");
}

function parseConnectors(value: string) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function displayTime(value: string) {
  return new Intl.DateTimeFormat("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
    day: "2-digit",
    month: "2-digit",
  }).format(new Date(value));
}

function DurationFields({
  duration,
  onChange,
}: {
  duration: SyntheticDuration;
  onChange: (duration: SyntheticDuration) => void;
}) {
  const updateNumber = (field: "value_min" | "min_min" | "max_min", value: string) => {
    const number = Number(value);
    onChange({ ...duration, [field]: Number.isFinite(number) ? number : undefined });
  };

  return (
    <div className="queue-duration">
      <select
        aria-label="Loại duration"
        value={duration.kind}
        onChange={(event) =>
          onChange(event.target.value === "uniform" ? { kind: "uniform", min_min: 5, max_min: 15 } : fixed(10))
        }
      >
        <option value="fixed">Cố định</option>
        <option value="uniform">Uniform</option>
      </select>
      {duration.kind === "fixed" ? (
        <input
          aria-label="Duration phút"
          type="number"
          min="0.1"
          step="0.1"
          value={duration.value_min ?? ""}
          onChange={(event) => updateNumber("value_min", event.target.value)}
        />
      ) : (
        <>
          <input
            aria-label="Duration nhỏ nhất phút"
            type="number"
            min="0.1"
            step="0.1"
            value={duration.min_min ?? ""}
            onChange={(event) => updateNumber("min_min", event.target.value)}
          />
          <input
            aria-label="Duration lớn nhất phút"
            type="number"
            min="0.1"
            step="0.1"
            value={duration.max_min ?? ""}
            onChange={(event) => updateNumber("max_min", event.target.value)}
          />
        </>
      )}
      <span>phút</span>
    </div>
  );
}

export default function QueueLab() {
  const [isExpanded, setIsExpanded] = useState(true);
  const [request, setRequest] = useState<QueueLabRequest | null>(null);
  const [result, setResult] = useState<QueueLabResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [simulating, setSimulating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadScenario = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const scenario = await api.queueLabScenario();
      setRequest(scenario);
      setResult(await api.simulateQueueLab(scenario));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Không tải được Queue Lab.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadScenario(), 0);
    return () => window.clearTimeout(timer);
  }, [loadScenario]);

  const setPort = (index: number, update: Partial<QueueLabPort>) => {
    if (!request) return;
    const ports = request.ports.map((port, itemIndex) =>
      itemIndex === index ? { ...port, ...update } : port,
    );
    setRequest({ ...request, ports });
  };

  const setVehicle = (index: number, update: Partial<QueueLabVehicle>) => {
    if (!request) return;
    const confirmed_queue = request.confirmed_queue.map((vehicle, itemIndex) =>
      itemIndex === index ? { ...vehicle, ...update } : vehicle,
    );
    setRequest({ ...request, confirmed_queue });
  };

  const simulate = async () => {
    if (!request) return;
    setSimulating(true);
    setError(null);
    try {
      setResult(await api.simulateQueueLab(request));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Simulation không chạy được.");
    } finally {
      setSimulating(false);
    }
  };

  if (loading || !request) {
    return <section className="queue-lab-shell"><p>Đang tải Queue Lab…</p></section>;
  }

  return (
    <section className="queue-lab-shell" id="queue-lab">
      <div className="queue-lab-heading">
        <button
          className="queue-lab-heading-toggle"
          type="button"
          aria-expanded={isExpanded}
          aria-controls="queue-lab-content"
          onClick={() => setIsExpanded((expanded) => !expanded)}
        >
          <span>
            <span className="step-label">04 · Queue Lab</span>
            <span className="queue-lab-title" role="heading" aria-level={2}>DES chờ sạc theo từng port</span>
            <span className="queue-lab-description">Duration là input mô phỏng; chưa dùng telemetry hoặc ML session thật.</span>
          </span>
          <span className="queue-lab-chevron" aria-hidden="true">{isExpanded ? "⌃" : "⌄"}</span>
        </button>
      </div>

      <div id="queue-lab-content" hidden={!isExpanded}>
      <div className="queue-lab-content-actions">
        <button className="secondary-button" onClick={() => void loadScenario()}>
          Nạp scenario 28 phút
        </button>
      </div>
      {error && <p className="queue-error" role="alert">{error}</p>}

      <div className="queue-lab-grid">
        <div className="queue-lab-panel">
          <div className="queue-panel-title">
            <h3>Ports</h3>
            <button
              className="text-button"
              onClick={() =>
                setRequest({
                  ...request,
                  ports: [
                    ...request.ports,
                    {
                      port_id: `PORT_${request.ports.length + 1}`,
                      connector_types: ["CCS2"],
                      state: "available",
                      remaining_port_release: null,
                    },
                  ],
                })
              }
            >
              + Thêm port
            </button>
          </div>
          {request.ports.map((port, index) => (
            <div className="queue-row" key={`${port.port_id}-${index}`}>
              <input
                aria-label="Mã port"
                value={port.port_id}
                onChange={(event) => setPort(index, { port_id: event.target.value })}
                placeholder="Port"
              />
              <input
                aria-label="Connector port"
                value={connectorText(port.connector_types)}
                onChange={(event) => setPort(index, { connector_types: parseConnectors(event.target.value) })}
                placeholder="CCS2, Type 2"
              />
              <select
                aria-label="Trạng thái port"
                value={port.state}
                onChange={(event) => {
                  const state = event.target.value as QueueLabPort["state"];
                  setPort(index, {
                    state,
                    remaining_port_release: state === "charging" ? port.remaining_port_release ?? fixed(10) : null,
                  });
                }}
              >
                <option value="available">Available</option>
                <option value="charging">Charging</option>
                <option value="offline">Offline</option>
              </select>
              {port.state === "charging" && port.remaining_port_release ? (
                <DurationFields
                  duration={port.remaining_port_release}
                  onChange={(remaining_port_release) => setPort(index, { remaining_port_release })}
                />
              ) : <span className="queue-empty-cell">—</span>}
              <button
                className="remove-button"
                aria-label={`Xóa ${port.port_id}`}
                disabled={request.ports.length === 1}
                onClick={() => setRequest({ ...request, ports: request.ports.filter((_, itemIndex) => itemIndex !== index) })}
              >
                ×
              </button>
            </div>
          ))}
        </div>

        <div className="queue-lab-panel">
          <div className="queue-panel-title">
            <h3>Confirmed queue</h3>
            <button
              className="text-button"
              onClick={() =>
                setRequest({
                  ...request,
                  confirmed_queue: [
                    ...request.confirmed_queue,
                    {
                      vehicle_id: `QUEUE_${request.confirmed_queue.length + 1}`,
                      queue_position: request.confirmed_queue.length + 1,
                      connector_types: ["CCS2"],
                      charging_duration: fixed(20),
                    },
                  ],
                })
              }
            >
              + Thêm xe
            </button>
          </div>
          {request.confirmed_queue.map((vehicle, index) => (
            <div className="queue-row queue-vehicle-row" key={`${vehicle.vehicle_id}-${index}`}>
              <input
                aria-label="Vị trí queue"
                type="number"
                min="1"
                value={vehicle.queue_position}
                onChange={(event) => setVehicle(index, { queue_position: Number(event.target.value) })}
              />
              <input
                aria-label="Mã xe queue"
                value={vehicle.vehicle_id}
                onChange={(event) => setVehicle(index, { vehicle_id: event.target.value })}
              />
              <input
                aria-label="Connector xe queue"
                value={connectorText(vehicle.connector_types)}
                onChange={(event) => setVehicle(index, { connector_types: parseConnectors(event.target.value) })}
              />
              <DurationFields
                duration={vehicle.charging_duration}
                onChange={(charging_duration) => setVehicle(index, { charging_duration })}
              />
              <button
                className="remove-button"
                aria-label={`Xóa ${vehicle.vehicle_id}`}
                onClick={() => setRequest({ ...request, confirmed_queue: request.confirmed_queue.filter((_, itemIndex) => itemIndex !== index) })}
              >
                ×
              </button>
            </div>
          ))}
          {!request.confirmed_queue.length && <p className="queue-hint">Chưa có xe đã xác nhận trong queue.</p>}
        </div>
      </div>

      <div className="queue-requester">
        <label>Connector xe demo
          <input
            value={connectorText(request.requester_connector_types)}
            onChange={(event) => setRequest({ ...request, requester_connector_types: parseConnectors(event.target.value) })}
          />
        </label>
        <label>Charging duration xe demo
          <DurationFields
            duration={request.requester_charge_duration}
            onChange={(requester_charge_duration) => setRequest({ ...request, requester_charge_duration })}
          />
        </label>
        <label>Monte Carlo trials
          <input
            type="number"
            min="1"
            max="10000"
            value={request.trials}
            onChange={(event) => setRequest({ ...request, trials: Number(event.target.value) })}
          />
        </label>
        <label>Seed
          <input
            type="number"
            min="0"
            value={request.seed}
            onChange={(event) => setRequest({ ...request, seed: Number(event.target.value) })}
          />
        </label>
        <label>Ngưỡng chờ (phút)
          <input
            type="number"
            min="0"
            value={request.wait_threshold_min}
            onChange={(event) => setRequest({ ...request, wait_threshold_min: Number(event.target.value) })}
          />
        </label>
        <button className="primary-button" disabled={simulating} onClick={() => void simulate()}>
          {simulating ? "Đang mô phỏng…" : "Simulate"}
        </button>
      </div>

      {result && <QueueResults result={result} />}
      </div>
    </section>
  );
}

function QueueResults({ result }: { result: QueueLabResult }) {
  const monteCarlo = result.monte_carlo;
  return (
    <div className="queue-results">
      <div className="queue-result-card primary-result">
        <span>Giờ bắt đầu trong mẫu có seed</span>
        <strong>{result.estimated_start_at ? displayTime(result.estimated_start_at) : "Không có port tương thích"}</strong>
        <small>Thời gian chờ trong mẫu này: {result.estimated_wait_min ?? "—"} phút</small>
      </div>
      <div className="queue-result-card">
        <span>Monte Carlo · {monteCarlo.trials.toLocaleString("vi-VN")} lần</span>
        <strong>P10 / P50 / P90</strong>
        <small>{monteCarlo.p10_wait_min ?? "—"} / {monteCarlo.p50_wait_min ?? "—"} / {monteCarlo.p90_wait_min ?? "—"} phút</small>
      </div>
      <div className="queue-result-card">
        <span>Tail risk</span>
        <strong>P(wait &gt; {monteCarlo.wait_threshold_min} phút)</strong>
        <small>{monteCarlo.probability_wait_over_threshold === null ? "—" : `${(monteCarlo.probability_wait_over_threshold * 100).toFixed(1)}%`}</small>
      </div>

      <div className="queue-timeline">
        <h3>Timeline port allocation</h3>
        {result.timeline.map((entry) => (
          <div className={`timeline-entry ${entry.kind}`} key={`${entry.port_id}-${entry.vehicle_id}-${entry.start_at}`}>
            <b>{entry.port_id}</b>
            <span>{entry.vehicle_id}</span>
            <time>{displayTime(entry.start_at)} → {displayTime(entry.end_at)}</time>
          </div>
        ))}
      </div>
      <div className="queue-caveats">
        <strong>Caveats</strong>
        {result.caveats.map((caveat) => <span key={caveat}>{caveat.replaceAll("_", " ")}</span>)}
      </div>
    </div>
  );
}
