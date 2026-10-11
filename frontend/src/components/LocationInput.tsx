import { useEffect, useId, useState } from "react";

import { api } from "../api";
import { CURRENT_LOCATION_LABEL, getCurrentPosition, resolvePlaceLabel } from "../location";
import type { GeoPoint, PlaceSuggestion } from "../types";

interface LocationInputProps {
  label: string;
  point: GeoPoint;
  disabled?: boolean;
  /** True while this field is waiting for a click on the map. */
  picking?: boolean;
  onSelect: (point: GeoPoint) => void;
  onValidityChange: (valid: boolean) => void;
  /** When provided, shows the "pick on map" button. */
  onPickOnMap?: () => void;
}

function PinIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21z" />
      <circle cx="12" cy="9.5" r="2.5" />
    </svg>
  );
}

function LocateIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <circle cx="12" cy="12" r="7" />
      <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
    </svg>
  );
}

export default function LocationInput({
  label,
  point,
  disabled = false,
  picking = false,
  onSelect,
  onValidityChange,
  onPickOnMap,
}: LocationInputProps) {
  const inputId = useId();
  const selectedLabel = point.label ?? `${point.lat.toFixed(5)}, ${point.lon.toFixed(5)}`;
  const [query, setQuery] = useState(selectedLabel);
  const [suggestions, setSuggestions] = useState<PlaceSuggestion[]>([]);
  const [loading, setLoading] = useState(false);
  const [locating, setLocating] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (query.trim() === selectedLabel || query.trim().length < 2) return;
    const timer = window.setTimeout(async () => {
      setLoading(true);
      setMessage(null);
      try {
        const results = await api.geocodeSuggestions(query.trim());
        setSuggestions(results);
        if (!results.length) setMessage("Không tìm thấy địa điểm phù hợp.");
      } catch (caught) {
        setSuggestions([]);
        setMessage(caught instanceof Error ? caught.message : "Geocoding không khả dụng.");
      } finally {
        setLoading(false);
      }
    }, 300);
    return () => window.clearTimeout(timer);
  }, [query, selectedLabel]);

  const choose = async (suggestion: PlaceSuggestion) => {
    setLoading(true);
    setMessage(null);
    try {
      const place = await api.geocodeDetails(suggestion.place_id);
      onSelect(place.location);
      setQuery(place.label);
      setSuggestions([]);
      onValidityChange(true);
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "Không thể lấy tọa độ địa điểm.");
    } finally {
      setLoading(false);
    }
  };

  const selectCurrentLocation = async () => {
    setLocating(true);
    setMessage(null);
    setSuggestions([]);
    try {
      const { lat, lon } = await getCurrentPosition();
      const resolved = await resolvePlaceLabel(lat, lon, CURRENT_LOCATION_LABEL);
      onSelect({ lat, lon, label: resolved });
      setQuery(resolved);
      onValidityChange(true);
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "Không thể lấy vị trí hiện tại.");
    } finally {
      setLocating(false);
    }
  };

  return (
    <div className="location-input">
      <label htmlFor={inputId}>{label}</label>
      <div className="location-field">
        <input
          id={inputId}
          value={query}
          disabled={disabled}
          aria-invalid={query.trim() !== selectedLabel}
          autoComplete="off"
          onChange={(event) => {
            setQuery(event.target.value);
            setSuggestions([]);
            onValidityChange(event.target.value.trim() === selectedLabel);
          }}
        />
        {onPickOnMap && (
          <button
            type="button"
            className="location-icon-button"
            aria-label={`Chọn ${label.toLowerCase()} trên bản đồ`}
            aria-pressed={picking}
            title="Chọn trên bản đồ"
            disabled={disabled}
            onClick={onPickOnMap}
          >
            <PinIcon />
          </button>
        )}
        <button
          type="button"
          className="location-icon-button"
          aria-label={`Dùng vị trí hiện tại cho ${label.toLowerCase()}`}
          title="Dùng vị trí hiện tại"
          disabled={disabled || locating}
          onClick={() => void selectCurrentLocation()}
        >
          <LocateIcon />
        </button>
      </div>
      {!locating && loading && <small className="location-message">Đang tìm địa điểm…</small>}
      {!loading && !locating && message && <small className="location-message error">{message}</small>}
      {suggestions.length > 0 && (
        <ul className="location-suggestions">
          {suggestions.map((suggestion) => (
            <li key={suggestion.place_id}>
              <button type="button" onClick={() => void choose(suggestion)}>
                <strong>{suggestion.main_text}</strong>
                <span>{suggestion.secondary_text || suggestion.description}</span>
                <small>{suggestion.provider === "goong" ? "Goong" : "Demo fallback"}</small>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
