from __future__ import annotations

import json
from pathlib import Path

from data_platform.synthetic_port_seed import _scaled_statuses

STATUS_PATH = Path(__file__).resolve().parents[1] / "data/runtime/station_status.json"


def test_scaled_statuses_preserve_template_distribution() -> None:
    templates = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    for template in templates:
        for port_count in range(5, 11):
            statuses = _scaled_statuses(template, port_count)
            assert len(statuses) == port_count
            assert set(statuses) <= {"available", "charging", "out_of_service"}


def test_scaled_statuses_follow_busy_four_port_template() -> None:
    templates = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    busy = next(item for item in templates if item["station_id"] == "ST_EVO_DEUTSCHES_HAUS")
    statuses = _scaled_statuses(busy, 8)

    assert statuses.count("charging") == 6
    assert statuses.count("available") == 2
