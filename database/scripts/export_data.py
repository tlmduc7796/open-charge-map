"""Write data/<group>/<table>.sql and bulk/<table>.csv from a loaded database, deterministically.

The schema is hand-written (schema/); only data is exported. Output is stable across runs so
diffs show real changes: rows follow `order_by` from tables.toml, audit columns that default
to now() are omitted (the database fills them on load), JSON is expanded for small tables.

Usage (from `database/`, Docker running, source database already loaded):
    python scripts\\export_data.py --database-name smart_ev_data
"""

from __future__ import annotations

import argparse
import json

import _dbtools as db

PRETTY_JSON_MAX_ROWS = 30
NUMERIC_TYPES = {"smallint", "integer", "bigint", "numeric", "real", "double precision"}


def _columns(database: str, table: db.Table) -> list[dict[str, str | None]]:
    out = db.query_text(
        database,
        "SELECT coalesce(jsonb_agg(jsonb_build_object("
        "'name', column_name, 'type', data_type, 'udt', udt_name, "
        "'default', column_default) ORDER BY ordinal_position), '[]') "
        "FROM information_schema.columns "
        f"WHERE table_schema = 'public' AND table_name = '{table.name}'",
    )
    columns = json.loads(out)
    if not columns:
        raise RuntimeError(f"table public.{table.name} not found in the source database")
    omit = {
        col["name"]
        for col in columns
        if col["name"] in db.AUDIT_COLUMNS
        and col["default"] is not None
        and col["name"] not in table.keep_columns
    }
    return [col for col in columns if col["name"] not in omit]


def _order_by(database: str, table: db.Table) -> str:
    if table.order_by:
        return table.order_by
    out = db.scalar(
        database,
        "SELECT string_agg('t.' || quote_ident(a.attname), ', ' ORDER BY k.ord) "
        "FROM pg_index i "
        "JOIN LATERAL unnest(i.indkey::int2[]) WITH ORDINALITY AS k(attnum, ord) ON true "
        "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum "
        f"WHERE i.indrelid = 'public.{table.name}'::regclass AND i.indisprimary",
    )
    return out or "1"


def _select_list(columns: list[dict[str, str | None]]) -> str:
    parts = []
    for col in columns:
        name = f'"{col["name"]}"'
        if col["udt"] == "geography":
            parts.append(f"ST_AsEWKT(t.{name}::geometry, 15) AS {name}")
        elif col["type"] == "jsonb":
            parts.append(f"t.{name}::text AS {name}")
        else:
            parts.append(f"t.{name}::text AS {name}")
    return ", ".join(parts)


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _literal(value: str | None, col: dict[str, str | None], pretty: bool) -> str:
    if value is None:
        return "NULL"
    kind = col["type"]
    if kind in NUMERIC_TYPES:
        return value
    if kind == "boolean":
        return value
    if col["udt"] == "geography":
        return f"ST_GeogFromText({_quote(value)})"
    if kind == "jsonb":
        if pretty and len(value) > 100:
            value = json.dumps(json.loads(value), ensure_ascii=False, indent=2)
        return _quote(value)
    return _quote(value)


def export_table(database: str, table: db.Table) -> None:
    path = table.data_path
    if path is None:
        return
    count = int(db.scalar(database, f"SELECT count(*) FROM public.{table.name}"))
    if count != table.rows:
        print(f"  !!  {table.name}: tables.toml says {table.rows} rows, database has {count}")
    if count == 0:
        path.unlink(missing_ok=True)
        return
    columns = _columns(database, table)
    order = _order_by(database, table)
    select = _select_list(columns)
    path.parent.mkdir(parents=True, exist_ok=True)

    if table.load == "csv":
        names = ", ".join(f'"{col["name"]}"' for col in columns)
        result = db.exec_in_postgres(
            "psql", "-U", db.DB_USER, "-d", database, "-q", "-c",
            f"COPY (SELECT {names} FROM public.{table.name} t ORDER BY {order}) "
            "TO STDOUT WITH (FORMAT csv, HEADER true)",
        )
        if result.returncode != 0:
            raise RuntimeError(db.decode_text(result.stderr))
        path.write_bytes(result.stdout.replace(b"\r\n", b"\n"))
        print(f"  ok  {path.relative_to(db.PACKAGE_ROOT)} ({count} rows)")
        return

    raw = db.query_text(
        database,
        "SELECT coalesce(jsonb_agg(to_jsonb(r)), '[]'::jsonb) FROM ("
        f"SELECT {select} FROM public.{table.name} t ORDER BY {order}) r",
    )
    rows = json.loads(raw)
    pretty = len(rows) <= PRETTY_JSON_MAX_ROWS
    names = [col["name"] for col in columns]
    lines = [
        f"-- {table.group}.{table.name}: {len(rows)} dòng, sắp theo order_by trong tables.toml.",
        "-- Cột kiểm toán (created_at/updated_at/ingested_at) không xuất; DB tự điền lúc nạp.",
        "",
        f"INSERT INTO public.{table.name} ({', '.join(names)}) VALUES",
    ]
    body = []
    for row in rows:
        values = [_literal(row[col["name"]], col, pretty) for col in columns]
        body.append("    (" + ", ".join(values) + ")")
    lines.append(",\n".join(body) + ";")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"  ok  {path.relative_to(db.PACKAGE_ROOT)} ({len(rows)} rows)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database-name", default="smart_ev_data")
    args = parser.parse_args()
    db.check_name(args.database_name)
    manifest = db.load_manifest()
    db.wait_for_postgres()
    print(f"Export data from {args.database_name}")
    for table in manifest.tables:
        export_table(args.database_name, table)


if __name__ == "__main__":
    main()
