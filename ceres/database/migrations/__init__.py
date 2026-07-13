"""Ordered schema migrations applied by `Database.migrate`.

Every migration is a plain SQL script file in this directory, named
`<id>-<name>.sql` for a script shared across dialects, or `<id>-<name>.sqlite.sql` /
`<id>-<name>.postgres.sql` when the SQL differs by backend. `load_migrations` scans the
directory into the `MIGRATIONS` registry at import time.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "MIGRATIONS",
    "Migration",
    "load_migrations",
]

_FILENAME_PATTERN = re.compile(
    r"^(?P<id>\d+)-(?P<name>[a-z0-9-]+?)(?:\.(?P<dialect>sqlite|postgres))?\.sql$"
)

_DIALECT_KEYS = {"sqlite": "sqlite", "postgres": "postgresql"}
"""Map a filename dialect token to the dialect key used in `Migration.scripts`."""


@dataclass(frozen=True, kw_only=True)
class Migration:
    """A single ordered schema migration backed by one or more SQL script files."""

    id: int
    """Unique sequential identifier parsed from the filename prefix."""
    name: str
    """Kebab-case name parsed from the filename (e.g. `init`)."""
    description: str
    """Human-readable form of `name` (e.g. `Init`)."""
    scripts: Mapping[str | None, Path]
    """SQL script paths keyed by dialect (`sqlite`/`postgresql`), `None` for shared."""

    def script_for(self, dialect: str) -> str | None:
        """Return the SQL text for `dialect`, or `None` when this migration has no script
        for it (a recorded no-op).

        Args:
            dialect: Dialect key to look up, e.g. `sqlite`, `postgres`, or `postgresql`.
                Normalized against `_DIALECT_KEYS` so callers can pass either the SQLAlchemy
                dialect name or the `DatabaseType` value.

        Returns:
            The SQL script text, or `None` if this migration has no script for `dialect`.
        """
        shared = self.scripts.get(None)
        if shared is not None:
            return shared.read_text()

        path = self.scripts.get(_DIALECT_KEYS.get(dialect, dialect))
        return path.read_text() if path is not None else None


def load_migrations(directory: Path) -> list[Migration]:
    """Scan `directory` for migration SQL files and build the ordered registry.

    Args:
        directory: Directory containing `<id>-<name>.sql` and
            `<id>-<name>.<dialect>.sql` migration script files.

    Returns:
        Every migration found, sorted by `id`.

    Raises:
        ValueError: If a filename does not match the naming convention, an id is duplicated
            with conflicting names, or an id mixes shared and dialect-specific files.
    """
    names: dict[int, str] = {}
    scripts_by_id: dict[int, dict[str | None, Path]] = {}

    for path in sorted(directory.glob("*.sql")):
        match = _FILENAME_PATTERN.match(path.name)
        if match is None:
            raise ValueError(
                f"Migration filename {path.name!r} does not match the naming convention "
                "'<id>-<name>.sql' or '<id>-<name>.<sqlite|postgres>.sql'."
            )

        id = int(match.group("id"))
        name = match.group("name")
        dialect_token = match.group("dialect")
        dialect = _DIALECT_KEYS[dialect_token] if dialect_token is not None else None

        if id in names and names[id] != name:
            raise ValueError(f"Migration {id} has conflicting names: {names[id]!r} and {name!r}.")
        names[id] = name

        scripts = scripts_by_id.setdefault(id, {})
        if dialect is None and scripts:
            raise ValueError(f"Migration {id} mixes a shared script with dialect-specific scripts.")
        if dialect is not None and None in scripts:
            raise ValueError(f"Migration {id} mixes a shared script with dialect-specific scripts.")

        scripts[dialect] = path

    return [
        Migration(
            id=id,
            name=names[id],
            description=names[id].replace("-", " ").capitalize(),
            scripts=scripts_by_id[id],
        )
        for id in sorted(scripts_by_id)
    ]


MIGRATIONS: list[Migration] = load_migrations(Path(__file__).parent)
"""Every known migration, in application order."""
