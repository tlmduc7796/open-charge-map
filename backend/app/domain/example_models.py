"""Importable estimators used only by artifact-format examples and tests."""

from __future__ import annotations


class PersistenceExampleEstimator:
    """Return the most recent occupancy lag to illustrate the loader contract."""

    def predict(self, rows: list[list[float]]) -> list[float]:
        if any(not row for row in rows):
            raise ValueError("example estimator requires at least one feature")
        return [float(row[0]) for row in rows]
