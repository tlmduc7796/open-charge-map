"""Goong geocoding with deterministic demo-location fallback."""

from __future__ import annotations

import hashlib
from typing import Any, Protocol

import httpx

from backend.app.domain.phase7_models import (
    DemoScenario,
    GeocodedPlace,
    GeoPoint,
    PlaceSuggestion,
)


class GeocodingProvider(Protocol):
    def autocomplete(self, query: str) -> tuple[PlaceSuggestion, ...]: ...

    def details(self, place_id: str) -> GeocodedPlace: ...


class GoongGeocodingProvider:
    def __init__(
        self,
        api_key: str,
        *,
        timeout_s: float = 8,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=timeout_s)

    def autocomplete(self, query: str) -> tuple[PlaceSuggestion, ...]:
        response = self._client.get(
            "https://rsapi.goong.io/Place/AutoComplete",
            params={
                "api_key": self._api_key,
                "input": query,
                "location": "10.7769,106.7009",
            },
        )
        response.raise_for_status()
        predictions: list[dict[str, Any]] = response.json().get("predictions", [])
        return tuple(
            PlaceSuggestion(
                place_id=item["place_id"],
                description=item.get("description", ""),
                main_text=item.get("structured_formatting", {}).get(
                    "main_text", item.get("description", "")
                ),
                secondary_text=item.get("structured_formatting", {}).get(
                    "secondary_text", ""
                ),
                provider="goong",
            )
            for item in predictions[:5]
            if item.get("place_id") and item.get("description")
        )

    def details(self, place_id: str) -> GeocodedPlace:
        response = self._client.get(
            "https://rsapi.goong.io/Place/Detail",
            params={"api_key": self._api_key, "place_id": place_id},
        )
        response.raise_for_status()
        result: dict[str, Any] = response.json().get("result") or {}
        location = result.get("geometry", {}).get("location", {})
        if "lat" not in location or "lng" not in location:
            raise RuntimeError("Goong place has no coordinates")
        label = result.get("formatted_address") or result.get("name") or place_id
        return GeocodedPlace(
            place_id=place_id,
            label=label,
            location=GeoPoint(
                lat=location["lat"], lon=location["lng"], label=label
            ),
            provider="goong",
        )


class GeocodingService:
    def __init__(
        self,
        scenarios: tuple[DemoScenario, ...],
        *,
        goong: GeocodingProvider | None,
    ) -> None:
        self._goong = goong
        self._demo_places: dict[str, GeocodedPlace] = {}
        for scenario in scenarios:
            self._add_demo_point(scenario.origin)
            self._add_demo_point(scenario.destination)

    def autocomplete(self, query: str) -> tuple[PlaceSuggestion, ...]:
        normalized = query.strip()
        if len(normalized) < 2:
            return ()
        if self._goong is not None:
            try:
                results = self._goong.autocomplete(normalized)
                if results:
                    return results
            except Exception:
                pass
        needle = normalized.casefold()
        return tuple(
            PlaceSuggestion(
                place_id=place.place_id,
                description=place.label,
                main_text=place.label,
                secondary_text="Demo scenario fallback",
                provider="demo",
            )
            for place in self._demo_places.values()
            if needle in place.label.casefold()
        )[:5]

    def details(self, place_id: str) -> GeocodedPlace:
        if place_id.startswith("demo:"):
            return self._demo_places[place_id]
        if self._goong is None:
            raise RuntimeError("Goong geocoding is not configured")
        return self._goong.details(place_id)

    def _add_demo_point(self, point: GeoPoint) -> None:
        label = point.label or f"{point.lat:.6f}, {point.lon:.6f}"
        digest = hashlib.sha256(
            f"{point.lat:.7f},{point.lon:.7f}".encode()
        ).hexdigest()[:12]
        place_id = f"demo:{digest}"
        self._demo_places.setdefault(
            place_id,
            GeocodedPlace(
                place_id=place_id,
                label=label,
                location=point.model_copy(update={"label": label}),
                provider="demo",
            ),
        )
