from __future__ import annotations

from abc import ABC, abstractmethod
from textwrap import dedent
from typing import TYPE_CHECKING, Any, cast

import sqlalchemy as sql
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql.elements import TextClause

from ..config import DatabaseConfig, DatabaseType
from .entity import EntityManager


class DatabaseManager(ABC):
    """
    Database manager that abstracts over SQLAlchemy's async engine type.
    """

    if TYPE_CHECKING:
        _session_maker: sessionmaker[AsyncSession]

    def __init__(self, config: DatabaseConfig) -> None:
        """
        Create a new database manager using the provided configuration.
        """
        self._base_config = config
        self._engine = self._create_engine(config)
        self._session_maker = sessionmaker(
            self._engine,
            autocommit=False,
            expire_on_commit=False,
            class_=AsyncSession,
        )

    @classmethod
    @abstractmethod
    def _create_engine(cls, config: DatabaseConfig) -> AsyncEngine:
        ...

    @abstractmethod
    def _create_ddl_statements(self) -> list[str]:
        ...

    @abstractmethod
    def _create_tables_query(self) -> str:
        ...

    @property
    def type(self) -> DatabaseType:
        return self._base_config.type

    @property
    def ddl(self) -> list[str]:
        return [self.compile(statement) for statement in self._create_ddl_statements()]

    @property
    def engine(self) -> AsyncEngine:
        """
        Access the underlying database async engine.
        """
        return self._engine

    @property
    def entities(self) -> EntityManager:
        return EntityManager(self)

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
        parameters: dict[str, Any] = {},
    ) -> str:
        return str(
            sql.text(dedent(command).strip())
            .bindparams(**parameters)
            .compile(self._engine, compile_kwargs={"literal_binds": True})
        )

    def sql(
        self,
        command: str,
        parameters: dict[str, Any] = {},
    ) -> TextClause:
        return sql.text(self.compile(command, parameters))

    async def init(self) -> None:
        async with self.begin() as connection:
            for statement in self.ddl:
                await connection.execute(sql.text(statement))

    async def tables(self) -> list[str]:
        async with self.connect() as connection:
            return list((await connection.execute(sql.text(self._create_tables_query()))).scalars())
