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
  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    props.onSubmit();
  };

  return (
    <form className="journey-form" onSubmit={submit}>
      <div className="section-heading">
        <div>
          <span className="step-label">01 · Hành trình</span>
          <h1>Chọn trạm sạc phù hợp</h1>
        </div>
        <span className="demo-pill">Demo backend-first</span>
      </div>

      <label>
        Kịch bản
        <select
          value={props.scenario.scenario_id}
          onChange={(event) => props.onScenarioChange(event.target.value)}
        >
          {props.scenarios.map((scenario) => (
            <option key={scenario.scenario_id} value={scenario.scenario_id}>
              {scenario.name}
            </option>
          ))}
        </select>
      </label>

      <div className="route-inputs">
        <LocationInput
          key={`origin-${props.origin.lat}-${props.origin.lon}`}
          label="Điểm đi"
          point={props.origin}
          disabled={props.submitting}
          onSelect={props.onOriginChange}
          onValidityChange={props.onOriginValidityChange}
        />
        <span className="route-arrow" aria-hidden="true">→</span>
        <LocationInput
          key={`destination-${props.destination.lat}-${props.destination.lon}`}
          label="Điểm đến"
          point={props.destination}
          disabled={props.submitting}
          onSelect={props.onDestinationChange}
          onValidityChange={props.onDestinationValidityChange}
        />
      </div>
      <p className="field-note">Chọn gợi ý Goong để đổi địa điểm; điểm scenario vẫn dùng route cache khi API lỗi.</p>

      <label>
        Xe điện
        <select value={props.vehicleId} onChange={(event) => props.onVehicleChange(event.target.value)}>
          {props.vehicles.map((vehicle) => (
            <option key={vehicle.vehicle_id} value={vehicle.vehicle_id}>
              {vehicle.make} {vehicle.model} {vehicle.variant ?? ""}
            </option>
          ))}
        </select>
      </label>

      <div className="soc-grid">
        <label>
          SOC hiện tại
          <div className="soc-input">
            <input
              type="range"
              min="1"
              max="100"
              value={Math.round(props.initialSoc * 100)}
              onChange={(event) => props.onInitialSocChange(Number(event.target.value) / 100)}
            />
            <strong>{Math.round(props.initialSoc * 100)}%</strong>
          </div>
        </label>
        <label>
          SOC mục tiêu
          <div className="soc-input">
            <input
              type="range"
              min="1"
              max="100"
              value={Math.round(props.targetSoc * 100)}
              onChange={(event) => props.onTargetSocChange(Number(event.target.value) / 100)}
            />
            <strong>{Math.round(props.targetSoc * 100)}%</strong>
          </div>
        </label>
      </div>

      <label className="event-toggle">
        <input
          type="checkbox"
          checked={props.applyEvents}
          disabled={props.scenario.event_ids.length === 0}
          onChange={(event) => props.onApplyEventsChange(event.target.checked)}
        />
        <span>
          Áp dụng event của kịch bản
          <small>{props.scenario.event_ids.length ? props.scenario.event_ids.join(", ") : "Không có event"}</small>
        </span>
      </label>

      <div className="form-actions">
        <button className="primary-button" type="submit" disabled={props.submitting || !props.locationsValid}>
          {props.submitting ? "Đang tính toán…" : "Tìm trạm phù hợp"}
        </button>
        <button className="secondary-button" type="button" onClick={props.onReset}>
          Reset demo
        </button>
      </div>
    </form>
  );
}
