import httpx
import pytest

from backend.app.domain.geocoding import GeocodingService, GoongGeocodingProvider


class StubGoong:
    def autocomplete(self, query):
        return ("suggestion",)

    def details(self, place_id):
        return {"place_id": place_id}


def test_geocoding_without_provider_returns_no_suggestions() -> None:
    service = GeocodingService(goong=None)

    assert service.autocomplete("Phu Nhuan") == ()


def test_short_query_is_ignored_and_provider_errors_degrade_to_empty() -> None:
    class Failing(StubGoong):
        def autocomplete(self, query):
            raise RuntimeError("provider down")

    assert GeocodingService(goong=StubGoong()).autocomplete("a") == ()
    assert GeocodingService(goong=Failing()).autocomplete("Ben Thanh") == ()


def test_autocomplete_and_details_delegate_to_provider() -> None:
    service = GeocodingService(goong=StubGoong())

    assert service.autocomplete("Ben Thanh") == ("suggestion",)
    assert service.details("abc") == {"place_id": "abc"}


def test_reverse_delegates_and_requires_a_provider() -> None:
    class Reversing(StubGoong):
        def reverse(self, lat, lon):
            return {"lat": lat, "lon": lon}

    assert GeocodingService(goong=Reversing()).reverse(10.77, 106.7) == {
        "lat": 10.77,
        "lon": 106.7,
    }
    with pytest.raises(RuntimeError, match="not configured"):
        GeocodingService(goong=None).reverse(10.77, 106.7)


def test_reverse_wraps_unexpected_provider_errors() -> None:
    class Failing(StubGoong):
        def reverse(self, lat, lon):
            raise ValueError("boom")

    with pytest.raises(RuntimeError, match="unavailable"):
        GeocodingService(goong=Failing()).reverse(10.77, 106.7)


def _goong_provider(payload: dict) -> tuple[GoongGeocodingProvider, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return GoongGeocodingProvider("test-key", client=client), seen


def test_goong_reverse_reads_formatted_address_and_keeps_the_point() -> None:
    provider, seen = _goong_provider(
        {
            "results": [
                {"formatted_address": "1 Nguyen Hue, Quan 1", "place_id": "goong-place"}
            ],
            "status": "OK",
        }
    )

    place = provider.reverse(10.7769, 106.7009)

    assert place.label == "1 Nguyen Hue, Quan 1"
    assert place.place_id == "goong-place"
    assert (place.location.lat, place.location.lon) == (10.7769, 106.7009)
    assert seen[0].url.params["latlng"] == "10.7769,106.7009"


def test_goong_reverse_without_results_raises() -> None:
    provider, _ = _goong_provider({"results": [], "status": "ZERO_RESULTS"})

    with pytest.raises(RuntimeError):
        provider.reverse(0.0, 0.0)
