from textwrap import dedent
from typing import TYPE_CHECKING, Any, Dict, List, cast

import sqlalchemy as sql
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql.elements import TextClause

from ..config import DatabaseConfig, DatabaseType
from .adapter import DatabaseAdapter
from .entity import EntityManager
from .sqlite import SQLiteDatabaseAdapter


def _create_engine(config: DatabaseConfig) -> AsyncEngine:
    if config.type == "sqlite":
        connection = f"sqlite+aiosqlite:///{config.path.resolve()}"
    else:
        raise ValueError(config.type)

    return create_async_engine(
        connection,
        **{
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
        self._engine = _create_engine(config)
        self._session_maker = sessionmaker(
            self._engine,
            autocommit=False,
            expire_on_commit=False,
            class_=AsyncSession,
        )

    @property
    def type(self) -> DatabaseType:
        return self._config.type

    @property
    def ddl(self) -> List[str]:
        return [self.compile(statement) for statement in self._adapter.ddl]

    @property
    def engine(self) -> AsyncEngine:
        """
        Access the underlying database async engine.
        """
        return self._engine

    @property
    def entities(self) -> EntityManager:
        return EntityManager(self)

    @property
    def _adapter(self) -> DatabaseAdapter:
        if self.type == "sqlite":
            return SQLiteDatabaseAdapter()

        raise ValueError(self.type)

    def session(self) -> AsyncSession:
        return self._session_maker()

    def connect(self) -> AsyncConnection:
        """
        Attempt to create a new database connection.
        """
        return self._engine.connect()

    def begin(self) -> AsyncConnection:
        """
        Attempt to create a new database connection.
        """
        return cast(AsyncConnection, self._engine.begin())

    async def dispose(self) -> None:
        """
        Discard all active database connections.
        """
        await self._engine.dispose()

    def compile(
        self,
        command: str,
        parameters: Dict[str, Any] = {},
    ) -> str:
        return str(
            sql.text(dedent(command).strip())
            .bindparams(**parameters)
            .compile(self._engine, compile_kwargs={"literal_binds": True})
        )

    def sql(
        self,
        command: str,
        parameters: Dict[str, Any] = {},
    ) -> TextClause:
        return sql.text(self.compile(command, parameters))

    async def init(self) -> None:
        async with self.begin() as connection:
            for statement in self.ddl:
                await connection.execute(sql.text(statement))

    async def tables(self) -> List[str]:
        async with self.connect() as connection:
            return list((await connection.execute(sql.text(self._adapter.tables))).scalars())
