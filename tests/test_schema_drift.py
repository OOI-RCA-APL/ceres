"""Assert that the migrations create the schema the native layer reads and writes.

Tables are created by the SQL in `ceres/database/migrations`, and every query, decode, and
write is built from the entity structs in `ceres-entities`. They are two independent
descriptions of one schema, and nothing else checks that they agree, so a column can be
renamed by a migration while the decoders go on naming the old one. That is not
hypothetical. Migration 5 declared `owner_id` as `CHAR(32)` where the models had `uuid`,
which PostgreSQL rejects against its `uuid` primary keys, and it was found only because a
test happened to replay migrations against a real server.

Nothing here would fail a build. A column the migrations do not create surfaces as a decode
error on a live query, on whichever backend the deployment happens to run, which is why this
compares the two descriptions on all three.
"""

from typing import Any

import pytest
from ceres_core import stored_columns

from ceres.database import Database, DatabaseType

pytestmark = pytest.mark.databases()
"""Every backend, since drift between the migrations and the models is backend specific."""

_BOOKKEEPING_TABLES = {"migrations"}
"""Tables owned by the migration runner rather than by an entity, so absent from the models."""

_TYPES: dict[str, dict[str, str]] = {
    "sqlite": {
        "uuid": "CHAR(32)",
        "address": "TEXT",
        "timestamp": "TIMESTAMP",
        "text": "TEXT",
        "email": "TEXT",
        "values": "VARCHAR",
        "level": "VARCHAR",
        "bytes": "BLOB",
        "json": "JSON",
        "boolean": "BOOLEAN",
    },
    "postgres": {
        "uuid": "uuid",
        "address": "text",
        "timestamp": "timestamp with time zone",
        "text": "text",
        "email": "text",
        "values": "character varying",
        "level": "character varying",
        "bytes": "bytea",
        "json": "json",
        "boolean": "boolean",
    },
}
"""The column type each family decodes from, on each backend."""

_TYPES["turso"] = {
    **_TYPES["sqlite"],
    # Turso echoes a declared type back without its length, so the same column SQLite
    # reports as `CHAR(32)` reads as `CHAR` here. The width goes unchecked on this backend
    # rather than unchecked everywhere, which is the most either can say for itself.
    "uuid": "CHAR",
}


def _declared() -> dict[str, dict[str, str]]:
    """Return `{table: {column: family}}` for everything the native layer names."""
    return {table: dict(columns) for table, columns in stored_columns()}


async def _migrated(database: Database) -> dict[str, dict[str, str]]:
    """Return `{table: {column: type}}` for the schema the migrations built.

    Read through the store rather than through a schema library, because the store is the
    one connection to the database and what it reports is what a query will meet.
    """
    if database.type is DatabaseType.POSTGRES:
        # Scoped to the search path rather than to every schema on the server, because
        # what a query meets is what this database resolves names against. A test server
        # hands each database a schema of its own, so anything wider would describe other
        # databases' tables as though they were this one's.
        sql = (
            "SELECT table_name AS name, column_name AS column, data_type AS type "
            "FROM information_schema.columns "
            "WHERE table_schema = ANY(current_schemas(false))"
        )
    else:
        sql = (
            "SELECT m.name AS name, i.name AS column, i.type AS type "
            "FROM sqlite_master m JOIN pragma_table_info(m.name) i "
            "WHERE m.type = 'table' AND m.name NOT LIKE 'sqlite_%'"
        )

    rows: list[dict[str, Any]] = await database._store().fetch(sql, [])
    described: dict[str, dict[str, str]] = {}
    for row in rows:
        name = str(row["name"])
        if name in _BOOKKEEPING_TABLES:
            continue

        described.setdefault(name, {})[str(row["column"])] = str(row["type"])

    return described


async def _built() -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]], str]:
    """Migrate a database and describe both sides of the comparison against it."""
    database = Database()
    try:
        await database.migrate()
        return _declared(), await _migrated(database), database.type.value
    finally:
        await database.dispose()


async def test_the_migrations_create_every_table_the_models_read() -> None:
    """A table the models name and no migration creates fails every query against it."""
    declared, migrated, _ = await _built()

    assert set(declared) == set(migrated), (
        f"only the models name {sorted(set(declared) - set(migrated))}, "
        f"only migrations create {sorted(set(migrated) - set(declared))}"
    )


async def test_the_migrations_create_every_column_the_models_read() -> None:
    """A column present in one and not the other breaks decoding a migrated database.

    Compared in both directions. A column the models name and the migrations skip fails a
    decode, and one the migrations create and the models never name is a column no write
    ever fills, which its first `NOT NULL` turns into a failing insert.

    The second direction assumes the database holds nothing but Ceres's own tables, which
    is true of one these tests built and of a deployment that gave Ceres a database of its
    own. An operator sharing a schema with tables of their own would see it fail on theirs.
    """
    declared, migrated, _ = await _built()

    mismatches: list[str] = []
    for table in sorted(set(declared) & set(migrated)):
        missing = sorted(set(declared[table]) - set(migrated[table]))
        extra = sorted(set(migrated[table]) - set(declared[table]))
        if missing or extra:
            mismatches.append(
                f"{table}: only the models name {missing}, only migrations create {extra}"
            )

    assert not mismatches, "the migrations and the models disagree:\n  " + "\n  ".join(mismatches)


async def test_the_migrations_create_every_column_as_the_type_its_family_decodes() -> None:
    """The `CHAR(32)` against `uuid` mismatch is exactly this assertion failing."""
    declared, migrated, backend = await _built()
    expected = _TYPES[backend]

    mismatches: list[str] = []
    for table in sorted(set(declared) & set(migrated)):
        for column in sorted(set(declared[table]) & set(migrated[table])):
            family = declared[table][column]
            if migrated[table][column] != expected[family]:
                mismatches.append(
                    f"{table}.{column}: the {family} family decodes {expected[family]!r}, "
                    f"the migrations create {migrated[table][column]!r}"
                )

    assert not mismatches, "column types disagree:\n  " + "\n  ".join(mismatches)


async def test_the_ddl_an_operator_is_handed_builds_the_schema_the_migrations_build() -> None:
    """`ceres database ddl` prints scripts that create the same schema, run in order.

    The command exists so an operator can read or replay what initializes a database, so
    what it prints has to actually build one. PostgreSQL is the case worth having, its
    baseline carrying a `$$`-quoted function body that only survives being handed over as
    one whole script.
    """
    migrated = Database()
    applied = Database()
    try:
        await migrated.migrate()
        for script in applied.ddl:
            await applied._store().execute_script(script)

        assert await _migrated(applied) == await _migrated(migrated)
    finally:
        await migrated.dispose()
        await applied.dispose()


def test_every_family_the_models_use_has_a_type_on_every_backend() -> None:
    """A family nobody mapped would skip the type check rather than fail it."""
    families = {family for columns in _declared().values() for family in columns.values()}
    for backend, mapping in _TYPES.items():
        assert families <= set(mapping), (
            f"{backend} has no column type for {sorted(families - set(mapping))}"
        )
