from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import JSON, TIMESTAMP, Column, String
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import DatabaseConfig


def create_engine(config: DatabaseConfig) -> AsyncEngine:
    if config.type == "sqlite":
        connection = f"sqlite3+aiosqlite://{config.path}"
    else:
        connection = f"postgresql+asyncpg://{config.user}:{config.password}@{config.host}:{config.port}/{config.name}"

    return create_async_engine(
        connection,
        **{
            "echo": config.echo,
            "pool_pre_ping": True,  # Check to see if a connection has closed before use.
            "pool_recycle": 60 * 5,  # Drop unused connections after 5 minutes.
        },
    )


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
        self._engine = create_engine(config)
        self._session_maker = sessionmaker(
            self._engine,
            autocommit=False,
            expire_on_commit=False,
            class_=AsyncSession,
        )

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


BaseEntity = declarative_base()


class Entity(BaseEntity):
    __abstract__ = True
    __mapper_args__ = {
        "eager_defaults": True,
    }

    id: str = Column(String, primary_key=True, default=lambda: str(uuid4()))


class MessageEntity(Entity):
    __tablename__ = "messages"
    connection_id: str = Column(String)
    timestamp: datetime = Column(TIMESTAMP(timezone=True))
    content: str = Column(String)


class ParticleEntity(Entity):
    __tablename__ = "particles"
    timestamp: datetime = Column(TIMESTAMP(timezone=True))
    value: Any = Column(JSON, none_as_null=True)
