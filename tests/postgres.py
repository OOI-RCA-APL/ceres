"""Run the suite against a real PostgreSQL server instead of the default SQLite database.

Production runs on PostgreSQL while the suite defaults to SQLite, so a query that only one backend
accepts can pass every test. Setting `CERES_TEST_DATABASE=postgres` redirects every unconfigured
`Database`, and therefore every unconfigured `Engine`, at PostgreSQL without a single test changing.

Isolation matches what SQLite gives for free. Each `Database` gets a private schema, and its
connections put that schema first on the search path, so the tables one test creates are invisible
to the next. `public` stays on the path behind it, because extensions and their operator classes,
such as `pg_trgm` and `gin_trgm_ops`, are installed once per database rather than per schema.

Schemas are recycled instead of accumulating. Handing one out is a list pop, and only a run that
exhausts the pool pays a round trip to drop and recreate the schemas that earlier tests finished
with, which keeps the catalog to a fixed size no matter how long the run is.
"""

import asyncio
import os
from collections.abc import Coroutine
from threading import Thread
from typing import Any

from pydantic import SecretStr
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from ceres.config import PostgresDatabaseConfig
from ceres.data import uuid4

POSTGRES_URL = os.environ.get(
    "CERES_TEST_POSTGRES_URL", "postgresql+asyncpg://ceres:ceres@localhost:5432/ceres_test"
)
"""Server the PostgreSQL tests connect to. Override to point at a different instance.

The default names a database of its own rather than the one a local deployment uses, because the
suite drops schemas and deletes rows wholesale and must never be pointed at real data by accident.
"""


def is_enabled() -> bool:
    """Report whether the suite was asked to run against PostgreSQL."""
    return os.environ.get("CERES_TEST_DATABASE", "sqlite").lower() == "postgres"


_BATCH = 64
"""Schemas created per round trip. Also the ceiling on how many exist at once."""

_available: list[str] = []
"""Schemas ready to hand out."""

_dirty: list[str] = []
"""Schemas a finished test left behind, recycled once the pool runs dry."""

_taken: list[str] = []
"""Schemas handed out during the current test."""


def _run(coroutine: Coroutine[Any, Any, None]) -> None:
    """Run a coroutine to completion on a loop of its own.

    Schemas are claimed from `Database.__new__`, which is synchronous and is usually reached from
    inside a test's own event loop, so the work goes to a separate thread rather than trying to
    nest one loop inside another.
    """
    failures: list[BaseException] = []

    def target() -> None:
        try:
            asyncio.run(coroutine)
        except BaseException as exception:
            failures.append(exception)

    thread = Thread(target=target)
    thread.start()
    thread.join()

    if failures:
        raise failures[0]


async def _execute(statements: list[str]) -> None:
    engine = create_async_engine(POSTGRES_URL, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            for statement in statements:
                await connection.execute(text(statement))
    finally:
        await engine.dispose()


def prepare() -> None:
    """Install the shared extensions once, before any schema is handed out.

    `PostgresDatabase.ddl` asks for `pg_trgm` without naming a schema, so a migration run inside a
    throwaway schema would install it there and take `gin_trgm_ops` down with that schema when it
    is recycled. Putting the extension in `public` first makes every later `IF NOT EXISTS` a no-op
    and keeps the operator classes resolvable for the whole run.

    Raises:
        RuntimeError: If the server is unreachable or the database does not exist, carrying the
            commands that create it. The role Ceres connects as cannot create a database itself.
    """
    try:
        _run(_execute(["CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public"]))
        _assert_byte_collation()
    except RuntimeError:
        raise
    except Exception as exception:
        raise RuntimeError(
            f"CERES_TEST_DATABASE=postgres, but {POSTGRES_URL} cannot be prepared. Start a "
            "PostgreSQL server and create the test database as a superuser:\n"
            '  psql postgres -c "CREATE DATABASE ceres_test OWNER ceres"\n'
            "Point CERES_TEST_POSTGRES_URL elsewhere to use a different server or database."
        ) from exception


def _assert_byte_collation() -> None:
    """Fail early when the test database orders text differently than SQLite does.

    Ordering of text columns follows the database's collation, and the suite asserts specific
    orderings. `C` sorts by byte, which matches SQLite, while a locale such as `en_US.utf8` orders
    case-insensitively and quietly fails a handful of filter tests instead.

    Raises:
        RuntimeError: If the database was created with a collation other than `C`.
    """
    collations: list[str] = []

    async def read() -> None:
        engine = create_async_engine(POSTGRES_URL, poolclass=NullPool)
        try:
            async with engine.connect() as connection:
                result = await connection.execute(
                    text("SELECT datcollate FROM pg_database WHERE datname = current_database()")
                )
                collations.extend(row[0] for row in result)
        finally:
            await engine.dispose()

    _run(read())

    if collations and not collations[0].startswith("C"):
        raise RuntimeError(
            f"{POSTGRES_URL} was created with the '{collations[0]}' collation, which orders text "
            "differently than SQLite and fails the ordering assertions. Recreate it as a "
            'superuser with: psql postgres -c "CREATE DATABASE ceres_test OWNER ceres '
            "TEMPLATE template0 LC_COLLATE 'C' LC_CTYPE 'C'\""
        )


def _refill() -> None:
    """Restock the pool, recycling finished schemas before creating new ones."""
    if _dirty:
        recycled = list(_dirty)
        _dirty.clear()
        _run(
            _execute(
                [
                    statement
                    for schema in recycled
                    for statement in (
                        f"DROP SCHEMA IF EXISTS {schema} CASCADE",
                        f"CREATE SCHEMA {schema}",
                    )
                ]
            )
        )
        _available.extend(recycled)
        return

    created = [f"ceres_test_{uuid4().hex}" for _ in range(_BATCH)]
    _run(_execute([f"CREATE SCHEMA {schema}" for schema in created]))
    _available.extend(created)


def take_schema() -> str:
    """Claim a private, empty schema for one `Database`."""
    if not _available:
        _refill()

    schema = _available.pop()
    _taken.append(schema)
    return schema


def release_schemas() -> None:
    """Mark every schema the finished test claimed as reusable."""
    _dirty.extend(_taken)
    _taken.clear()


def drop_schemas() -> None:
    """Drop every schema the run created, leaving the server as it was found."""
    schemas = _available + _dirty + _taken
    _available.clear()
    _dirty.clear()
    _taken.clear()

    if schemas:
        _run(_execute([f"DROP SCHEMA IF EXISTS {schema} CASCADE" for schema in schemas]))


def database_config() -> PostgresDatabaseConfig:
    """Build a config for a private schema on the test server.

    `NullPool` keeps the connection count down. Nothing disposes the databases a test creates, so a
    pooled engine would hold its connections open until the process exited and a full run would
    exhaust the server long before it finished.
    """
    url = make_url(POSTGRES_URL)
    schema = take_schema()

    return PostgresDatabaseConfig(
        host=url.host or "localhost",
        port=url.port,
        database=url.database or "ceres_test",
        user=url.username or "ceres",
        password=SecretStr(url.password) if url.password is not None else None,
        engine={
            "poolclass": NullPool,
            "connect_args": {"server_settings": {"search_path": f"{schema},public"}},
        },
    )
