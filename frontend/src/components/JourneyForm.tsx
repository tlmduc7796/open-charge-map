import type { GeoPoint, Vehicle } from "../types";
import { fullRangeKm, rangeKmToSoc, socToRangeKm } from "../vehicleRange";
import LocationInput from "./LocationInput";

interface JourneyFormProps {
  vehicles: Vehicle[];
  vehicleId: string;
  initialSoc: number;
  origin: GeoPoint;
  destination: GeoPoint;
  locationsValid: boolean;
  submitting: boolean;
  onVehicleChange: (vehicleId: string) => void;
  onInitialSocChange: (soc: number) => void;
  onOriginChange: (point: GeoPoint) => void;
  onDestinationChange: (point: GeoPoint) => void;
  onOriginValidityChange: (valid: boolean) => void;
  onDestinationValidityChange: (valid: boolean) => void;
  onSubmit: () => void;
}

export default function JourneyForm(props: JourneyFormProps) {
  const vehicle = props.vehicles.find((item) => item.vehicle_id === props.vehicleId) ?? props.vehicles[0];
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
      </div>

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
      <p className="field-note">Chọn gợi ý Goong để đổi địa điểm.</p>

      <label>
        Xe điện
        <select value={props.vehicleId} onChange={(event) => props.onVehicleChange(event.target.value)}>
          {props.vehicles.map((item) => (
            <option key={item.vehicle_id} value={item.vehicle_id}>
              {item.make} {item.model} {item.variant ?? ""}
            </option>
          ))}
        </select>
      </label>

      {vehicle && (
        <label>
          Quãng đường tối đa EV có thể đi
          <div className="soc-input">
            <input
              aria-label="Quãng đường tối đa EV có thể đi"
              type="range"
              min="0"
              max={Math.round(fullRangeKm(vehicle))}
              value={Math.round(socToRangeKm(props.initialSoc, vehicle))}
              onChange={(event) => props.onInitialSocChange(rangeKmToSoc(Number(event.target.value), vehicle))}
            />
            <strong>{Math.round(socToRangeKm(props.initialSoc, vehicle))} km</strong>
          </div>
        </label>
      )}

      <div className="form-actions">
        <button className="primary-button" type="submit" disabled={props.submitting || !props.locationsValid}>
          {props.submitting ? "Đang tính toán…" : "Tìm trạm phù hợp"}
        </button>
      </div>
    </form>
  );
}
