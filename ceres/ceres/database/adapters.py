import sqlite3
import traceback
from abc import ABC, abstractmethod
from os import PathLike
from pathlib import Path
from sqlite3 import Connection as SQLiteConnection
from tempfile import NamedTemporaryFile, gettempdir
from typing import Any, Generic, TypeVar, final
from uuid import UUID

from sqlalchemy import QueuePool, event, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from typing_extensions import override

from ceres.address import Address
from ceres.config import DatabaseConfig, PostgresDatabaseConfig, SQLiteDatabaseConfig
from ceres.internal.database.entities import AlertDumpEntity, BinEntity
from ceres.internal.utilities import achunkify
from ceres.threading import spawn

ConfigT = TypeVar("ConfigT", bound=DatabaseConfig, covariant=True)


class DatabaseAdapter(Generic[ConfigT], ABC):
    def __init__(self, id: UUID, config: ConfigT) -> None:
        self.__id = id
        self.__config = config

    @property
    def id(self) -> UUID:
        return self.__id

    @property
    def config(self) -> ConfigT:
        return self.__config

    @abstractmethod
    def get_engine_url(cls) -> str:
        ...

    @abstractmethod
    def get_engine_config(self) -> dict[str, Any]:
        ...

    def create_engine(self) -> AsyncEngine:
        return create_async_engine(
            self.get_engine_url(),
            **self.get_engine_config(),
        )

    async def dump(self, path: PathLike[str], *, update: bool = False) -> None:
        raise NotImplementedError()

    async def load(self, path: PathLike[str]) -> None:
        raise NotImplementedError()

    async def clone(self, path: PathLike[str]) -> None:
        raise NotImplementedError()

    async def _dump(
        self,
        source_engine: AsyncEngine,
        destination_engine: AsyncEngine,
        destination_path: Path,
        *,
        update: bool = False,
    ) -> None:
        from ceres.internal.database.entities import (
            AlertEntity,
            BinEntity,
            ComponentEntity,
            Entity,
            LogEntryEntity,
            MessageEntity,
        )

        if not update:
            if destination_path.exists():
                destination_path.unlink()

        async with destination_engine.begin() as destination_connection:
            for cls in Entity.get_entity_classes():
                dump_cls = cls.get_entity_dump_cls()
                if dump_cls is None:
                    continue

                for statement in dump_cls.get_entity_ddl(destination_engine.sync_engine):
                    await destination_connection.execute(text(statement))

            async with source_engine.begin() as source_connection:
                if not update:
                    await destination_connection.execute(text("PRAGMA foreign_keys = OFF"))

                for connection in (source_connection, destination_connection):
                    await connection.execute(text("PRAGMA syncronous = 0"))
                    await connection.execute(text("PRAGMA locking_mode = EXCLUSIVE"))

                bins: dict[int, Address] = {}
                for bin_id, address in await source_connection.execute(
                    select(BinEntity.id, BinEntity.address)
                ):
                    bins[bin_id] = address

                from sqlalchemy.dialects.sqlite import insert

                for source_component in await source_connection.execute(
                    select(*ComponentEntity.get_entity_columns())
                ):
                    destination_component = source_component._asdict()
                    await destination_connection.execute(
                        insert(ComponentEntity.get_entity_dump_cls())
                        .values(destination_component)
                        .on_conflict_do_update(set_=destination_component)
                    )

                for item_cls in (MessageEntity, AlertEntity, LogEntryEntity):
                    item_columns = item_cls.get_entity_columns()
                    item_dump_cls = item_cls.get_entity_dump_cls()
                    item_dump_columns = item_dump_cls.get_entity_columns()

                    async for source_items in achunkify(
                        await source_connection.stream(select(*item_columns)),
                        500,
                    ):

                        destination_items: list[dict[str, Any]] = []
                        for source_item in source_items:
                            destination_item = source_item._asdict()
                            destination_item["address"] = bins[destination_item.pop("bin_id")]
                            destination_items.append(destination_item)

                        statement = insert(item_dump_cls).values(destination_items)
                        await destination_connection.execute(
                            statement.on_conflict_do_update(
                                set_={
                                    key: statement.excluded[key] for key in item_dump_columns.keys()
                                }
                            )
                        )

            await destination_connection.commit()

    async def _load(
        self,
        source_engine: AsyncEngine,
        destination_engine: AsyncEngine,
    ) -> None:
        from ceres.internal.database.entities import (
            AlertEntity,
            ComponentDumpEntity,
            ComponentEntity,
            Entity,
            LogEntryDumpEntity,
            LogEntryEntity,
            MessageDumpEntity,
            MessageEntity,
        )

        async with destination_engine.begin() as destination_connection:
            for cls in Entity.get_entity_classes():
                for statement in cls.get_entity_ddl(destination_engine.sync_engine):
                    await destination_connection.execute(text(statement))

            async with source_engine.begin() as source_connection:
                from sqlalchemy.dialects.sqlite import insert

                incoming_addresses = sorted(
                    {
                        *list(await source_connection.scalars(select(ComponentDumpEntity.address))),
                        *list(await source_connection.scalars(select(MessageDumpEntity.address))),
                        *list(await source_connection.scalars(select(AlertDumpEntity.address))),
                        *list(await source_connection.scalars(select(LogEntryDumpEntity.address))),
                    }
                )

                current_addresses: dict[Address, int] = {}
                for address, bin_id in await destination_connection.execute(
                    select(BinEntity.address, BinEntity.id)
                ):
                    current_addresses[address] = bin_id

                for address in incoming_addresses:
                    if address not in current_addresses:
                        bin_id = await destination_connection.scalar(
                            insert(BinEntity).values({"address": address}).returning(BinEntity.id)
                        )
                        assert bin_id is not None

                        current_addresses[address] = bin_id

                for source_component in await source_connection.execute(
                    select(*ComponentDumpEntity.get_entity_columns())
                ):
                    destination_component = source_component._asdict()
                    await destination_connection.execute(
                        insert(ComponentEntity.get_entity_dump_cls())
                        .values(destination_component)
                        .on_conflict_do_update(set_=destination_component)
                    )

                for item_cls in (MessageEntity, AlertEntity, LogEntryEntity):
                    item_columns = item_cls.get_entity_columns()
                    item_dump_cls = item_cls.get_entity_dump_cls()
                    item_dump_columns = item_dump_cls.get_entity_columns()

                    async for source_items in achunkify(
                        await source_connection.stream(select(*item_dump_columns)),
                        500,
                    ):

                        destination_items: list[dict[str, Any]] = []
                        for source_item in source_items:
                            destination_item = source_item._asdict()
                            destination_item["bin_id"] = current_addresses[
                                destination_item.pop("address")
                            ]
                            destination_items.append(destination_item)

                        statement = insert(item_cls).values(destination_items)
                        await destination_connection.execute(
                            statement.on_conflict_do_update(
                                set_={key: statement.excluded[key] for key in item_columns.keys()}
                            )
                        )

            await destination_connection.commit()


