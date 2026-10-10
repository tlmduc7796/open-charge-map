"""Helpers for comparing values persisted in fixed-scale numeric columns."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def database_numeric_values_match(
    persisted: float | Decimal | None,
    requested: float | Decimal | None,
    *,
    decimal_places: int,
) -> bool:
    """Compare values after applying PostgreSQL NUMERIC scale rounding."""
    if decimal_places < 0:
        raise ValueError("decimal_places must be nonnegative")
    if persisted is None or requested is None:
        return persisted is None and requested is None
    quantum = Decimal(1).scaleb(-decimal_places)
    return Decimal(str(persisted)).quantize(
        quantum, rounding=ROUND_HALF_UP
    ) == Decimal(str(requested)).quantize(quantum, rounding=ROUND_HALF_UP)
