import type { GeoPoint, PickTarget, Vehicle } from "../types";
import LocationInput from "./LocationInput";

interface JourneyFormProps {
  searchMode: "stations" | "route";
  vehicles: Vehicle[];
  vehicleId: string;
  initialSoc: number;
  origin: GeoPoint;
  destination: GeoPoint;
  locationsValid: boolean;
  submitting: boolean;
  pickTarget?: PickTarget | null;
  onPickTargetChange?: (target: PickTarget | null) => void;
  onSearchModeChange: (mode: "stations" | "route") => void;
  onInitialSocChange: (soc: number) => void;
  onOriginChange: (point: GeoPoint) => void;
  onDestinationChange: (point: GeoPoint) => void;
  onOriginValidityChange: (valid: boolean) => void;
  onDestinationValidityChange: (valid: boolean) => void;
  onSubmit: () => void;
}

export default function JourneyForm(props: JourneyFormProps) {
  const vehicle = props.vehicles.find((item) => item.vehicle_id === props.vehicleId) ?? props.vehicles[0];
  const togglePick = (target: PickTarget) =>
    props.onPickTargetChange?.(props.pickTarget === target ? null : target);
  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    props.onSubmit();
  };

  return (
    <form className="journey-form" onSubmit={submit}>
      <div className="section-heading">
        <div>
          <span className="step-label">01 · Tìm kiếm</span>
          <h1>{props.searchMode === "stations" ? "Tìm trạm trong tầm pin" : "Tìm trạm trên hành trình"}</h1>
        </div>
      </div>

      <div className="search-mode-tabs" role="tablist" aria-label="Chế độ tìm kiếm">
        <button
          type="button"
          role="tab"
          aria-selected={props.searchMode === "stations"}
          className={props.searchMode === "stations" ? "active" : ""}
          onClick={() => props.onSearchModeChange("stations")}
        >
          Tìm trạm
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={props.searchMode === "route"}
          className={props.searchMode === "route" ? "active" : ""}
          onClick={() => props.onSearchModeChange("route")}
        >
          Tìm đường
        </button>
      </div>

      {props.searchMode === "stations" ? (
        <div className="station-search-location">
          <LocationInput
            key={`station-origin-${props.origin.lat}-${props.origin.lon}-${props.origin.label ?? ""}`}
            label="Điểm bắt đầu"
            point={props.origin}
            disabled={props.submitting}
            picking={props.pickTarget === "origin"}
            onSelect={props.onOriginChange}
            onValidityChange={props.onOriginValidityChange}
            onPickOnMap={() => togglePick("origin")}
          />
          <p className="field-note" aria-hidden="true" />
        </div>
      ) : (
        <div className="route-inputs">
          <LocationInput
            key={`origin-${props.origin.lat}-${props.origin.lon}-${props.origin.label ?? ""}`}
            label="Điểm đi"
            point={props.origin}
            disabled={props.submitting}
            picking={props.pickTarget === "origin"}
            onSelect={props.onOriginChange}
            onValidityChange={props.onOriginValidityChange}
            onPickOnMap={() => togglePick("origin")}
          />
          <LocationInput
            key={`destination-${props.destination.lat}-${props.destination.lon}-${props.destination.label ?? ""}`}
            label="Điểm đến"
            point={props.destination}
            disabled={props.submitting}
            picking={props.pickTarget === "destination"}
            onSelect={props.onDestinationChange}
            onValidityChange={props.onDestinationValidityChange}
            onPickOnMap={() => togglePick("destination")}
          />
        </div>
      )}
      {props.searchMode === "route" && <p className="field-note" aria-hidden="true" />}

      <label>
        Xe điện
        <span className="vehicle-select-wrap"><input
          aria-label="Xe điện"
          readOnly
          value={vehicle ? `${vehicle.make} ${vehicle.model} ${vehicle.variant ?? ""}`.trim() : ""}
        /><span aria-hidden="true">⌄</span></span>
      </label>

      {vehicle && <div className="form-spacer" aria-hidden="true" />}

      {vehicle && (
        <label>
          Phần trăm pin còn lại
          <div className="soc-input">
            <input
              aria-label="Phần trăm pin còn lại"
              type="range"
              min="0"
              max="100"
              step="1"
              value={Math.round(props.initialSoc * 100)}
              onChange={(event) => props.onInitialSocChange(Number(event.target.value) / 100)}
            />
            <strong>{Math.round(props.initialSoc * 100)}%</strong>
          </div>
        </label>
      )}

      {vehicle && <div className="form-spacer" aria-hidden="true" />}

      <div className="form-actions">
        <button className="primary-button" type="submit" disabled={props.submitting || !props.locationsValid}>
          {props.submitting ? "Đang tính toán…" : props.searchMode === "stations" ? "Tìm trạm" : "Tìm đường đi"}
        </button>
      </div>
    </form>
  );
}
