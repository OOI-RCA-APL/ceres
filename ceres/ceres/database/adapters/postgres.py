from typing import Any, final

from ...config import PostgresDatabaseConfig
from ..adapter import DatabaseAdapter


@final
class PostgresDatabaseAdapter(DatabaseAdapter[PostgresDatabaseConfig]):
    def get_engine_url(self) -> str:
        return (
            "postgresql+psycopg://"
            + f"{self.config.user}:{self.config.password.get_secret_value()}"
            + f"@{self.config.host}:{self.config.port}/{self.config.database}"
        )

    def get_engine_config(self) -> dict[str, Any]:
        return {
            "pool_pre_ping": True,  # Check to see if a connection has closed before use.
            "pool_recycle": 60 * 5,  # Drop unused connections after 5 minutes.
            **self.config.engine,
        }
