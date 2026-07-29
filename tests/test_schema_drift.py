"""Assert that the migrations and the ORM describe the same schema.

Tables are created by the SQL in `ceres/database/migrations`, while queries are built from the
`BaseEntityRow` definitions. They are two independent descriptions of one schema, and nothing else
checks that they agree, so a column can be declared one type in the ORM and created as another by a
migration. That is not hypothetical. Migration 5 declared `owner_id` as `CHAR(32)` while the ORM
had `uuid`, which PostgreSQL rejects against its `uuid` primary keys, and it was found only because
a test happened to replay migrations against a real server.

Both schemas are built here, side by side on whichever backend the run uses, and compared.
"""

import re
from typing import Any

import pytest
from sqlalchemy import Inspector, inspect
from sqlalchemy import text as sql

from ceres.database import Database

pytestmark = pytest.mark.databases()
"""Every backend, since drift between the migrations and the ORM is backend specific."""

_BOOKKEEPING_TABLES = {"migrations"}
"""Tables owned by the migration runner rather than by an entity, so absent from the ORM."""


def _describe(connection: Any) -> dict[str, dict[str, tuple[str, bool, str | None]]]:
    """Return every table's columns as `{table: {column: (type, nullable, default)}}`."""
    inspector: Inspector = inspect(connection)
    return {
        name: {
            column["name"]: (
                str(column["type"]),
                bool(column["nullable"]),
                _normalize_default(column.get("server_default")),
            )
            for column in inspector.get_columns(name)
        }
        for name in inspector.get_table_names()
        if name not in _BOOKKEEPING_TABLES
    }


def _normalize_default(default: object) -> str | None:
    """Reduce a server default to a comparable form.

    The two sides write the same default differently. A migration's SQL is echoed back verbatim
    while the ORM's goes through SQLAlchemy, so one may carry a cast, outer parentheses, or a
    different quote style for a value that is identical.
    """
    if default is None:
        return None

    text = str(default).strip()
    text = text.split("::")[0].strip()
    while text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()

    return text.strip("'").lower()


def _normalize_check(sqltext: str) -> str:
    """Reduce a check constraint to a comparable form.

    The two sides round-trip the same predicate differently, so whitespace, quoting, outer
    parentheses, and casts are removed before comparing what it actually restricts.
    """
    text = " ".join(sqltext.split()).replace('"', "").lower()
    text = text.replace(" ", "")

    # Casts are how PostgreSQL echoes a predicate back, not part of what it restricts. The array
    # form matters as well, since one side writes `ARRAY[...]` and the other `(ARRAY[...])::text[]`.
    text = re.sub(r"::[a-z]+(\[\])?", "", text)
    while text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()

    return text


def _describe_indexes(connection: Any) -> dict[str, set[str]]:
    """Return every table's indexes in a comparable form.

    Compared by what an index does rather than by its name, since a name is chosen by whoever wrote
    the statement while the rest decides whether a query can use it. That includes the method and
    the operator class, because a trigram index quietly rebuilt as a B-tree still answers every
    query, only slowly, and nothing else would notice.

    The PostgreSQL-only keys are absent on SQLite, where both sides simply report nothing and still
    agree.
    """
    inspector: Inspector = inspect(connection)
    described: dict[str, set[str]] = {}
    for name in inspector.get_table_names():
        if name in _BOOKKEEPING_TABLES:
            continue

        entries: set[str] = set()
        for index in inspector.get_indexes(name):
            options = index.get("dialect_options") or {}
            operators = options.get("postgresql_ops") or {}
            entries.add(
                "columns="
                + ",".join(sorted(str(column) for column in index["column_names"]))
                + "|expressions="
                + ",".join(sorted(str(current) for current in index.get("expressions") or []))
                + f"|unique={index['unique']}"
                + f"|using={options.get('postgresql_using') or ''}"
                + "|ops="
                + ",".join(f"{key}:{value}" for key, value in sorted(operators.items()))
                + f"|where={options.get('postgresql_where') or ''}"
            )

        described[name] = entries

    return described


def _describe_constraints(connection: Any) -> dict[str, set[str]]:
    """Return every table's keys and unique constraints in a comparable form."""
    inspector: Inspector = inspect(connection)
    described: dict[str, set[str]] = {}
    for name in inspector.get_table_names():
        if name in _BOOKKEEPING_TABLES:
            continue

        entries: set[str] = set()
        primary = inspector.get_pk_constraint(name)
        if primary.get("constrained_columns"):
            entries.add("primary:" + ",".join(sorted(primary["constrained_columns"])))

        for key in inspector.get_foreign_keys(name):
            # The cascade behavior is part of the constraint, not decoration. Workspace ownership
            # relies on a private workspace going away with its owner, so a key created without
            # the cascade leaves rows behind that nothing will ever clean up.
            options = key.get("options") or {}
            entries.add(
                "foreign:"
                + ",".join(sorted(key["constrained_columns"]))
                + "->"
                + str(key["referred_table"])
                + "."
                + ",".join(sorted(key["referred_columns"]))
                + f" ondelete={str(options.get('ondelete') or '').upper()}"
                + f" onupdate={str(options.get('onupdate') or '').upper()}"
            )

        for check in inspector.get_check_constraints(name):
            entries.add("check:" + _normalize_check(str(check.get("sqltext", ""))))

        for unique in inspector.get_unique_constraints(name):
            entries.add("unique:" + ",".join(sorted(unique["column_names"])))

        described[name] = entries

    return described


