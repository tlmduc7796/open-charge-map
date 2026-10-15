"""Build a database from schema/*.sql and load data/*.sql + bulk/*.csv in tables.toml order.

Each file runs in its own transaction, so a failure names the table. The data step needs
empty tables (the INSERTs do not upsert).

Usage (from `database/`, Docker running):
    python scripts\\apply_sql.py --database-name smart_ev_data
    python scripts\\apply_sql.py --schema-only
    python scripts\\apply_sql.py --data-only
"""

from __future__ import annotations

import argparse

import _dbtools as db


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database-name", default="smart_ev_data")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--schema-only", action="store_true")
    scope.add_argument("--data-only", action="store_true")
    args = parser.parse_args()

    db.check_name(args.database_name)
    manifest = db.load_manifest()
    db.wait_for_postgres()
    if not db.database_exists(args.database_name):
        db.create_database(args.database_name)
    if not args.data_only:
        print(f"Schema -> {args.database_name}")
        db.apply_schema(args.database_name, manifest)
    if not args.schema_only:
        print(f"Data -> {args.database_name}")
        db.apply_data(args.database_name, manifest)


if __name__ == "__main__":
    main()
