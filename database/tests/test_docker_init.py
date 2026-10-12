"""Offline guards for the one-command Docker init (database/docker/), no Docker needed.

`docker/manifest-plan.awk` re-implements, for the container's shell, what `scripts/_dbtools.py`
does with tables.toml. These tests keep the two readings identical.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCKER_DIR = ROOT / "docker"
sys.path.insert(0, str(ROOT / "scripts"))

import _dbtools as dbtools  # noqa: E402

MANIFEST = dbtools.load_manifest()
AWK = shutil.which("awk")


def _plan() -> list[list[str]]:
    result = subprocess.run(
        [AWK, "-f", str(DOCKER_DIR / "manifest-plan.awk"), str(ROOT / "tables.toml")],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.split() for line in result.stdout.splitlines() if line.strip()]


@pytest.mark.skipif(AWK is None, reason="awk is not installed")
def test_awk_plan_matches_python_manifest() -> None:
    plan = _plan()
    expected = (
        [["BASE", name] for name in MANIFEST.base]
        + [
            ["TABLE", t.name, t.group, t.load, str(t.rows)]
            for t in MANIFEST.tables
        ]
        + [["VIEW", name] for name in MANIFEST.views]
    )
    assert plan == expected


def test_init_scripts_are_lf_and_ordered_after_image_scripts() -> None:
    scripts = sorted((DOCKER_DIR / "initdb").glob("*.sh"))
    assert scripts, "no init scripts found"
    names = [path.name for path in scripts]
    assert names == sorted(names)
    # The postgis image ships 10_postgis.sh; ours must not collide with or precede it.
    assert all(int(name.split("-", 1)[0]) > 10 for name in names)
    for path in [*scripts, DOCKER_DIR / "reset-entrypoint.sh", DOCKER_DIR / "manifest-plan.awk"]:
        assert b"\r" not in path.read_bytes(), f"{path.name} has CRLF line endings"


def test_compose_mounts_what_the_init_scripts_read() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    for needle in (
        "/docker-entrypoint-initdb.d",
        "/docker/reset-entrypoint.sh",
        ":/docker:ro",
        ":/db:ro",
        ":/sim:ro",
        "RESET_ON_START",
        "HISTORY_REQUIRED",
        "pg_isready -h 127.0.0.1",
    ):
        assert needle in compose, f"compose.yaml lacks {needle}"
    for script in (DOCKER_DIR / "initdb").glob("*.sh"):
        text = script.read_text(encoding="utf-8")
        for path in ("/docker/manifest-plan.awk", "/docker/sql/load_history.sql"):
            if path in text:
                assert (DOCKER_DIR / path.removeprefix("/docker/")).is_file(), path


def test_history_sql_uses_only_documented_variables() -> None:
    text = (DOCKER_DIR / "sql" / "load_history.sql").read_text(encoding="utf-8")
    assert ":'csv_path'" in text
    # The whole CSV is loaded as is: no anchoring on the machine clock, no day shift, no cut-off.
    assert "history_days" not in text and "shift_days" not in text
    assert "now()" not in text and "date_bin" not in text
    # Station status is read from the latest occupancy bucket; per-port state is not touched.
    assert "UPDATE public.port_status" not in text
    assert "session_replication_role" not in text


def test_history_csv_is_the_september_october_fixture() -> None:
    """The mounted CSV is loaded unmodified and must cover exactly 2026-09-01 .. 2026-10-31."""
    path = ROOT / "fixtures" / "simulator" / "station_occupancy_5m.csv"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "station_id,bucket_at,total_ports,operational_ports,occupied_ports"
    stamps = [line.split(",", 2)[1] for line in lines[1:]]
    assert min(stamps) == "2026-09-01T00:00:00+07:00"
    assert max(stamps) == "2026-10-31T23:55:00+07:00"
    # 61 days x 288 five-minute buckets for each of the 11 stations, no gaps.
    assert len(stamps) == 11 * 61 * 288


def test_compose_mounts_the_september_october_csv() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "./fixtures/simulator:/sim:ro" in compose
    assert "HISTORY_DAYS" not in compose
