from __future__ import annotations

from sqlalchemy import CheckConstraint, Index

from data_platform.database.models import PlannedArrival, StationArrivalRate


def _constraint_names(model: type[object]) -> set[str | None]:
    return {
        constraint.name
        for constraint in model.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }


def _index_names(model: type[object]) -> set[str | None]:
    return {
        index.name for index in model.__table__.indexes if isinstance(index, Index)
    }


def test_planned_arrival_schema_has_lifecycle_constraints_and_query_indexes() -> None:
    assert PlannedArrival.__table__.primary_key.columns.keys() == ["arrival_id"]
    assert {
        "ck_planned_arrivals_id_nonempty",
        "ck_planned_arrivals_route_id_nonempty",
        "ck_planned_arrivals_energy_nonnegative",
        "ck_planned_arrivals_charge_duration_positive",
        "ck_planned_arrivals_probability",
        "ck_planned_arrivals_status",
        "ck_planned_arrivals_source",
        "ck_planned_arrivals_eta_window",
        "ck_planned_arrivals_expiry",
    } <= _constraint_names(PlannedArrival)
    assert {
        "ix_planned_arrivals_station_eta_planned",
        "ix_planned_arrivals_expires_planned",
    } == _index_names(PlannedArrival)


def test_station_arrival_rate_schema_is_one_row_per_station() -> None:
    assert StationArrivalRate.__table__.primary_key.columns.keys() == ["station_id"]
    assert {
        "ck_station_arrival_rates_nonnegative",
        "ck_station_arrival_rates_source",
    } <= _constraint_names(StationArrivalRate)
