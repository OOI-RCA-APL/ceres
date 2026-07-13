"""Ordered schema migrations applied by `Database.migrate`."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncConnection

__all__ = [
    "MIGRATIONS",
    "Migration",
    "migration",
]

type UpgradeFunction = Callable[[AsyncConnection], Awaitable[None]]


@dataclass(frozen=True, kw_only=True)
class Migration:
    """A single ordered schema migration."""

    id: int
    """Unique sequential identifier."""
    description: str
    """Human-readable summary of what the migration does."""
    upgrade: UpgradeFunction
    """Apply the migration's schema changes on the given connection."""


MIGRATIONS: list[Migration] = []
"""Every known migration, in application order."""


def migration(id: int, description: str) -> Callable[[UpgradeFunction], UpgradeFunction]:
    """Declare a schema migration and register it in `MIGRATIONS`.

    Args:
        id: Unique sequential identifier for the migration.
        description: Human-readable summary of what the migration does.

    Raises:
        ValueError: If a migration with the same `id` is already registered.
    """

    def decorate(upgrade: UpgradeFunction) -> UpgradeFunction:
        if any(current.id == id for current in MIGRATIONS):
            raise ValueError(f"A migration with id {id} is already registered.")

        MIGRATIONS.append(Migration(id=id, description=description, upgrade=upgrade))
        MIGRATIONS.sort(key=lambda current: current.id)
        return upgrade

    return decorate
