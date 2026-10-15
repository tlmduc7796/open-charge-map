"""Create the demo database from the SQL layer: schema/*.sql, data/*.sql and bulk/*.csv.

Order and expected row counts come from tables.toml. The target database must not be
initialized yet (no `stations` table); to reload data into an existing schema use
`apply_sql.py --data-only` on empty tables, or drop the database first.

Usage (from `database/`, Docker running):
    python scripts\\bootstrap_database.py [--database-name smart_ev_data]
"""

from __future__ import annotations

import argparse

import _dbtools as db


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database-name", default="smart_ev_data")
    args = parser.parse_args()

    db.check_name(args.database_name)
    manifest = db.load_manifest()
    problems = [
        f"missing {path.relative_to(db.PACKAGE_ROOT)}"
        for path in [*manifest.schema_files(),
                     *(t.data_path for t in manifest.tables if t.data_path is not None)]
        if not path.is_file()
    ]
    if problems:
        raise FileNotFoundError("; ".join(problems))

    db.wait_for_postgres()
    if not db.database_exists(args.database_name):
        db.create_database(args.database_name)
    elif db.scalar(args.database_name, "SELECT to_regclass('public.stations')"):
        raise RuntimeError(
            f"Database {args.database_name} is already initialized (table stations exists). "
            "Drop it first, or use apply_sql.py --data-only on empty tables."
        )

    print(f"Schema -> {args.database_name}")
    db.apply_schema(args.database_name, manifest)
    print(f"Data -> {args.database_name}")
    db.apply_data(args.database_name, manifest)

    counts = db.row_counts(args.database_name, manifest)
    wrong = {
        table.name: {"expected": table.rows, "actual": counts[table.name]}
        for table in manifest.tables
        if counts[table.name] != table.rows
    }
    if wrong:
        raise RuntimeError(f"loaded row counts do not match tables.toml: {wrong}")

    print(
        "Database bootstrap complete: "
        f"{counts['stations']} stations, {counts['ports']} ports, "
        f"{counts['vehicle_models']} vehicles, "
        f"{counts['predictions']} prediction slots"
    )


if __name__ == "__main__":
    main()
