"""Read a database's schema back out of it, in a form worth committing and diffing.

The migrations are the only description of the schema, so nothing compares them against a
second one. What this gives instead is a recorded one: the schema each backend ends up with
is dumped to `tests/schema/<backend>.json` and checked in, so a migration that changes a
column's type, drops an index, or diverges between backends shows the change as a diff in
review rather than as a surprise in production.

What that catches is unintended change. A migration that was wrong from the start would have
its wrongness recorded here and pass, which is the trade for an expectation nobody has to
hand-maintain.

Backends do not report themselves the same way, so neither do their files. SQLite and Turso
keep the statement that created each table, which carries the checks and uniques their
pragmas will not report, while PostgreSQL has no stored statement and its constraints are
read from the catalog instead.
"""

import json
from pathlib import Path
from typing import Any

from ceres.database import Database, DatabaseType

SCHEMA_DIRECTORY = Path(__file__).parent / "schema"
"""Where the recorded schemas live, one file per backend."""

_SCHEMA_PLACEHOLDER = "<schema>"
"""Stands in for a PostgreSQL schema name, which a test run picks at random."""


def path_for(backend: str) -> Path:
    """The recorded schema file for one backend."""
    return SCHEMA_DIRECTORY / f"{backend}.json"


def render(schema: dict[str, Any]) -> str:
    """Serialize a schema the way the recorded files hold it."""
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


async def describe(database: Database) -> dict[str, Any]:
    """Read back every table the database holds, keyed by name.

    Each table carries its columns in declaration order, its keys, and its indexes. A
    database this reads has to have been migrated already, since an empty one describes
    nothing rather than failing.
    """
    if database.type is DatabaseType.POSTGRES:
        return await _describe_postgres(database)

    return await _describe_sqlite(database)


async def _fetch(database: Database, sql: str) -> list[dict[str, Any]]:
    """Run a read through the store, which is the one connection to the database."""
    return await database._store().fetch(sql, [])


def _squeeze(sql: str | None) -> str | None:
    """Collapse a stored statement's whitespace, which is formatting rather than schema."""
    return " ".join(sql.split()) if sql else None


async def _describe_sqlite(database: Database) -> dict[str, Any]:
    """Describe a SQLite or Turso database from its master table and pragmas.

    The stored statement is kept alongside the pragmas because it is the only place a check
    constraint appears, SQLite offering no pragma that reports one. Turso rewrites the
    statement it stores rather than echoing it back, so the two backends record the same
    schema in different words, which is why they get a file each.
    """
    tables = await _fetch(
        database,
        "SELECT name, sql FROM sqlite_master "
        "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name",
    )
    indexes = await _fetch(
        database,
        "SELECT name, tbl_name, sql FROM sqlite_master "
        "WHERE type = 'index' AND name NOT LIKE 'sqlite_%' ORDER BY name",
    )

    described: dict[str, Any] = {}
    for table in tables:
        name = str(table["name"])
        # The name comes from the master table, so it is one this database created rather
        # than anything a caller chose.
        columns = await _fetch(database, f"SELECT * FROM pragma_table_info('{name}')")
        keys = await _fetch(database, f"SELECT * FROM pragma_foreign_key_list('{name}')")
        described[name] = {
            "columns": [
                {
                    "name": str(column["name"]),
                    "type": str(column["type"]),
                    "nullable": not column["notnull"],
                    "default": _squeeze(column["dflt_value"]),
                }
                for column in columns
            ],
            "primary_key": [str(column["name"]) for column in columns if column["pk"]],
            "foreign_keys": sorted(
                f"{key['from']} -> {key['table']}.{key['to']} "
                f"on_delete={key['on_delete']} on_update={key['on_update']}"
                for key in keys
            ),
            "indexes": sorted(
                " ".join(str(index["sql"]).split())
                for index in indexes
                if index["tbl_name"] == name and index["sql"]
            ),
            "statement": _squeeze(str(table["sql"])),
        }

    return described


async def _describe_postgres(database: Database) -> dict[str, Any]:
    """Describe a PostgreSQL database from its catalog.

    Scoped to the search path rather than to every schema on the server, because what a
    query meets is what this database resolves names against, and a test server hands each
    database a schema of its own. That schema's name is picked at random per run, so it is
    replaced wherever it appears rather than recorded.
    """
    rows = await _fetch(database, "SELECT current_schema() AS name")
    schema = str(rows[0]["name"])

    def unqualified(text: str) -> str:
        return " ".join(text.split()).replace(f"{schema}.", "").replace(f'"{schema}".', "")

    columns = await _fetch(
        database,
        "SELECT table_name, column_name, data_type, is_nullable, column_default "
        "FROM information_schema.columns "
        "WHERE table_schema = ANY(current_schemas(false)) "
        "ORDER BY table_name, ordinal_position",
    )
    indexes = await _fetch(
        database,
        "SELECT tablename, indexdef FROM pg_indexes "
        "WHERE schemaname = ANY(current_schemas(false)) ORDER BY indexname",
    )
    constraints = await _fetch(
        database,
        # The definition says what kind of constraint it is, so `contype` would only
        # repeat it, in a one-character type nothing here decodes.
        'SELECT c.relname AS "table", pg_get_constraintdef(con.oid) AS definition '
        "FROM pg_constraint con "
        "JOIN pg_class c ON c.oid = con.conrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = ANY(current_schemas(false)) "
        "ORDER BY c.relname, con.conname",
    )

    described: dict[str, Any] = {}
    for column in columns:
        table = described.setdefault(
            str(column["table_name"]),
            {"columns": [], "constraints": [], "indexes": []},
        )
        table["columns"].append(
            {
                "name": str(column["column_name"]),
                "type": str(column["data_type"]),
                "nullable": column["is_nullable"] == "YES",
                "default": (
                    unqualified(str(column["column_default"]))
                    if column["column_default"] is not None
                    else None
                ),
            }
        )

    for constraint in constraints:
        table = described.get(str(constraint["table"]))
        if table is not None:
            table["constraints"].append(unqualified(str(constraint["definition"])))

    for index in indexes:
        table = described.get(str(index["tablename"]))
        if table is not None:
            table["indexes"].append(unqualified(str(index["indexdef"])))

    for table in described.values():
        table["constraints"].sort()
        table["indexes"].sort()

    return described
