from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from data_platform.database.models import Base, GeographyLineString, GeographyPoint
from sqlalchemy import Table, Text, engine_from_config, event, pool, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.sql.sqltypes import NullType

config = context.config
database_url = os.environ.get("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


@event.listens_for(Table, "column_reflect")
def reflect_postgis_geography(inspector, table, column_info) -> None:
    """Restore geography subtype/SRID metadata PostgreSQL's dialect omits."""
    if not isinstance(column_info["type"], NullType):
        return
    statement = text(
        "SELECT format_type(attribute.atttypid, attribute.atttypmod) "
        "FROM pg_attribute AS attribute "
        "JOIN pg_class AS relation ON relation.oid=attribute.attrelid "
        "JOIN pg_namespace AS namespace ON namespace.oid=relation.relnamespace "
        "WHERE namespace.nspname=COALESCE(:schema_name, current_schema()) "
        "AND relation.relname=:table_name AND attribute.attname=:column_name "
        "AND attribute.attnum > 0 AND NOT attribute.attisdropped"
    )
    parameters = {
        "schema_name": table.schema,
        "table_name": table.name,
        "column_name": column_info["name"],
    }
    bind = inspector.bind
    if isinstance(bind, Connection):
        database_type = bind.execute(statement, parameters).scalar_one_or_none()
    elif isinstance(bind, Engine):
        with bind.connect() as connection:
            database_type = connection.execute(statement, parameters).scalar_one_or_none()
    else:
        return

    if database_type == "geography(Point,4326)":
        column_info["type"] = GeographyPoint()
    elif database_type == "geography(LineString,4326)":
        column_info["type"] = GeographyLineString()
    elif database_type is not None:
        # Do not let an unsupported or changed PostGIS type disappear as NullType.
        column_info["type"] = Text()


def include_object(obj, name, type_, reflected, compare_to):
    """Compare mapped tables while leaving migration-managed tables to raw SQL.

    Partition children, extension tables, and support tables created directly by
    migrations are intentionally not mapped as ORM entities. Their parent or
    migration tests define their schema; including them here makes every
    autogenerate check propose dropping those live structures.
    """
    if type_ == "table" and reflected and compare_to is None:
        return False
    if type_ == "index" and reflected and compare_to is None:
        table = getattr(obj, "table", None)
        if table is not None and table.name not in target_metadata.tables:
            return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
