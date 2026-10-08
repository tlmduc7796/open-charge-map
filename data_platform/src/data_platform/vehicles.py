"""Reconcile the manufacturer catalog with the legacy demo vehicles and seed PostgreSQL."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, text

VEHICLE_NAMESPACE = uuid.UUID("f94a5b96-193a-4a39-93fb-85376024a52e")
NUMERIC_FIELDS = ("battery_kwh", "consumption_kwh_per_100km", "max_ac_kw", "max_dc_kw")
RETIRED_BYD_BROCHURE_URL = (
    "https://www.byd.com/content/dam/byd-site/vn/proudct-specs/"
    "new-catalogue-2024/Brochure%20Catalogue_BYD_ATTO%203_VN_view.pdf"
)
CONNECTOR_TYPES = {
    "TYPE2": ("Type 2", "AC"),
    "CCS2": ("CCS 2", "DC"),
    "GBTAC": ("GB/T AC", "AC"),
    "GBTDC": ("GB/T DC", "DC"),
}


@dataclass(frozen=True)
class VehicleSeedBundle:
    vehicles: tuple[dict[str, Any], ...]
    connectors: tuple[tuple[str, str], ...]
    matched_demo_ids: tuple[str, ...]


def _key(brand: str, model: str, variant: str | None, market: str) -> tuple[str, ...]:
    return tuple(" ".join(value.lower().split()) for value in (brand, model, variant or "", market))


def _connector_code(value: str) -> str:
    code = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    if code not in CONNECTOR_TYPES:
        raise ValueError(f"unsupported vehicle connector: {value}")
    return code


def _positive(value: Any, field: str, code: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{code}.{field} must be positive or null")
    return float(value)


def build_vehicle_bundle(catalog: dict[str, Any], demo: list[dict[str, Any]]) -> VehicleSeedBundle:
    snapshot = catalog.get("snapshot")
    if not isinstance(snapshot, dict) or not snapshot.get("retrieved_at"):
        raise ValueError("vehicle catalog requires snapshot.retrieved_at")
    defaults = snapshot.get("calculation_defaults")
    if (
        not isinstance(defaults, dict)
        or defaults.get("origin") != "synthetic"
        or not defaults.get("provider")
        or not defaults.get("note")
    ):
        raise ValueError("vehicle catalog requires synthetic calculation defaults")
    reserve = defaults.get("reserve_soc")
    target = defaults.get("default_target_soc")
    efficiency = defaults.get("charging_efficiency")
    if not all(type(value) in (int, float) for value in (reserve, target, efficiency)):
        raise ValueError("vehicle calculation defaults must be numeric")
    if not (0 <= reserve < target <= 1 and 0 < efficiency <= 1):
        raise ValueError("vehicle calculation defaults are out of range")
    for field in ("unknown_ac_planning_kw", "unknown_dc_planning_kw"):
        if _positive(defaults.get(field), field, "calculation_defaults") is None:
            raise ValueError(f"vehicle calculation defaults require {field}")
    if not isinstance(catalog.get("vehicles"), list) or not isinstance(demo, list):
        raise ValueError("vehicle catalog and demo vehicles must be arrays")

    vehicles: list[dict[str, Any]] = []
    by_key: dict[tuple[str, ...], dict[str, Any]] = {}
    codes: set[str] = set()
    matched_demo_ids: list[str] = []
    for raw in catalog["vehicles"]:
        code = str(raw.get("code", "")).strip()
        if not code or code in codes:
            raise ValueError(f"missing or duplicate vehicle code: {code!r}")
        codes.add(code)
        for field in ("brand", "model", "market"):
            if not str(raw.get(field, "")).strip():
                raise ValueError(f"{code}.{field} is required")
        key = _key(raw["brand"], raw["model"], raw.get("variant"), raw["market"])
        if key in by_key:
            raise ValueError(f"duplicate vehicle configuration: {code}")
        provenance = dict(raw.get("provenance") or {})
        provenance["_calculation_defaults"] = {
            field: defaults[field]
            for field in ("reserve_soc", "default_target_soc", "charging_efficiency")
        }
        for field in provenance["_calculation_defaults"]:
            provenance.setdefault(
                field,
                {
                    "origin": "synthetic",
                    "provider": defaults["provider"],
                    "note": defaults["note"],
                },
            )
        for field in NUMERIC_FIELDS:
            value = _positive(raw.get(field), field, code)
            if value is not None and field not in provenance:
                raise ValueError(f"missing provenance for {code}.{field}")
        year = raw.get("model_year")
        if year is not None and (type(year) is not int or not 2000 <= year <= 2200):
            raise ValueError(f"invalid model_year for {code}")
        connectors = raw.get("connectors")
        if not isinstance(connectors, list) or not connectors:
            raise ValueError(f"{code} requires connectors")
        connector_codes = tuple(_connector_code(item) for item in connectors)
        if len(connector_codes) != len(set(connector_codes)):
            raise ValueError(f"duplicate connector for {code}")
        power_fallbacks = {}
        for field, connector, default_field in (
            ("max_ac_kw", "TYPE2", "unknown_ac_planning_kw"),
            ("max_dc_kw", "CCS2", "unknown_dc_planning_kw"),
        ):
            if raw.get(field) is None and connector in connector_codes:
                power_fallbacks[field] = defaults[default_field]
                provenance.setdefault(
                    field,
                    {
                        "origin": "synthetic",
                        "provider": defaults["provider"],
                        "note": "Demo calculation fallback; manufacturer maximum remains unknown.",
                    },
                )
        if power_fallbacks:
            provenance["_planning_power_fallback"] = power_fallbacks
        vehicle = {
            **raw,
            "provenance": {**provenance, "_snapshot": snapshot},
            "connectors": connector_codes,
        }
        vehicles.append(vehicle)
        by_key[key] = vehicle

    for raw in demo:
        legacy_id = str(raw.get("vehicle_id", "")).strip()
        if not legacy_id or legacy_id in matched_demo_ids:
            raise ValueError(f"missing or duplicate demo vehicle_id: {legacy_id!r}")
        matched_demo_ids.append(legacy_id)
        legacy_fields = {
            "battery_kwh": raw.get("usable_battery_kwh"),
            "consumption_kwh_per_100km": (
                raw["consumption_wh_km"] / 10 if raw.get("consumption_wh_km") is not None else None
            ),
            "max_ac_kw": raw.get("max_ac_power_kw"),
            "max_dc_kw": raw.get("max_dc_power_kw"),
        }
        legacy_meta = {
            "vehicle_id": legacy_id,
            "source_ref": raw.get("source"),
            "reserve_soc": raw.get("reserve_soc"),
            "default_target_soc": raw.get("default_target_soc"),
            "charging_efficiency": raw.get("charging_efficiency"),
            "consumption_wh_km": raw.get("consumption_wh_km"),
        }
        market = "DEMO" if raw.get("is_synthetic") else "VN"
        key = _key(raw["make"], raw["model"], raw.get("variant"), market)
        vehicle = by_key.get(key)
        if vehicle is not None:
            vehicle["provenance"]["_legacy_demo"] = legacy_meta
            for field, value in legacy_fields.items():
                if vehicle.get(field) is None and value is not None:
                    vehicle[field] = _positive(value, field, legacy_id)
                    vehicle["provenance"][field] = {
                        "origin": "synthetic"
                        if field in raw.get("synthetic_fields", [])
                        else "inferred",
                        "provider": "legacy_demo_fixture",
                        "source_ref": raw.get("source"),
                        "confidence": 0.6,
                        "note": "Filled from the legacy demo profile; review before use.",
                    }
            continue
        if not raw.get("is_synthetic"):
            raise ValueError(f"unmatched non-synthetic demo vehicle: {legacy_id}")
        if legacy_id in codes:
            raise ValueError(f"duplicate vehicle code: {legacy_id}")
        codes.add(legacy_id)
        connectors = tuple(
            _connector_code(item)
            for item in raw.get("ac_connectors", []) + raw.get("dc_connectors", [])
        )
        if not connectors or len(connectors) != len(set(connectors)):
            raise ValueError(f"invalid demo connectors for {legacy_id}")
        provenance = {
            field: {
                "origin": "synthetic",
                "provider": "project_demo_fixture",
                "source_ref": raw.get("source"),
                "confidence": 1.0,
            }
            for field, value in legacy_fields.items()
            if value is not None
        }
        provenance.update(
            {
                "connectors": {
                    "origin": "synthetic",
                    "provider": "project_demo_fixture",
                    "confidence": 1.0,
                },
                "_demo_only": True,
                "_legacy_demo": legacy_meta,
            }
        )
        vehicle = {
            "code": legacy_id,
            "brand": raw["make"],
            "model": raw["model"],
            "variant": raw.get("variant"),
            "model_year": None,
            "market": "DEMO",
            **{field: _positive(value, field, legacy_id) for field, value in legacy_fields.items()},
            "connectors": connectors,
            "is_active": False,
            "provenance": provenance,
        }
        vehicles.append(vehicle)
        by_key[key] = vehicle

    connector_pairs = tuple(
        (vehicle["code"], connector) for vehicle in vehicles for connector in vehicle["connectors"]
    )
    return VehicleSeedBundle(tuple(vehicles), connector_pairs, tuple(matched_demo_ids))


def load_vehicle_seed(catalog_path: Path, demo_path: Path) -> VehicleSeedBundle:
    return build_vehicle_bundle(
        json.loads(catalog_path.read_text(encoding="utf-8")),
        json.loads(demo_path.read_text(encoding="utf-8")),
    )


def seed_vehicle_data(engine: Engine, catalog_path: Path, demo_path: Path) -> dict[str, int]:
    """Insert missing vehicles and fill null fields without replacing existing DB values."""
    bundle = load_vehicle_seed(catalog_path, demo_path)
    with engine.begin() as connection:
        existing = (
            connection.execute(text("SELECT * FROM vehicle_models FOR UPDATE")).mappings().all()
        )
        matches: list[tuple[dict[str, Any], Any | None]] = []
        used_ids: set[uuid.UUID] = set()
        for vehicle in bundle.vehicles:
            alias = vehicle["provenance"].get("_legacy_demo", {}).get("vehicle_id")
            key = _key(
                vehicle["brand"], vehicle["model"], vehicle.get("variant"), vehicle["market"]
            )
            candidates = [
                row
                for row in existing
                if row["code"] in {vehicle["code"], alias}
                or _key(row["brand"], row["model"], row["variant"], row["market"]) == key
            ]
            if len(candidates) > 1:
                raise ValueError(
                    f"multiple existing DB rows match {vehicle['code']}; manual review required"
                )
            row = candidates[0] if candidates else None
            if row is not None:
                if row["id"] in used_ids:
                    raise ValueError(
                        f"existing DB row matches more than one source vehicle: {row['code']}"
                    )
                used_ids.add(row["id"])
            matches.append((vehicle, row))

        needed_types = {connector for _, connector in bundle.connectors}
        for code in sorted(needed_types):
            display_name, current_type = CONNECTOR_TYPES[code]
            connection.execute(
                text(
                    "INSERT INTO connector_types (code, display_name, current_type) "
                    "VALUES (:code, :display_name, CAST(:current_type AS current_type)) "
                    "ON CONFLICT (code) DO NOTHING"
                ),
                {"code": code, "display_name": display_name, "current_type": current_type},
            )

        inserted = updated = 0
        for vehicle, row in matches:
            provenance = dict(vehicle["provenance"])
            values = {field: vehicle.get(field) for field in NUMERIC_FIELDS}
            if row is not None:
                prior_provenance = dict(row["provenance"] or {})
                provenance = {**provenance, **prior_provenance}
                for field, details in vehicle["provenance"].items():
                    previous = provenance.get(field)
                    if (
                        isinstance(details, dict)
                        and isinstance(previous, dict)
                        and previous.get("source_ref") == RETIRED_BYD_BROCHURE_URL
                    ):
                        previous["source_ref"] = details.get("source_ref")
                for field in NUMERIC_FIELDS:
                    if row[field] is not None:
                        values[field] = row[field]
                    elif values[field] is not None:
                        provenance[field] = vehicle["provenance"][field]
                if values["battery_kwh"] is not None:
                    provenance.pop("_battery_note", None)
                vehicle_id = row["id"]
                connection.execute(
                    text(
                        "UPDATE vehicle_models SET code=:code, brand=:brand, model=:model, "
                        "variant=:variant, model_year=:model_year, market=:market, "
                        "battery_kwh=:battery_kwh, "
                        "consumption_kwh_per_100km=:consumption_kwh_per_100km, "
                        "max_ac_kw=:max_ac_kw, max_dc_kw=:max_dc_kw, is_active=:is_active, "
                        "provenance=CAST(:provenance AS jsonb) WHERE id=:id"
                    ),
                    {
                        "id": vehicle_id,
                        **{
                            k: vehicle.get(k)
                            for k in ("code", "brand", "model", "variant", "model_year", "market")
                        },
                        **values,
                        "is_active": False if provenance.get("_demo_only") else row["is_active"],
                        "provenance": json.dumps(provenance),
                    },
                )
                updated += 1
            else:
                vehicle_id = uuid.uuid5(VEHICLE_NAMESPACE, f"vehicle:{vehicle['code']}")
                connection.execute(
                    text(
                        "INSERT INTO vehicle_models "
                        "(id, code, brand, model, variant, model_year, market, battery_kwh, "
                        "consumption_kwh_per_100km, max_ac_kw, max_dc_kw, is_active, provenance) "
                        "VALUES (:id, :code, :brand, :model, :variant, :model_year, :market, "
                        ":battery_kwh, :consumption_kwh_per_100km, :max_ac_kw, :max_dc_kw, "
                        ":is_active, CAST(:provenance AS jsonb))"
                    ),
                    {
                        "id": vehicle_id,
                        **{
                            k: vehicle.get(k)
                            for k in (
                                "code",
                                "brand",
                                "model",
                                "variant",
                                "model_year",
                                "market",
                                "is_active",
                            )
                        },
                        **values,
                        "provenance": json.dumps(provenance),
                    },
                )
                inserted += 1
            for connector in vehicle["connectors"]:
                connection.execute(
                    text(
                        "INSERT INTO vehicle_connectors (vehicle_model_id, connector_code) "
                        "VALUES (:id, :connector) ON CONFLICT DO NOTHING"
                    ),
                    {"id": vehicle_id, "connector": connector},
                )
    return {
        "inserted": inserted,
        "updated": updated,
        "vehicles": len(bundle.vehicles),
        "connectors": len(bundle.connectors),
    }
