from __future__ import annotations

from ..config import DatabaseConfig
from .base import DatabaseManager as DatabaseManager
from .sqlite import SQLiteDatabaseManager as SQLiteDatabaseManager


def create_database_manager(config: DatabaseConfig) -> DatabaseManager:
    if config.kind == "sqlite":
        return SQLiteDatabaseManager(config)

    raise NotImplementedError(config.kind)
