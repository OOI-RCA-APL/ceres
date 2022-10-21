from __future__ import annotations

from typing import Any

from .adapter import DatabaseAdapter


class PostgresDatabaseAdapter(DatabaseAdapter):
    def get_async_engine_url(self) -> str:
        return (
            "postgresql+psycopg://"
            + f"{self.config.user}:{self.config.password.get_secret_value()}"
            + f"@{self.config.host}:{self.config.port}/{self.config.database}"
        )

    def get_sync_engine_url(self) -> str:
        return self.get_async_engine_url()

    def get_engine_config(self) -> dict[str, Any]:
        return {
            "pool_pre_ping": True,  # Check to see if a connection has closed before use.
            "pool_recycle": 60 * 5,  # Drop unused connections after 5 minutes.
            **(self.config.engine or {}),
        }
