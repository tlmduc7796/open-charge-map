from __future__ import annotations

import pytest

from ml.src.acquire_acn_data import parse_utc


def test_parse_utc_normalizes_z_suffix():
    assert parse_utc("2021-01-01T00:00:00Z").isoformat() == "2021-01-01T00:00:00+00:00"


def test_parse_utc_rejects_naive_timestamp():
    with pytest.raises(ValueError, match="explicit timezone"):
        parse_utc("2021-01-01T00:00:00")
