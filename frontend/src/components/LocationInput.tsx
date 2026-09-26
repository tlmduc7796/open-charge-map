import { useEffect, useState } from "react";

import { api } from "../api";
import type { GeoPoint, PlaceSuggestion } from "../types";

interface LocationInputProps {
  label: string;
  point: GeoPoint;
  disabled?: boolean;
  onSelect: (point: GeoPoint) => void;
  onValidityChange: (valid: boolean) => void;
}

export default function LocationInput({
  label,
  point,
  disabled = false,
  onSelect,
  onValidityChange,
}: LocationInputProps) {
  const selectedLabel = point.label ?? `${point.lat.toFixed(5)}, ${point.lon.toFixed(5)}`;
  const [query, setQuery] = useState(selectedLabel);
  const [suggestions, setSuggestions] = useState<PlaceSuggestion[]>([]);
  const [loading, setLoading] = useState(false);
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

  return (
    <label className="location-input">
      {label}
      <input
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
      {loading && <small className="location-message">Đang tìm địa điểm…</small>}
      {!loading && message && <small className="location-message error">{message}</small>}
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
    </label>
  );
}