async def _migrated(describe: Any = _describe) -> Any:
    """Build a database the way a deployment does, by running every migration."""
    database = Database()
    await database.migrate()
    async with database.engine.connect() as connection:
        return await connection.run_sync(describe)


async def _declared(describe: Any = _describe) -> Any:
    """Build a database from the ORM's own DDL, which is what queries are written against."""
    database = Database()
    async with database.engine.begin() as connection:
        for statement in database.ddl:
            await connection.execute(sql(statement))

    async with database.engine.connect() as connection:
        return await connection.run_sync(describe)


async def test_migrations_and_orm_declare_the_same_tables() -> None:
    """A table created by one and not the other means a migration was forgotten, or vice versa."""
    migrated = await _migrated()
    declared = await _declared()

    assert set(migrated) == set(declared), (
        f"only migrations create {sorted(set(migrated) - set(declared))}, "
        f"only the ORM declares {sorted(set(declared) - set(migrated))}"
    )


async def test_migrations_and_orm_declare_the_same_columns() -> None:
    """A column present in one and not the other breaks queries against a migrated database."""
    migrated = await _migrated()
    declared = await _declared()

    for table in sorted(set(migrated) & set(declared)):
        assert set(migrated[table]) == set(declared[table]), (
            f"{table}: only migrations create {sorted(set(migrated[table]) - set(declared[table]))}"
            f", only the ORM declares {sorted(set(declared[table]) - set(migrated[table]))}"
        )


async def test_migrations_and_orm_agree_on_column_types() -> None:
    """The `CHAR(32)` against `uuid` mismatch is exactly this assertion failing."""
    migrated = await _migrated()
    declared = await _declared()

    mismatches: list[str] = []
    for table in sorted(set(migrated) & set(declared)):
        for column in sorted(set(migrated[table]) & set(declared[table])):
            if migrated[table][column] != declared[table][column]:
                mismatches.append(
                    f"{table}.{column}: migrated={migrated[table][column]} "
                    f"declared={declared[table][column]}"
                )

    assert not mismatches, "migrations and the ORM disagree:\n  " + "\n  ".join(mismatches)


async def test_migrations_and_orm_agree_on_defaults() -> None:
    """A default in one and not the other silently changes what a fresh row contains."""
    migrated = await _migrated()
    declared = await _declared()

    mismatches: list[str] = []
    for table in sorted(set(migrated) & set(declared)):
        for column in sorted(set(migrated[table]) & set(declared[table])):
            left, right = migrated[table][column][2], declared[table][column][2]
            if left != right:
                mismatches.append(f"{table}.{column}: migrated={left!r} declared={right!r}")

    assert not mismatches, "defaults disagree:\n  " + "\n  ".join(mismatches)


async def test_migrations_and_orm_agree_on_indexes() -> None:
    """A missing index is invisible until a query is slow on a database nobody rebuilt.

    Compared for equality rather than for containment. Both schemas here are built from Ceres's own
    two descriptions, so anything present in one and not the other is drift by definition. Tolerating
    extra indexes would belong in a check that inspects a real deployment's database, where an
    operator may have added their own, and this is not that check.
    """
    migrated = await _migrated(_describe_indexes)
    declared = await _declared(_describe_indexes)

    mismatches: list[str] = []
    for table in sorted(set(migrated) & set(declared)):
        only_migrated = migrated[table] - declared[table]
        only_declared = declared[table] - migrated[table]
        if only_migrated or only_declared:
            mismatches.append(
                f"{table}: only migrations index {sorted(only_migrated)}, "
                f"only the ORM indexes {sorted(only_declared)}"
            )

    assert not mismatches, "indexes disagree:\n  " + "\n  ".join(mismatches)


async def test_migrations_and_orm_agree_on_constraints() -> None:
    """Keys and unique constraints are what stop bad rows, so a gap is a data integrity gap."""
    migrated = await _migrated(_describe_constraints)
    declared = await _declared(_describe_constraints)

    mismatches: list[str] = []
    for table in sorted(set(migrated) & set(declared)):
        only_migrated = migrated[table] - declared[table]
        only_declared = declared[table] - migrated[table]
        if only_migrated or only_declared:
            mismatches.append(
                f"{table}: only migrations constrain {sorted(only_migrated)}, "
                f"only the ORM constrains {sorted(only_declared)}"
            )

    assert not mismatches, "constraints disagree:\n  " + "\n  ".join(mismatches)
