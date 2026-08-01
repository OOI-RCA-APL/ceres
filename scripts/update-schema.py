#!/usr/bin/env uv run

"""Record the schema each backend's migrations build, for `tests/test_schema_drift.py`.

Run after any migration change, the same way coverage is regenerated after a test change.
The diff is the point: it shows what the migration did to the schema, on every backend, in
the review rather than afterwards.

PostgreSQL needs a reachable test server and Turso needs the optional `pyturso` package, so
a backend that cannot be reached is left as it was rather than recorded empty. `--check`
fails on one it could not reach as well as on one that has drifted, because a check that
skipped a backend has not checked it and reporting otherwise is how a stale file survives.
"""

import asyncio
import sys
from typing import Any

# ruff: disable[T201] # Allow print statements.
from ceres.config import SQLiteDatabaseConfig, TursoDatabaseConfig
from ceres.database import Database
from tests import introspection, postgres

_EXPECTED_TABLES = {"migrations", "users", "workspaces", "messages", "particles"}
"""Tables any migrated database holds, as a floor under what is worth recording.

Nobody reads the update path as closely as the check path, so a half-applied migration or a
misconfigured backend could otherwise write a truncated file that every later run passes
against. This is a sanity floor, not a schema, which is what the recorded file is for.
"""


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
        described = await introspection.describe(database)
        missing = sorted(_EXPECTED_TABLES - set(described))
        if missing:
            raise RuntimeError(f"the migrated database is missing {missing}, nothing was recorded")

        return introspection.render(described)
    finally:
        await database.dispose()


async def main() -> int:
    check = "--check" in sys.argv
    stale: list[str] = []
    unreached: list[str] = []
    introspection.SCHEMA_DIRECTORY.mkdir(exist_ok=True)

    for backend in ("sqlite", "turso", "postgres"):
        try:
            recorded = await _record(backend)
        except Exception as error:
            unreached.append(backend)
            print(f"{backend}: not reached, {error}")
            continue

        path = introspection.path_for(backend)
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

    if unreached and check:
        print(f"\n{', '.join(unreached)} could not be reached, so nothing checked them.")

    return 1 if stale or (unreached and check) else 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    finally:
        postgres.drop_schemas()