@final
class SQLiteDatabaseAdapter(DatabaseAdapter[SQLiteDatabaseConfig]):
    def get_engine_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.__get_path()}"

    def __del__(self) -> None:
        if self.config.path is not None or not self.__get_temporary_path().exists():
            return

        try:
            for path in Path(gettempdir()).glob(f"*{self.id}*"):
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    traceback.print_exc()
        except Exception:
            traceback.print_exc()

    def get_engine_config(self) -> dict[str, Any]:
        return {
            "poolclass": QueuePool,
            "pool_size": 10,  # Keep a maximum of ten connections alive continuously.
            "max_overflow": -1,  # Allow an infinite number of connections to be created if needed.
            "pool_recycle": 60,  # Recreate connections after one minute.
            **self.config.engine,
        }

    def create_engine(self) -> AsyncEngine:
        engine = super().create_engine()
        self.__add_essential_listeners(engine)

        # https://docs.sqlalchemy.org/en/latest/core/events.html#sqlalchemy.events.PoolEvents.first_connect
        @event.listens_for(engine.sync_engine, "first_connect")
        def first_connect(connection: SQLiteConnection, *args: object) -> None:
            # Enable incremental "auto_vacuum" mode when the first connection to the database is
            # made. This can only be done before database tables are created and is disabled by
            # default, so we do it here just in case "incremental_vacuum" is needed later on.
            # https://www.sqlite.org/pragma.html#pragma_auto_vacuum
            # https://www.sqlite.org/pragma.html#pragma_incremental_vacuum
            connection.execute("PRAGMA auto_vacuum = INCREMENTAL")

        # https://docs.sqlalchemy.org/en/20/core/events.html#sqlalchemy.events.PoolEvents.close
        @event.listens_for(engine.sync_engine, "close")
        def close(connection: SQLiteConnection, *args: object) -> None:
            # Run optimize every time we close a database connection.
            # https://www.sqlite.org/lang_analyze.html
            try:
                connection.execute("PRAGMA analysis_limit = 500")
                connection.execute("PRAGMA optimize")
            except OperationalError:
                pass

        return engine

    def __add_essential_listeners(self, engine: AsyncEngine) -> None:
        # https://docs.sqlalchemy.org/en/latest/core/events.html#sqlalchemy.events.DialectEvents.do_connect
        @event.listens_for(engine.sync_engine, "do_connect")
        def do_connect(*args: object) -> None:
            # Create the directory containing the database file if it doesn't already exist.
            if self.config.path is not None:
                try:
                    self.config.path.parent.mkdir(parents=True, exist_ok=True)
                except Exception:
                    traceback.print_exc()

        # https://docs.sqlalchemy.org/en/20/core/events.html#sqlalchemy.events.PoolEvents.connect
        @event.listens_for(engine.sync_engine, "connect")
        def connect(connection: SQLiteConnection, *args: object) -> None:
            # Enable a 30 second busy timeout.
            connection.execute("PRAGMA busy_timeout = 30000")
            # Clear the isolation level to stop "pysqlite" from:
            #   1. Automatically emitting "BEGIN"
            #   2. Automatically emitting "COMMIT" before any DDL
            # https://docs.sqlalchemy.org/en/latest/dialects/sqlite.html#serializable-isolation-savepoints-transactional-ddl
            connection.isolation_level = None
            # Enable foreign key handling by default.
            # https://docs.sqlalchemy.org/en/latest/dialects/sqlite.html#foreign-key-support
            connection.execute("PRAGMA foreign_keys = ON")

        # https://docs.sqlalchemy.org/en/20/core/events.html#sqlalchemy.events.ConnectionEvents.begin
        @event.listens_for(engine.sync_engine, "begin")
        def begin(connection: Connection) -> None:
            # Emit our own "BEGIN" statement.
            # https://docs.sqlalchemy.org/en/latest/dialects/sqlite.html#serializable-isolation-savepoints-transactional-ddl
            connection.exec_driver_sql("BEGIN IMMEDIATE")

    @override
    async def clone(self, path: PathLike[str]) -> None:
        path = Path(path).absolute()

        if path.exists():
            path.unlink()

        def execute() -> None:
            with sqlite3.connect(self.__get_path()) as source_connection:
                with sqlite3.connect(path) as temporary_connection:
                    source_connection.backup(temporary_connection)

        await spawn(execute)

    @override
    async def dump(self, path: PathLike[str], *, update: bool = False) -> None:
        path = Path(path).absolute()

        if not update:
            if path.exists():
                path.unlink()

        with NamedTemporaryFile(prefix="ceres", suffix=".sqlite.temporary") as temporary_file:
            temporary_path = Path(temporary_file.name)
            await self.clone(temporary_path)

            source_engine = create_async_engine(f"sqlite+aiosqlite:///{temporary_path}")
            destination_engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
            self.__add_essential_listeners(source_engine)
            self.__add_essential_listeners(destination_engine)

            await self._dump(source_engine, destination_engine, path, update=update)

    @override
    async def load(self, path: PathLike[str]) -> None:
        destination_engine = self.create_engine()
        source_engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
        self.__add_essential_listeners(source_engine)

        await self._load(source_engine, destination_engine)

    def __get_path(self) -> Path:
        # If a path is provided, create an database at the provided path.
        if self.config.path is not None:
            return self.config.path.absolute()

        # Otherwise create a temporary on-disk database.
        return self.__get_temporary_path()

    def __get_temporary_path(self) -> Path:
        return Path(gettempdir()) / f"ceres-{self.id}.sqlite"


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
            "poolclass": QueuePool,
            "pool_size": 10,  # Keep a maximum of ten connections alive continuously.
            "max_overflow": -1,  # Allow an infinite number of connections to be created if needed.
            "pool_pre_ping": True,  # Check to see if a connection has closed before use.
            "pool_recycle": 60 * 5,  # Recreate connections after five minutes.
            **self.config.engine,
        }
