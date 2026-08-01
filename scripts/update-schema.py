#!/usr/bin/env uv run

"""Record the schema each backend's migrations build, for `tests/test_schema_drift.py`.

Run after any migration change, the same way coverage is regenerated after a test change.
The diff is the point: it shows what the migration did to the schema, on every backend, in
the review rather than afterwards.

PostgreSQL needs a reachable test server and Turso needs the optional `pyturso` package, so
a backend that cannot be reached is reported and left as it was rather than recorded empty.
"""

import asyncio
import sys
from typing import Any

# ruff: disable[T201] # Allow print statements.
from ceres.config import SQLiteDatabaseConfig, TursoDatabaseConfig
from ceres.database import Database
from tests import postgres, schema


def _config(backend: str) -> Any:
    """Build a configuration for one backend, reaching its server if it needs one."""
    match backend:
        case "sqlite":
            return SQLiteDatabaseConfig()
        case "turso":
            return TursoDatabaseConfig()
        case _:
            postgres.prepare()
            return postgres.database_config()


async def _record(backend: str) -> str:
    """Migrate a throwaway database on `backend` and render what it built."""
    database = Database(_config(backend))
    try:
        await database.migrate()
        return schema.render(await schema.describe(database))
    finally:
        await database.dispose()


async def main() -> int:
    check = "--check" in sys.argv
    stale: list[str] = []
    schema.SCHEMA_DIRECTORY.mkdir(exist_ok=True)

    for backend in ("sqlite", "turso", "postgres"):
        try:
            recorded = await _record(backend)
        except Exception as error:
            print(f"{backend}: skipped, {error}")
            continue

        path = schema.path_for(backend)
        if check:
            if not path.exists() or path.read_text() != recorded:
                stale.append(backend)
                print(f"{backend}: the recorded schema is out of date")
            else:
                print(f"{backend}: up to date")

            continue

        changed = not path.exists() or path.read_text() != recorded
        path.write_text(recorded)
        print(f"{backend}: {'updated' if changed else 'unchanged'} {path}")

    if stale:
        print("\nRun 'make schema' to record the schema the migrations now build.")
        return 1

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    finally:
        postgres.drop_schemas()
