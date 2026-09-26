from backend.app.config import load_settings
from backend.app.domain.geocoding import GeocodingService
from backend.app.domain.repositories import load_domain_data


def test_demo_geocoding_fallback_resolves_scenario_location() -> None:
    data = load_domain_data(load_settings().data_dir)
    service = GeocodingService(data.demo_scenarios.all(), goong=None)

    suggestions = service.autocomplete("Phu Nhuan")
    assert suggestions
    assert suggestions[0].provider == "demo"

    place = service.details(suggestions[0].place_id)
    assert place.provider == "demo"
    assert place.location.label == "Phu Nhuan"
    assert 10 < place.location.lat < 11
