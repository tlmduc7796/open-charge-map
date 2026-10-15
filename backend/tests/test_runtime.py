from backend.app.config import load_settings
from backend.app.domain.repositories import load_domain_data
from backend.app.domain.runtime import RuntimeStateStore


def test_runtime_store_serves_and_refreshes_repository_status() -> None:
    data = load_domain_data(load_settings().data_dir)
    runtime = RuntimeStateStore(data.station_statuses)

    assert len(runtime.all()) == 16
    expected = data.station_statuses.get("ST_VF_LA_VELA")
    assert runtime.get("ST_VF_LA_VELA") == expected

    runtime.refresh()
    assert runtime.get("ST_VF_LA_VELA") == expected
