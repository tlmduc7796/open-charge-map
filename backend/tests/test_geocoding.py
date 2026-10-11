from backend.app.domain.geocoding import GeocodingService


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
