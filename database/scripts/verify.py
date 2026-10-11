"""Prove the SQL layer is consistent: files match tables.toml, load cleanly, counts match.

Steps, each reported PASS/FAIL (exit code 1 if any fails):
  1. tables.toml matches the files on disk (no missing or orphan schema/data/bulk files).
  2. schema/ + data/ + bulk/ apply to an empty temporary database, in tables.toml order.
  3. Row counts equal `rows` in tables.toml.
  4. Every table in the database is declared in tables.toml (and vice versa).
  5. station_status_current (the view the backend reads at startup) returns one row per
     station, so the backend readiness check will pass.

Standard library only; needs Docker running with the compose Postgres service.

Usage (from `database/`):
    python scripts\\verify.py [--keep]
"""

from __future__ import annotations

import argparse
import sys

import _dbtools as db

TEMP_DB = "smart_ev_verify"


class Report:
    def __init__(self) -> None:
        self.failed = False

    def check(self, ok: bool, label: str, detail: str = "") -> None:
        print(f"[{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            self.failed = True
            if detail:
                print("       " + detail.replace("\n", "\n       "))


def _layout_problems(manifest: db.Manifest) -> list[str]:
    problems: list[str] = []
    for path in manifest.schema_files():
        if not path.is_file():
            problems.append(f"missing {path.relative_to(db.PACKAGE_ROOT)}")
    for table in manifest.tables:
        data_path = table.data_path
        if data_path is not None and not data_path.is_file():
            problems.append(f"missing {data_path.relative_to(db.PACKAGE_ROOT)}")
        if table.load == "none" and table.rows:
            problems.append(f"{table.name}: load = none but rows = {table.rows}")
    declared = {path.resolve() for path in manifest.schema_files()}
    for path in db.SCHEMA_DIR.rglob("*.sql"):
        if path.resolve() not in declared:
            problems.append(f"orphan {path.relative_to(db.PACKAGE_ROOT)} (not in tables.toml)")
    data_declared = {t.data_path.resolve() for t in manifest.tables if t.data_path is not None}
    for folder, pattern in ((db.DATA_DIR, "*.sql"), (db.BULK_DIR, "*.csv")):
        if not folder.is_dir():
            continue
        for path in folder.rglob(pattern):
            if path.resolve() not in data_declared:
                problems.append(f"orphan {path.relative_to(db.PACKAGE_ROOT)} (not in tables.toml)")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--keep", action="store_true", help="keep the temporary database")
    args = parser.parse_args()

    report = Report()
    manifest = db.load_manifest()

    problems = _layout_problems(manifest)
    report.check(not problems, "tables.toml matches files on disk", "\n".join(problems))
    if problems:
        return 1

    db.wait_for_postgres()
    db.drop_database(TEMP_DB)
    db.create_database(TEMP_DB)
    try:
        quiet = lambda _message: None  # noqa: E731
        try:
            db.apply_schema(TEMP_DB, manifest, log=quiet)
            db.apply_data(TEMP_DB, manifest, log=quiet)
            report.check(True, "schema/ + data/ + bulk/ apply to an empty database")
        except RuntimeError as exc:
            report.check(False, "schema/ + data/ + bulk/ apply to an empty database", str(exc))
            return 1

        counts = db.row_counts(TEMP_DB, manifest)
        wrong = {
            table.name: (table.rows, counts[table.name])
            for table in manifest.tables
            if counts[table.name] != table.rows
        }
        report.check(
            not wrong,
            "row counts match tables.toml",
            "\n".join(f"{n}: expected {e}, got {g}" for n, (e, g) in wrong.items()),
        )

        existing = set(
            db.query_text(
                TEMP_DB,
                "SELECT c.relname FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace "
                "AND c.relkind IN ('r','p') AND NOT c.relispartition "
                "AND NOT EXISTS (SELECT 1 FROM pg_depend d "
                "WHERE d.objid = c.oid AND d.deptype = 'e')",
            ).split()
        )
        declared = {table.name for table in manifest.tables}
        report.check(
            existing == declared,
            "every table in the database is declared in tables.toml",
            f"undeclared: {sorted(existing - declared)}; missing: {sorted(declared - existing)}",
        )

        stations = int(db.scalar(TEMP_DB, "SELECT count(*) FROM stations"))
        rows = int(db.scalar(TEMP_DB, "SELECT count(*) FROM station_status_current"))
        report.check(
            rows == stations > 0,
            f"station_status_current has one row per station ({rows}/{stations})",
        )
    finally:
        if not args.keep:
            db.drop_database(TEMP_DB)

    print("RESULT:", "FAIL" if report.failed else "PASS")
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
