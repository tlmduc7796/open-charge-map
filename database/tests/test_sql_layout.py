"""Offline guards for the SQL layer (no Docker). `scripts/verify.py` does the live proof."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import _dbtools as dbtools  # noqa: E402

MANIFEST = dbtools.load_manifest()
TABLES = {table.name: table for table in MANIFEST.tables}
ORDER = [table.name for table in MANIFEST.tables]


def test_manifest_has_unique_tables_and_described_groups() -> None:
    assert len(ORDER) == len(set(ORDER))
    assert {table.group for table in MANIFEST.tables} <= set(MANIFEST.groups)


@pytest.mark.parametrize("name", ORDER)
def test_each_table_has_a_schema_file_that_creates_it(name: str) -> None:
    path = TABLES[name].schema_path
    assert path.is_file(), f"missing {path}"
    assert f"CREATE TABLE public.{name} (" in path.read_text(encoding="utf-8")


def test_foreign_keys_point_to_tables_applied_earlier() -> None:
    for position, name in enumerate(ORDER):
        text = TABLES[name].schema_path.read_text(encoding="utf-8")
        for target in re.findall(r"REFERENCES public\.(\w+)\(", text):
            assert target in ORDER[:position], f"{name} references {target} defined later"


def test_every_sql_file_is_declared() -> None:
    declared = {path.resolve() for path in MANIFEST.schema_files()}
    for path in dbtools.SCHEMA_DIR.rglob("*.sql"):
        assert path.resolve() in declared, f"{path} is not in tables.toml"
    data = {t.data_path.resolve() for t in MANIFEST.tables if t.data_path is not None}
    for folder, pattern in ((dbtools.DATA_DIR, "*.sql"), (dbtools.BULK_DIR, "*.csv")):
        if folder.is_dir():
            for path in folder.rglob(pattern):
                assert path.resolve() in data, f"{path} is not in tables.toml"


@pytest.mark.parametrize("name", [t.name for t in MANIFEST.data_files() if t.load == "sql"])
def test_data_files_only_insert_into_their_table(name: str) -> None:
    text = TABLES[name].data_path.read_text(encoding="utf-8")  # type: ignore[union-attr]
    body = "\n".join(line for line in text.splitlines() if not line.startswith("--")).strip()
    assert body.startswith(f"INSERT INTO public.{name} (")
    assert body.endswith(";")
    assert body.count("INSERT INTO ") == 1, "one multi-row INSERT per file"


@pytest.mark.parametrize("name", [t.name for t in MANIFEST.data_files() if t.load == "csv"])
def test_bulk_csv_has_header_and_expected_rows(name: str) -> None:
    lines = TABLES[name].data_path.read_text(encoding="utf-8").splitlines()  # type: ignore[union-attr]
    assert lines[0].split(",")[0] == "id"
    assert len(lines) - 1 == TABLES[name].rows


def test_schema_has_no_provenance_or_migration_leftovers() -> None:
    text = "\n".join(
        path.read_text(encoding="utf-8") for path in dbtools.SCHEMA_DIR.rglob("*.sql")
    )
    for forbidden in ("alembic", "provenance", "data_origin", "simulation_run_id"):
        assert forbidden not in text.lower(), forbidden
