import { useState } from "react";

import type { DemoScenario, GeoPoint, Vehicle } from "../types";
import LocationInput from "./LocationInput";

interface JourneyFormProps {
  scenarios: DemoScenario[];
  vehicles: Vehicle[];
  scenario: DemoScenario;
  vehicleId: string;
  initialSoc: number;
  targetSoc: number;
  applyEvents: boolean;
  origin: GeoPoint;
  destination: GeoPoint;
  locationsValid: boolean;
  submitting: boolean;
  onScenarioChange: (scenarioId: string) => void;
  onVehicleChange: (vehicleId: string) => void;
  onInitialSocChange: (soc: number) => void;
  onTargetSocChange: (soc: number) => void;
  onApplyEventsChange: (enabled: boolean) => void;
  onOriginChange: (point: GeoPoint) => void;
  onDestinationChange: (point: GeoPoint) => void;
  onOriginValidityChange: (valid: boolean) => void;
  onDestinationValidityChange: (valid: boolean) => void;
  onSubmit: () => void;
  onReset: () => void;
}

export default function JourneyForm(props: JourneyFormProps) {
  const [showAdvanced, setShowAdvanced] = useState(false);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    props.onSubmit();
  };

  return (
    <form className="journey-form" onSubmit={submit}>
      <div className="section-heading">
        <div>
          <span className="step-label">01 · Hành trình</span>
          <h1>Chọn trạm sạc</h1>
        </div>
      </div>

      <div className="journey-fields">
        <LocationInput
          key={`origin-${props.origin.lat}-${props.origin.lon}`}
          label="Điểm đi"
          point={props.origin}
          disabled={props.submitting}
          onSelect={props.onOriginChange}
          onValidityChange={props.onOriginValidityChange}
        />

        <LocationInput
          key={`destination-${props.destination.lat}-${props.destination.lon}`}
          label="Điểm đến"
          point={props.destination}
          disabled={props.submitting}
          onSelect={props.onDestinationChange}
          onValidityChange={props.onDestinationValidityChange}
        />

        <label>
          Xe điện
          <select
            value={props.vehicleId}
            disabled={props.submitting}
            onChange={(event) => props.onVehicleChange(event.target.value)}
          >
            {props.vehicles.map((vehicle) => (
              <option key={vehicle.vehicle_id} value={vehicle.vehicle_id}>
                {vehicle.make} {vehicle.model} {vehicle.variant ?? ""}
              </option>
            ))}
          </select>
        </label>

        <label>
          Pin hiện tại
          <div className="soc-input">
            <input
              type="range"
              min="1"
              max="100"
              value={Math.round(props.initialSoc * 100)}
              disabled={props.submitting}
              onChange={(event) =>
                props.onInitialSocChange(Number(event.target.value) / 100)
              }
            />
            <strong>{Math.round(props.initialSoc * 100)}%</strong>
          </div>
        </label>
      </div>

      <div className="form-actions">
        <button
          className="primary-button"
          type="submit"
          disabled={props.submitting || !props.locationsValid}
        >
          {props.submitting ? "Đang tìm trạm…" : "Tìm trạm tốt nhất"}
        </button>
      </div>

      <button
        className="advanced-toggle"
        type="button"
        aria-expanded={showAdvanced}
        onClick={() => setShowAdvanced((current) => !current)}
      >
        <span>⚙ Tùy chọn nâng cao</span>
      </button>

      {showAdvanced && (
        <div className="advanced-options">
          <label>
            Kịch bản
            <select
              value={props.scenario.scenario_id}
              disabled={props.submitting}
              onChange={(event) =>
                props.onScenarioChange(event.target.value)
              }
            >
              {props.scenarios.map((scenario) => (
                <option
                  key={scenario.scenario_id}
                  value={scenario.scenario_id}
                >
                  {scenario.name}
                </option>
              ))}
            </select>
          </label>

          <label>
            SOC mục tiêu
            <div className="soc-input">
              <input
                type="range"
                min="1"
                max="100"
                value={Math.round(props.targetSoc * 100)}
                disabled={props.submitting}
                onChange={(event) =>
                  props.onTargetSocChange(
                    Number(event.target.value) / 100,
                  )
                }
              />
              <strong>{Math.round(props.targetSoc * 100)}%</strong>
            </div>
          </label>

          <label className="event-toggle">
            <input
              type="checkbox"
              checked={props.applyEvents}
              disabled={
                props.submitting ||
                props.scenario.event_ids.length === 0
              }
              onChange={(event) =>
                props.onApplyEventsChange(event.target.checked)
              }
            />

            <span>
              Áp dụng event của kịch bản
              <small>
                {props.scenario.event_ids.length
                  ? props.scenario.event_ids.join(", ")
                  : "Không có event"}
              </small>
            </span>
          </label>

          <button
            className="secondary-button"
            type="button"
            disabled={props.submitting}
            onClick={props.onReset}
          >
            Reset demo
          </button>
        </div>
      )}
    </form>
  );
}

