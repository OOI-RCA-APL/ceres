from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker

from .config import DatabaseConfig


class Database:
    """
    Database manager that abstracts over SQLAlchemy's async engine type.
    """

    if TYPE_CHECKING:
        _session_maker: sessionmaker[AsyncSession]

    def __init__(self, config: DatabaseConfig) -> None:
        """
        Create a new database manager using the provided configuration.
        """
        self._config = config

        engine_config = {
            "echo": self._config.echo,
            "pool_pre_ping": True,  # Check to see if a connection has closed before use.
            "pool_recycle": 60 * 5,  # Drop unused connections after 5 minutes.
        }

        self._engine: AsyncEngine = create_async_engine(self.url, **engine_config)
        self._session_maker = sessionmaker(
            self._engine,
            autocommit=False,
            expire_on_commit=False,
            class_=AsyncSession,
        )

    @property
    def url(self) -> str:
        """
        Get URL of the database used for the asyncronous engine. This includes username and password
        authentication.
        """
        user = self._config.user
        password = self._config.password
        host = self._config.host
        port = self._config.port
        name = self._config.name

        return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{name}"

    @property
    def engine(self) -> AsyncEngine:
        """
        Access the underlying database async engine.
        """
        return self._engine

    def session(self) -> AsyncSession:
        return self._session_maker()

    def connect(self) -> AsyncConnection:
        """
        Attempt to create a new database connection.
        """
        return self._engine.connect()

    async def dispose(self) -> None:
        """
        Discard all active database connections.
        """
        await self._engine.dispose()
