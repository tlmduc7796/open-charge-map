"""Shared helpers for the SQL layer: manifest (tables.toml) and psql access via docker compose."""

from __future__ import annotations

import re
import subprocess
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = PACKAGE_ROOT / "schema"
DATA_DIR = PACKAGE_ROOT / "data"
BULK_DIR = PACKAGE_ROOT / "bulk"
MANIFEST_PATH = PACKAGE_ROOT / "tables.toml"
DB_USER = "smart_ev"
AUDIT_COLUMNS = ("created_at", "updated_at", "ingested_at")


@dataclass(frozen=True)
class Table:
    name: str
    group: str
    rows: int
    load: str
    order_by: str | None = None
    keep_columns: tuple[str, ...] = ()

    @property
    def schema_path(self) -> Path:
        return SCHEMA_DIR / self.group / f"{self.name}.sql"

    @property
    def data_path(self) -> Path | None:
        if self.load == "sql":
            return DATA_DIR / self.group / f"{self.name}.sql"
        if self.load == "csv":
            return BULK_DIR / f"{self.name}.csv"
        return None


@dataclass(frozen=True)
class Manifest:
    base: tuple[str, ...]
    views: tuple[str, ...]
    groups: dict[str, str]
    tables: tuple[Table, ...] = field(default_factory=tuple)

    def schema_files(self) -> list[Path]:
        names = [*self.base]
        paths = [SCHEMA_DIR / f"{name}.sql" for name in names]
        paths += [table.schema_path for table in self.tables]
        paths += [SCHEMA_DIR / f"{name}.sql" for name in self.views]
        return paths

    def data_files(self) -> list[Table]:
        return [table for table in self.tables if table.data_path is not None]


def load_manifest(path: Path = MANIFEST_PATH) -> Manifest:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    tables = tuple(
        Table(
            name=item["name"],
            group=item["group"],
            rows=int(item["rows"]),
            load=item.get("load", "sql"),
            order_by=item.get("order_by"),
            keep_columns=tuple(item.get("keep_columns", ())),
        )
        for item in raw["table"]
    )
    manifest = Manifest(
        base=tuple(raw["base"]),
        views=tuple(raw["views"]),
        groups=dict(raw["groups"]),
        tables=tables,
    )
    names = [table.name for table in tables]
    if len(names) != len(set(names)):
        raise ValueError("tables.toml: duplicate table name")
    unknown = {table.group for table in tables} - set(manifest.groups)
    if unknown:
        raise ValueError(f"tables.toml: groups without description: {sorted(unknown)}")
    bad = [table.name for table in tables if table.load not in {"sql", "csv", "none"}]
    if bad:
        raise ValueError(f"tables.toml: invalid load for {bad}")
    return manifest


# --------------------------------------------------------------------------- docker / psql
def exec_in_postgres(*args: str, stdin: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["docker", "compose", "exec", "-T", "-e", "PGTZ=UTC", "postgres", *args],
        cwd=PACKAGE_ROOT,
        input=stdin,
        capture_output=True,
    )


def decode_text(data: bytes) -> str:
    return data.decode("utf-8", "replace").strip()


def check_name(name: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise ValueError("database name may contain only letters, digits and underscores")


def wait_for_postgres() -> None:
    subprocess.run(["docker", "compose", "up", "-d", "postgres"], cwd=PACKAGE_ROOT, check=True,
                   capture_output=True)
    for _ in range(60):
        if exec_in_postgres("pg_isready", "-U", DB_USER, "-d", "postgres").returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError("PostgreSQL did not become ready within 60 seconds")


def database_exists(name: str) -> bool:
    check_name(name)
    return scalar("postgres", f"SELECT 1 FROM pg_database WHERE datname = '{name}'") == "1"


def create_database(name: str) -> None:
    check_name(name)
    result = exec_in_postgres("createdb", "-U", DB_USER, name)
    if result.returncode != 0:
        raise RuntimeError(decode_text(result.stderr))


def drop_database(name: str) -> None:
    check_name(name)
    result = exec_in_postgres("psql", "-U", DB_USER, "-d", "postgres", "-tAc",
                   f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
    if result.returncode != 0:
        raise RuntimeError(decode_text(result.stderr))


def scalar(database: str, sql: str) -> str:
    result = exec_in_postgres("psql", "-U", DB_USER, "-d", database, "-tAc", sql)
    if result.returncode != 0:
        raise RuntimeError(decode_text(result.stderr))
    return decode_text(result.stdout)


def query_text(database: str, sql: str) -> str:
    """Run a query and return raw stdout (no trimming of inner whitespace)."""
    result = exec_in_postgres("psql", "-U", DB_USER, "-d", database, "-tAq", "-c", sql)
    if result.returncode != 0:
        raise RuntimeError(decode_text(result.stderr))
    return result.stdout.decode("utf-8")


def run_sql_file(database: str, path: Path) -> None:
    result = exec_in_postgres(
        "psql", "--quiet", "-v", "ON_ERROR_STOP=1", "--single-transaction",
        "-U", DB_USER, "-d", database, stdin=path.read_bytes(),
    )
    if result.returncode != 0:
        raise RuntimeError(_failure(path, result))


def _failure(path: Path, result: subprocess.CompletedProcess[bytes]) -> str:
    return f"{path.relative_to(PACKAGE_ROOT)} failed:\n{decode_text(result.stderr)}"


def copy_csv(database: str, table: Table, path: Path) -> None:
    data = path.read_bytes()
    header = data.split(b"\n", 1)[0].decode("utf-8").strip()
    columns = ", ".join(f'"{name}"' for name in header.split(","))
    result = exec_in_postgres(
        "psql", "--quiet", "-v", "ON_ERROR_STOP=1", "--single-transaction",
        "-U", DB_USER, "-d", database, "-c",
        f"COPY public.{table.name} ({columns}) FROM STDIN WITH (FORMAT csv, HEADER true)",
        stdin=data,
    )
    if result.returncode != 0:
        raise RuntimeError(_failure(path, result))


def apply_schema(database: str, manifest: Manifest, *, log=print) -> None:
    for path in manifest.schema_files():
        run_sql_file(database, path)
        log(f"  ok  {path.relative_to(PACKAGE_ROOT)}")


def apply_data(database: str, manifest: Manifest, *, log=print) -> None:
    for table in manifest.data_files():
        path = table.data_path
        assert path is not None
        if table.load == "csv":
            copy_csv(database, table, path)
        else:
            run_sql_file(database, path)
        log(f"  ok  {path.relative_to(PACKAGE_ROOT)}")


def row_counts(database: str, manifest: Manifest) -> dict[str, int]:
    return {
        table.name: int(scalar(database, f"SELECT count(*) FROM public.{table.name}"))
        for table in manifest.tables
    }
