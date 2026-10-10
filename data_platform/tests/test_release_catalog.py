import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from data_platform.release_catalog import (
    _assert_provider_station_ref_owner,
    _expanded_station_ports,
    _invalidate_station_runtime_snapshots,
    _station_provenance_for_import,
    _upsert_provider_station_ref,
    _vehicle_provenance_for_import,
    import_release_catalog,
    load_release_catalog,
)
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from backend.app.domain.models import Connector


def _write_catalogs(tmp_path, *, synthetic_station: bool = False):
    stations_path = tmp_path / "stations.json"
    vehicles_path = tmp_path / "vehicles.json"
    stations_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [106.7, 10.8]},
                        "properties": {
                            "station_id": "OPS-001",
                            "provider_station_id": "station-1",
                            "name": "Reviewed station",
                            "address": "1 Test Street",
                            "operator": "Operator",
                            "total_ports": 1,
                            "connectors": [
                                {
                                    "type": "CCS2",
                                    "current": "DC",
                                    "max_power_kw": 120,
                                    "count": 1,
                                    "source": "operator_verified",
                                }
                            ],
                            "amenities": ["restroom"],
                            "opening_hours": None,
                            "access": "public",
                            "notes": [],
                            "source_provider": "operator_feed",
                            "source_updated_at": "2026-10-01T09:00:00+07:00",
                            "synthetic_fields": ["name"] if synthetic_station else [],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    vehicles_path.write_text(
        json.dumps(
            [
                {
                    "vehicle_id": "MODEL-001",
                    "make": "Maker",
                    "model": "Model",
                    "variant": "Long range",
                    "battery_capacity_kwh": 80,
                    "usable_battery_kwh": 76,
                    "max_ac_power_kw": 11,
                    "max_dc_power_kw": 150,
                    "ac_connectors": ["Type2"],
                    "dc_connectors": ["CCS2"],
                    "consumption_wh_km": 170,
                    "reserve_soc": 0.1,
                    "default_target_soc": 0.8,
                    "charging_efficiency": 0.92,
                    "source": "manufacturer specification",
                    "is_synthetic": False,
                    "synthetic_fields": [],
                    "field_provenance": {
                        "battery_capacity_kwh": {
                            "origin": "observed", "provider": "manufacturer",
                            "source_ref": "https://manufacturer.example/spec",
                        },
                        "usable_battery_kwh": {
                            "origin": "observed", "provider": "manufacturer",
                            "source_ref": "https://manufacturer.example/spec",
                        },
                        "max_ac_power_kw": {
                            "origin": "observed", "provider": "manufacturer",
                            "source_ref": "https://manufacturer.example/spec",
                        },
                        "max_dc_power_kw": {
                            "origin": "observed", "provider": "manufacturer",
                            "source_ref": "https://manufacturer.example/spec",
                        },
                        "ac_connectors": {
                            "origin": "observed", "provider": "manufacturer",
                            "source_ref": "https://manufacturer.example/spec",
                        },
                        "dc_connectors": {
                            "origin": "observed", "provider": "manufacturer",
                            "source_ref": "https://manufacturer.example/spec",
                        },
                        "consumption_wh_km": {
                            "origin": "inferred", "provider": "release-review-test",
                            "source_ref": "https://manufacturer.example/range",
                            "note": "test-cycle derivation",
                        },
                        "reserve_soc": {
                            "origin": "operator_policy", "provider": "test-policy",
                            "policy_id": "charging-policy-v1",
                        },
                        "default_target_soc": {
                            "origin": "operator_policy", "provider": "test-policy",
                            "policy_id": "charging-policy-v1",
                        },
                        "charging_efficiency": {
                            "origin": "operator_policy", "provider": "test-policy",
                            "policy_id": "charging-policy-v1",
                        },
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    return stations_path, vehicles_path


def test_release_catalog_preview_validates_and_does_not_write(tmp_path) -> None:
    stations_path, vehicles_path = _write_catalogs(tmp_path)
    stations, vehicles = load_release_catalog(stations_path, vehicles_path)

    assert import_release_catalog(None, stations, vehicles) == {
        "applied": False,
        "stations": 1,
        "vehicles": 1,
        "replace_snapshot": False,
        "mapped_port_ids": 0,
    }
    assert vehicles[0].field_provenance["consumption_wh_km"]["origin"] == "inferred"


def test_release_import_preserves_vehicle_field_origins_and_policy_reference(tmp_path) -> None:
    stations_path, vehicles_path = _write_catalogs(tmp_path)
    _stations, vehicles = load_release_catalog(stations_path, vehicles_path)

    provenance = _vehicle_provenance_for_import(
        vehicles[0],
        reviewed_by="operator@example.com",
        imported_at=datetime(2026, 10, 10, tzinfo=UTC),
    )

    assert provenance["consumption_kwh_per_100km"]["origin"] == "inferred"
    assert provenance["battery_kwh"]["origin"] == "observed"
    assert provenance["catalog_import"]["reviewed_by"] == "operator@example.com"
    assert (
        provenance["_calculation_defaults_provenance"]["reserve_soc"]["policy_id"]
        == "charging-policy-v1"
    )


def test_station_import_provenance_records_operator_review_and_source_time(tmp_path) -> None:
    stations_path, vehicles_path = _write_catalogs(tmp_path)
    stations, _vehicles = load_release_catalog(stations_path, vehicles_path)
    properties = stations.features[0].properties

    provenance = _station_provenance_for_import(
        properties,
        reviewed_by="operator@example.com",
        imported_at=datetime(2026, 10, 10, tzinfo=UTC),
    )

    assert provenance["name"]["origin"] == "operator_reviewed"
    assert provenance["location"]["reviewed_by"] == "operator@example.com"
    assert provenance["connectors"]["provider"] == "operator_feed"
    assert provenance["catalog_import"]["source_updated_at"] == "2026-10-01T09:00:00+07:00"


def test_release_catalog_preview_reports_snapshot_reconciliation_mode(tmp_path) -> None:
    stations_path, vehicles_path = _write_catalogs(tmp_path)
    stations, vehicles = load_release_catalog(stations_path, vehicles_path)

    preview = import_release_catalog(
        None, stations, vehicles, replace_snapshot=True
    )

    assert preview["applied"] is False
    assert preview["replace_snapshot"] is True
    assert preview["mapped_port_ids"] == 0


def test_release_catalog_validates_port_external_id_mapping(tmp_path) -> None:
    stations_path, vehicles_path = _write_catalogs(tmp_path)
    station_data = json.loads(stations_path.read_text(encoding="utf-8"))
    station_data["features"][0]["properties"]["total_ports"] = 2
    station_data["features"][0]["properties"]["connectors"][0]["count"] = 2
    stations_path.write_text(json.dumps(station_data), encoding="utf-8")
    stations, vehicles = load_release_catalog(stations_path, vehicles_path)

    preview = import_release_catalog(
        None,
        stations,
        vehicles,
        port_external_ids={"OPS-001": {"CCS2-1": "provider-port-42"}},
    )

    assert preview["mapped_port_ids"] == 1
    cleared_preview = import_release_catalog(
        None,
        stations,
        vehicles,
        port_external_ids={"OPS-001": {"CCS2-1": None}},
    )
    assert cleared_preview["mapped_port_ids"] == 0
    with pytest.raises(ValueError, match="unknown labels.*NOT-A-PORT"):
        import_release_catalog(
            None,
            stations,
            vehicles,
            port_external_ids={"OPS-001": {"NOT-A-PORT": "provider-port-42"}},
        )
    with pytest.raises(ValueError, match="duplicate provider IDs"):
        import_release_catalog(
            None,
            stations,
            vehicles,
            port_external_ids={
                "OPS-001": {"CCS2-1": "provider-port-42", "CCS2-2": "provider-port-42"}
            },
        )
    with pytest.raises(ValueError, match="nonempty provider IDs"):
        import_release_catalog(
            None,
            stations,
            vehicles,
            port_external_ids={"OPS-001": {"CCS2-1": "  "}},
        )


def test_import_cli_preview_reads_and_reports_port_mapping(tmp_path) -> None:
    stations_path, vehicles_path = _write_catalogs(tmp_path)
    port_map_path = tmp_path / "port-map.json"
    port_map_path.write_text(
        json.dumps({"OPS-001": {"CCS2-1": "aggregator-port-42"}}),
        encoding="utf-8",
    )
    script = Path(__file__).resolve().parents[1] / "scripts" / "import_release_catalog.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--stations",
            str(stations_path),
            "--vehicles",
            str(vehicles_path),
            "--port-map",
            str(port_map_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    preview = json.loads(result.stdout)
    assert preview["applied"] is False
    assert preview["mapped_port_ids"] == 1


@pytest.mark.skipif(
    not os.getenv("DATA_PLATFORM_TEST_DATABASE_URL"),
    reason="set DATA_PLATFORM_TEST_DATABASE_URL to run release CLI database integration",
)
def test_import_cli_apply_persists_reviewed_port_mapping(tmp_path) -> None:
    database_url = os.environ["DATA_PLATFORM_TEST_DATABASE_URL"]
    stations_path, vehicles_path = _write_catalogs(tmp_path)
    station_code = f"CLI_PORT_MAP_{uuid4().hex}"
    vehicle_code = f"CLI_PORT_MAP_VEHICLE_{uuid4().hex}"
    provider = f"CLI_PORT_MAP_PROVIDER_{uuid4().hex}"
    provider_port_id = f"provider-port-{uuid4().hex}"
    station_data = json.loads(stations_path.read_text(encoding="utf-8"))
    station_properties = station_data["features"][0]["properties"]
    station_properties["station_id"] = station_code
    station_properties["provider_station_id"] = f"provider-{station_code}"
    station_properties["source_provider"] = provider
    stations_path.write_text(json.dumps(station_data), encoding="utf-8")
    vehicles = json.loads(vehicles_path.read_text(encoding="utf-8"))
    vehicles[0]["vehicle_id"] = vehicle_code
    vehicles_path.write_text(json.dumps(vehicles), encoding="utf-8")
    port_map_path = tmp_path / "port-map.json"
    port_map_path.write_text(
        json.dumps({station_code: {"CCS2-1": provider_port_id}}),
        encoding="utf-8",
    )
    script = Path(__file__).resolve().parents[1] / "scripts" / "import_release_catalog.py"
    environment = os.environ.copy()
    environment["DATA_PLATFORM_DATABASE_URL"] = database_url
    engine = create_engine(database_url)
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "--stations",
                str(stations_path),
                "--vehicles",
                str(vehicles_path),
                "--port-map",
                str(port_map_path),
                "--apply",
                "--reviewed-by",
                "integration-test",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        report = json.loads(result.stdout)
        assert report["applied"] is True
        assert report["mapped_port_ids"] == 1
        with engine.connect() as connection:
            port_mapping = connection.execute(
                text(
                    "SELECT external_id, provenance->'port_mapping'->>'reviewed_by' "
                    "FROM ports WHERE station_id=(SELECT id FROM stations WHERE code=:code) "
                    "AND label='CCS2-1'"
                ),
                {"code": station_code},
            ).one()
        assert port_mapping == (provider_port_id, "integration-test")
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM stations WHERE code=:code"), {"code": station_code}
            )
            connection.execute(
                text("DELETE FROM vehicle_models WHERE code=:code"),
                {"code": vehicle_code},
            )
        engine.dispose()


@pytest.mark.skipif(
    not os.getenv("DATA_PLATFORM_TEST_DATABASE_URL"),
    reason="set DATA_PLATFORM_TEST_DATABASE_URL to test path identifier constraints",
)
def test_postgres_rejects_non_path_safe_station_and_arrival_ids() -> None:
    engine = create_engine(os.environ["DATA_PLATFORM_TEST_DATABASE_URL"])
    try:
        with engine.begin() as connection:
            station_code = connection.scalar(text("SELECT code FROM stations LIMIT 1"))
            arrival_id = connection.scalar(
                text("SELECT arrival_id FROM planned_arrivals LIMIT 1")
            )
            assert station_code is not None
            assert arrival_id is not None

            for table, column, current_value, invalid_value, constraint in (
                (
                    "stations",
                    "code",
                    station_code,
                    f"{station_code}/unsafe",
                    "ck_stations_code_path_segment",
                ),
                (
                    "planned_arrivals",
                    "arrival_id",
                    arrival_id,
                    f"{arrival_id}/unsafe",
                    "ck_planned_arrivals_id_path_segment",
                ),
            ):
                with pytest.raises(IntegrityError) as error:
                    with connection.begin_nested():
                        connection.execute(
                            text(f"UPDATE {table} SET {column}=:invalid WHERE {column}=:current"),
                            {"invalid": invalid_value, "current": current_value},
                        )
                assert error.value.orig.diag.constraint_name == constraint
    finally:
        engine.dispose()


def test_import_boundary_revalidates_models_after_catalog_load(tmp_path) -> None:
    stations_path, vehicles_path = _write_catalogs(tmp_path)
    stations, vehicles = load_release_catalog(stations_path, vehicles_path)
    ineligible = vehicles[0].model_copy(update={"is_synthetic": True})

    with pytest.raises(ValueError, match="vehicle MODEL-001 contains synthetic data"):
        import_release_catalog(None, stations, (ineligible,))


def test_same_connector_can_have_multiple_power_groups_with_unique_stable_labels() -> None:
    connectors = (
        Connector(
            type="CCS2",
            current="DC",
            max_power_kw=180,
            count=2,
            source="operator_verified",
        ),
        Connector(
            type="CCS 2",
            current="DC",
            max_power_kw=120,
            count=1,
            source="operator_verified",
        ),
    )

    assignments = _expanded_station_ports(connectors)

    assert [(code, label, connector.max_power_kw) for connector, code, label in assignments] == [
        ("CCS2", "CCS2-1", 120),
        ("CCS2", "CCS2-2", 180),
        ("CCS2", "CCS2-3", 180),
    ]


def test_release_catalog_accepts_duplicate_connector_types_at_distinct_power_levels(
    tmp_path,
) -> None:
    stations_path, vehicles_path = _write_catalogs(tmp_path)
    station_document = json.loads(stations_path.read_text(encoding="utf-8"))
    properties = station_document["features"][0]["properties"]
    properties["total_ports"] = 3
    properties["connectors"] = [
        {
            "type": "CCS2",
            "current": "DC",
            "max_power_kw": 120,
            "count": 1,
            "source": "operator_verified",
        },
        {
            "type": "CCS 2",
            "current": "DC",
            "max_power_kw": 180,
            "count": 2,
            "source": "operator_verified",
        },
    ]
    stations_path.write_text(json.dumps(station_document), encoding="utf-8")

    stations, _vehicles = load_release_catalog(stations_path, vehicles_path)

    assert len(stations.features[0].properties.connectors) == 2


def test_release_catalog_rejects_synthetic_station_fields(tmp_path) -> None:
    stations_path, vehicles_path = _write_catalogs(tmp_path, synthetic_station=True)

    with pytest.raises(ValueError, match="synthetic fields"):
        load_release_catalog(stations_path, vehicles_path)


def test_release_catalog_rejects_synthetic_station_source_provider(tmp_path) -> None:
    stations_path, vehicles_path = _write_catalogs(tmp_path)
    station_data = json.loads(stations_path.read_text(encoding="utf-8"))
    station_data["features"][0]["properties"]["source_provider"] = "Synthetic Import Feed"
    stations_path.write_text(json.dumps(station_data), encoding="utf-8")

    with pytest.raises(ValueError, match="synthetic source provider"):
        load_release_catalog(stations_path, vehicles_path)


def test_release_catalog_rejects_blank_station_source_provider(tmp_path) -> None:
    stations_path, vehicles_path = _write_catalogs(tmp_path)
    station_data = json.loads(stations_path.read_text(encoding="utf-8"))
    station_data["features"][0]["properties"]["source_provider"] = "  "
    stations_path.write_text(json.dumps(station_data), encoding="utf-8")

    with pytest.raises(ValueError, match="station OPS-001 requires source_provider"):
        load_release_catalog(stations_path, vehicles_path)


def test_release_catalog_rejects_duplicate_provider_station_references(tmp_path) -> None:
    stations_path, vehicles_path = _write_catalogs(tmp_path)
    station_data = json.loads(stations_path.read_text(encoding="utf-8"))
    duplicate = json.loads(json.dumps(station_data["features"][0]))
    duplicate["properties"]["station_id"] = "OPS-002"
    duplicate["geometry"]["coordinates"] = [106.8, 10.9]
    station_data["features"].append(duplicate)
    stations_path.write_text(json.dumps(station_data), encoding="utf-8")

    with pytest.raises(ValueError, match="provider station reference operator_feed/station-1"):
        load_release_catalog(stations_path, vehicles_path)


def test_import_refuses_to_reassign_existing_provider_station_reference() -> None:
    expected_station_id = uuid4()

    class Result:
        def scalar_one_or_none(self):
            return uuid4()

    class Connection:
        def execute(self, statement, parameters):
            assert "FOR UPDATE" in str(statement)
            assert parameters == {"provider": "operator_feed", "external_id": "station-1"}
            return Result()

    with pytest.raises(ValueError, match="already belongs to a different station"):
        _assert_provider_station_ref_owner(
            Connection(),
            provider="operator_feed",
            external_id="station-1",
            station_id=expected_station_id,
        )


@pytest.mark.skipif(
    not os.getenv("DATA_PLATFORM_TEST_DATABASE_URL"),
    reason="set DATA_PLATFORM_TEST_DATABASE_URL to run PostgreSQL reference-upsert integration",
)
def test_postgres_concurrent_provider_ref_upserts_keep_one_owner() -> None:
    engine = create_engine(os.environ["DATA_PLATFORM_TEST_DATABASE_URL"])
    stations = (uuid4(), uuid4())
    schema = f"station_ref_test_{uuid4().hex}"
    observed_at = datetime(2026, 10, 10, tzinfo=UTC)
    barrier = Barrier(2)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(f'CREATE SCHEMA "{schema}"')
            )
            connection.execute(
                text(
                    f'CREATE TABLE "{schema}".station_external_refs ('
                    "id uuid PRIMARY KEY, station_id uuid NOT NULL, provider text NOT NULL, "
                    "external_id text NOT NULL, retrieved_at timestamptz NOT NULL, "
                    "is_primary boolean NOT NULL, UNIQUE(provider, external_id))"
                )
            )

        def attempt(station_id):
            with engine.begin() as connection:
                connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                barrier.wait(timeout=5)
                try:
                    _upsert_provider_station_ref(
                        connection,
                        reference_id=uuid4(),
                        station_id=station_id,
                        provider="operator_feed",
                        external_id="station-1",
                        retrieved_at=observed_at,
                    )
                except ValueError:
                    return "conflict"
                return "saved"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = tuple(pool.map(attempt, stations))
        assert sorted(results) == ["conflict", "saved"]

        with engine.begin() as connection:
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            assert connection.execute(
                text(
                    "SELECT station_id FROM station_external_refs "
                    "WHERE provider='operator_feed' AND external_id='station-1'"
                )
            ).scalar_one() in stations
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()


def test_release_catalog_reports_station_and_vehicle_eligibility_issues(tmp_path) -> None:
    stations_path, vehicles_path = _write_catalogs(tmp_path, synthetic_station=True)
    station_document = json.loads(stations_path.read_text(encoding="utf-8"))
    station_document["features"][0]["properties"]["total_ports"] = 2
    station_document["features"][0]["properties"]["connectors"] = [
        {
            "type": "CCS2",
            "current": "DC",
            "max_power_kw": power,
            "count": 1,
            "source": "synthetic",
        }
        for power in (120, 180)
    ]
    stations_path.write_text(json.dumps(station_document), encoding="utf-8")
    vehicles = json.loads(vehicles_path.read_text(encoding="utf-8"))
    vehicles[0]["is_synthetic"] = True
    vehicles[0]["synthetic_fields"] = ["battery_capacity_kwh"]
    vehicles[0]["max_ac_power_kw"] = 0
    vehicles[0]["max_dc_power_kw"] = 0
    vehicles_path.write_text(json.dumps(vehicles), encoding="utf-8")

    with pytest.raises(ValueError, match="release catalog is not eligible") as error:
        load_release_catalog(stations_path, vehicles_path)

    assert "station OPS-001 has synthetic fields: name" in str(error.value)
    assert "vehicle MODEL-001 contains synthetic data" in str(error.value)
    assert "vehicle MODEL-001 requires a positive charging power" in str(error.value)
    assert str(error.value).count("station OPS-001 has synthetic connectors") == 1


def test_release_catalog_requires_per_field_vehicle_provenance(tmp_path) -> None:
    stations_path, vehicles_path = _write_catalogs(tmp_path)
    vehicles = json.loads(vehicles_path.read_text(encoding="utf-8"))
    vehicles[0]["field_provenance"].pop("consumption_wh_km")
    vehicles_path.write_text(json.dumps(vehicles), encoding="utf-8")

    with pytest.raises(ValueError, match="field_provenance.consumption_wh_km"):
        load_release_catalog(stations_path, vehicles_path)


def test_release_catalog_requires_operator_policy_provenance_for_soc_defaults(tmp_path) -> None:
    stations_path, vehicles_path = _write_catalogs(tmp_path)
    vehicles = json.loads(vehicles_path.read_text(encoding="utf-8"))
    vehicles[0]["field_provenance"]["reserve_soc"]["origin"] = "inferred"
    vehicles_path.write_text(json.dumps(vehicles), encoding="utf-8")

    with pytest.raises(ValueError, match="requires operator_policy provenance for reserve_soc"):
        load_release_catalog(stations_path, vehicles_path)


def test_release_catalog_rejects_synthetic_field_provenance(tmp_path) -> None:
    stations_path, vehicles_path = _write_catalogs(tmp_path)
    vehicles = json.loads(vehicles_path.read_text(encoding="utf-8"))
    vehicles[0]["field_provenance"]["consumption_wh_km"]["origin"] = "synthetic"
    vehicles_path.write_text(json.dumps(vehicles), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid provenance origin.*consumption_wh_km"):
        load_release_catalog(stations_path, vehicles_path)


def test_release_catalog_rejects_synthetic_vehicle_source(tmp_path) -> None:
    stations_path, vehicles_path = _write_catalogs(tmp_path)
    vehicles = json.loads(vehicles_path.read_text(encoding="utf-8"))
    vehicles[0]["source"] = "Synthetic vehicle catalog"
    vehicles_path.write_text(json.dumps(vehicles), encoding="utf-8")

    with pytest.raises(ValueError, match="vehicle MODEL-001 contains synthetic data"):
        load_release_catalog(stations_path, vehicles_path)


def test_release_catalog_rejects_synthetic_field_provider(tmp_path) -> None:
    stations_path, vehicles_path = _write_catalogs(tmp_path)
    vehicles = json.loads(vehicles_path.read_text(encoding="utf-8"))
    vehicles[0]["field_provenance"]["consumption_wh_km"]["provider"] = (
        "Synthetic inference feed"
    )
    vehicles_path.write_text(json.dumps(vehicles), encoding="utf-8")

    with pytest.raises(ValueError, match="synthetic provenance provider.*consumption_wh_km"):
        load_release_catalog(stations_path, vehicles_path)


def test_release_catalog_requires_vehicle_field_provider(tmp_path) -> None:
    stations_path, vehicles_path = _write_catalogs(tmp_path)
    vehicles = json.loads(vehicles_path.read_text(encoding="utf-8"))
    vehicles[0]["field_provenance"]["consumption_wh_km"].pop("provider")
    vehicles_path.write_text(json.dumps(vehicles), encoding="utf-8")

    with pytest.raises(ValueError, match="requires provenance provider for consumption_wh_km"):
        load_release_catalog(stations_path, vehicles_path)


def test_release_catalog_rejects_unpublished_provenance_for_populated_values(tmp_path) -> None:
    stations_path, vehicles_path = _write_catalogs(tmp_path)
    vehicles = json.loads(vehicles_path.read_text(encoding="utf-8"))
    vehicles[0]["field_provenance"]["consumption_wh_km"]["origin"] = "unpublished"
    vehicles_path.write_text(json.dumps(vehicles), encoding="utf-8")

    with pytest.raises(ValueError, match="cannot mark populated consumption_wh_km"):
        load_release_catalog(stations_path, vehicles_path)


def test_topology_change_invalidates_current_telemetry_without_deleting_history() -> None:
    class Result:
        rowcount = 3

    class Connection:
        statements: list[str]

        def __init__(self):
            self.statements = []

        def execute(self, statement, _parameters):
            self.statements.append(str(statement))
            return Result()

    connection = Connection()

    invalidated = _invalidate_station_runtime_snapshots(connection, "station-uuid")

    assert invalidated == 3
    assert any("DELETE FROM port_status" in statement for statement in connection.statements)
    assert any(
        "DELETE FROM station_live_metrics" in statement
        for statement in connection.statements
    )
    assert any(
        "DELETE FROM station_telemetry_snapshots" in statement
        for statement in connection.statements
    )
    assert all("station_occupancy_5m" not in statement for statement in connection.statements)
