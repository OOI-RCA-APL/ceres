from typing import final

from ....config import PostgresDatabaseConfig
from ..adapter import DatabaseAdapter


@final
class PostgresDatabaseAdapter(DatabaseAdapter[PostgresDatabaseConfig]):
    def get_engine_url(self) -> str:
        return (
            "postgresql+psycopg://"
            + f"{self.config.user}:{self.config.password.get_secret_value()}"
            + f"@{self.config.host}:{self.config.port}/{self.config.database}"
        )
