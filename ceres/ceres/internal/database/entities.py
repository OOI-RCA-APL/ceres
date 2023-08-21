import re
import textwrap
from datetime import datetime
from typing import TYPE_CHECKING, Any, ClassVar, Iterable
from uuid import UUID

import sqlparse
from sqlalchemy import (
    JSON,
    Boolean,
    ClauseElement,
    Engine,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    PrimaryKeyConstraint,
    Table,
    Text,
    text,
)
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    MappedAsDataclass,
    declared_attr,
    mapped_column,
    relationship,
)
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlalchemy.sql import expression
from typing_extensions import final

from ceres.address import Address
from ceres.internal.database.types import (
    AddressMapper,
    DateTimeMapper,
    EnumConstraint,
    EnumMapper,
    UUIDMapper,
)
from ceres.level import Level
from ceres.message import MessageDirection


def _sql(statement: str, *, indent: int = 0) -> str:
    statement = textwrap.dedent(statement).strip()
    sqlparse.format(statement, keyword_case="upper").strip()
    statement = statement.rstrip(";")
    statement += ";"
    if indent:
        statement = textwrap.indent(statement, " " * (indent * 4))
    return statement


def _compile(engine: Engine, element: ClauseElement) -> str:
    statement = str(element.compile(engine))
    statement = re.sub(
        r"[\n\r]+\t",
        "\n    ",
        textwrap.dedent(statement.strip()),
    ).strip()

    if not statement.endswith(";"):
        statement += ";"
    return statement


class Entity(MappedAsDataclass, DeclarativeBase, kw_only=True):
    __abstract__ = True
    __mapper_args__ = {
        "eager_defaults": True,
    }

    if TYPE_CHECKING:
        __tablename__: ClassVar[str]  # type: ignore
        __table__: ClassVar[Table]

    @staticmethod
    def get_entity_classes() -> list[type["Entity"]]:
        return [
            ComponentEntity,
            InternalBinEntity,
            InternalMessageEntity,
            InternalAlertEntity,
            InternalLogEntryEntity,
            MessageEntity,
            AlertEntity,
            LogEntryEntity,
        ]

    @classmethod
    def get_entity_ddl(cls, engine: Engine) -> Iterable[str]:
        yield _compile(engine, CreateTable(cls.__table__, if_not_exists=True))
        for index in sorted(cls.__table__.indexes, key=lambda index: str(index.name)):
            yield _compile(engine, CreateIndex(index, if_not_exists=True))

    @classmethod
    async def create_all(cls, bind: AsyncEngine | AsyncConnection) -> None:
        match bind:
            case AsyncEngine():
                engine = bind.sync_engine
                connection = await bind.connect()
            case AsyncConnection():
                engine = bind.sync_engine
                connection = bind

        async with connection.begin():
            for cls in cls.get_entity_classes():
                for statement in cls.get_entity_ddl(engine):
                    await connection.execute(text(statement))

            await connection.commit()

    def values(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__table__.columns.keys()}


@final
class ComponentEntity(Entity, kw_only=True):
    __tablename__ = "components"

    address: Mapped[Address] = mapped_column(AddressMapper)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=expression.false())

    __table_args__ = (PrimaryKeyConstraint("address", name="pk_components"),)


@final
class InternalBinEntity(Entity, kw_only=True):
    __tablename__ = "__bins"

    id: Mapped[int] = mapped_column(Integer, autoincrement=True, default=None)
    address: Mapped[Address] = mapped_column(AddressMapper)

    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_bins"),
        Index("ix_bins__address", "address", unique=True),
    )


class InternalItemEntity(Entity, kw_only=True):
    __abstract__ = True

    id: Mapped[UUID] = mapped_column(UUIDMapper, sort_order=-3000)

    @declared_attr
    def bin_id(cls) -> Mapped[int]:
        return mapped_column(
            Integer,
            ForeignKey(
                InternalBinEntity.id,
                name=f"fk_{cls.__tablename__.strip('_')}__bin_id__{InternalBinEntity.__tablename__}",
            ),
            sort_order=-2000,
        )

    timestamp: Mapped[datetime] = mapped_column(DateTimeMapper, sort_order=-1000)

    @declared_attr
    def bin(cls) -> Mapped[InternalBinEntity]:
        return relationship(InternalBinEntity, lazy="joined")

    @declared_attr
    def __table_args__(cls) -> Any:
        return (
            PrimaryKeyConstraint("id", name=f"pk_{cls.__tablename__.strip('_')}"),
            Index(f"ix_{cls.__tablename__.strip('_')}__bin_id", "bin_id"),
            Index(f"ix_{cls.__tablename__.strip('_')}__bin_id__timestamp", "bin_id", "timestamp"),
            Index(f"ix_{cls.__tablename__.strip('_')}__timestamp", "timestamp"),
        )


class ItemEntity(Entity, kw_only=True):
    __abstract__ = True

    id: Mapped[UUID] = mapped_column(UUIDMapper, sort_order=-3000)
    address: Mapped[Address] = mapped_column(AddressMapper, sort_order=-2000)
    timestamp: Mapped[datetime] = mapped_column(DateTimeMapper, sort_order=-1000)

    @declared_attr
    def __table_args__(cls) -> Any:
        return (PrimaryKeyConstraint("id", name=f"pk_{cls.__tablename__.strip('_')}"),)


@final
class InternalMessageEntity(InternalItemEntity, kw_only=True):
    __tablename__ = "__messages"

    direction: Mapped[MessageDirection] = mapped_column(EnumMapper(MessageDirection))
    content: Mapped[bytes] = mapped_column(LargeBinary)

    @declared_attr
    def __table_args__(cls) -> Any:
        return (
            *super().__table_args__,
            EnumConstraint("direction", MessageDirection, "ck_messages__direction"),
            Index("ix_messages__content", "content"),
        )


@final
class MessageEntity(ItemEntity, kw_only=True):
    __tablename__ = "messages"

    Internal: ClassVar[type[InternalMessageEntity]] = InternalMessageEntity

    direction: Mapped[MessageDirection] = mapped_column(EnumMapper(MessageDirection))
    content: Mapped[bytes] = mapped_column(LargeBinary)

    @classmethod
    def get_entity_ddl(cls, engine: Engine) -> Iterable[str]:
        yield from _create_view(
            engine,
            "messages",
            """
            SELECT __messages.id, address, timestamp, direction, content
            FROM __messages
            JOIN __bins ON __messages.bin_id = __bins.id;
            """,
        )

        yield from _create_triggers(
            engine,
            "messages",
            """
            INSERT INTO __bins (address) SELECT new.address WHERE NOT EXISTS (SELECT TRUE FROM __bins WHERE address = new.address);
            INSERT INTO __messages (id, bin_id, timestamp, direction, content)
            VALUES (new.id, (SELECT id FROM __bins WHERE __bins.address = new.address), new.timestamp, new.direction, new.content)
            ON CONFLICT DO UPDATE SET id = new.id, timestamp = new.timestamp, direction = new.direction, content = new.content;
            """,  # noqa: E501
            """
            DELETE FROM __messages WHERE bin_id = (SELECT id FROM __bins WHERE __bins.address = old.address);
            """,  # noqa: E501
            """
            INSERT INTO __bins (address) SELECT new.address WHERE NOT EXISTS (SELECT TRUE FROM __bins WHERE address = new.address);
            UPDATE __messages
            SET
                id = new.id,
                bin_id = (SELECT id FROM __bins WHERE __bins.address = new.address),
                timestamp = new.timestamp,
                direction = new.direction,
                content = new.content
            WHERE id = old.id;
            """,  # noqa: E501
        )


@final
class InternalAlertEntity(InternalItemEntity, kw_only=True):
    __tablename__ = "__alerts"

    level: Mapped[Level] = mapped_column(EnumMapper(Level))
    code: Mapped[str] = mapped_column(Text)
    info: Mapped[dict[str, Any]] = mapped_column(JSON, default_factory=dict)

    @declared_attr
    def __table_args__(cls) -> Any:
        return (
            *super().__table_args__,
            EnumConstraint("level", Level, "ck_alerts__level"),
            Index("ix_alerts__code", "code"),
        )


@final
class AlertEntity(ItemEntity, kw_only=True):
    __tablename__ = "alerts"

    Internal: ClassVar[type[InternalAlertEntity]] = InternalAlertEntity

    level: Mapped[Level] = mapped_column(EnumMapper(Level))
    code: Mapped[str] = mapped_column(Text)
    info: Mapped[dict[str, Any]] = mapped_column(JSON)

    @classmethod
    def get_entity_ddl(cls, engine: Engine) -> Iterable[str]:
        yield from _create_view(
            engine,
            "alerts",
            """
            SELECT __alerts.id, address, timestamp, level, code, info
            FROM __alerts
            JOIN __bins ON __alerts.bin_id = __bins.id;
            """,
        )

        yield from _create_triggers(
            engine,
            "alerts",
            """
            INSERT INTO __bins (address) SELECT new.address WHERE NOT EXISTS (SELECT TRUE FROM __bins WHERE address = new.address);
            INSERT INTO __alerts (id, bin_id, timestamp, level, code, info)
            VALUES (new.id, (SELECT id FROM __bins WHERE __bins.address = new.address), new.timestamp, new.level, new.code, new.info)
            ON CONFLICT DO UPDATE SET id = new.id, timestamp = new.timestamp, level = new.level, code = new.code, info = new.info;
            """,  # noqa: E501
            """
            DELETE FROM __alerts WHERE bin_id = (SELECT id FROM __bins WHERE __bins.address = old.address);
            """,  # noqa: E501
            """
            INSERT INTO __bins (address) SELECT new.address WHERE NOT EXISTS (SELECT TRUE FROM __bins WHERE address = new.address);
            UPDATE __alerts
            SET
                id = new.id,
                bin_id = (SELECT id FROM __bins WHERE __bins.address = new.address),
                timestamp = new.timestamp,
                level = new.level,
                code = new.code,
                info = new.info
            WHERE id = old.id;
            """,  # noqa: E501
        )


@final
class InternalLogEntryEntity(InternalItemEntity, kw_only=True):
    __tablename__ = "__log_entries"

    level: Mapped[Level] = mapped_column(EnumMapper(Level))
    content: Mapped[str] = mapped_column(Text)

    @declared_attr
    def __table_args__(cls) -> Any:
        return (
            *super().__table_args__,
            EnumConstraint("level", Level, name="ck_log_entries__level"),
            Index("ix_log_entries__content", "content"),
        )


@final
class LogEntryEntity(ItemEntity, kw_only=True):
    __tablename__ = "log_entries"

    Internal: ClassVar[type[InternalLogEntryEntity]] = InternalLogEntryEntity

    level: Mapped[Level] = mapped_column(EnumMapper(Level))
    content: Mapped[str] = mapped_column(Text)

    @classmethod
    def get_entity_ddl(cls, engine: Engine) -> Iterable[str]:
        yield from _create_view(
            engine,
            "log_entries",
            """
SELECT __log_entries.id, address, timestamp, level, content
FROM __log_entries
JOIN __bins ON __log_entries.bin_id = __bins.id;
            """,
        )

        yield from _create_triggers(
            engine,
            "log_entries",
            """
            INSERT INTO __bins (address) SELECT new.address WHERE NOT EXISTS (SELECT TRUE FROM __bins WHERE address = new.address);
            INSERT INTO __log_entries (id, bin_id, timestamp, level, content)
            VALUES (new.id, (SELECT id FROM __bins WHERE __bins.address = new.address), new.timestamp, new.level, new.content)
            ON CONFLICT DO UPDATE SET id = new.id, timestamp = new.timestamp, level = new.level, content = new.content;
            """,  # noqa: E501
            """
            DELETE FROM __log_entries WHERE bin_id = (SELECT id FROM __bins WHERE __bins.address = old.address);
            """,  # noqa: E501
            """
            INSERT INTO __bins (address) SELECT new.address WHERE NOT EXISTS (SELECT TRUE FROM __bins WHERE address = new.address);
            UPDATE __log_entries
            SET
                id = new.id,
                bin_id = (SELECT id FROM __bins WHERE __bins.address = new.address),
                timestamp = new.timestamp,
                level = new.level,
                content = new.content
            WHERE id = old.id;
            """,  # noqa: E501 ,
        )


def _create_view(engine: Engine, name: str, statement: str) -> Iterable[str]:
    statement = _sql(statement)
    if engine.dialect.name == "sqlite":
        yield _sql(f"CREATE VIEW IF NOT EXISTS {name} AS {statement};")
    elif engine.dialect.name == "postgresql":
        yield _sql(f"CREATE OR REPLACE VIEW {name} AS {statement};")


def _create_triggers(
    engine: Engine,
    table: str,
    insert: str,
    delete: str,
    update: str,
) -> Iterable[str]:
    triggers = {
        "insert": insert,
        "delete": delete,
        "update": update,
    }

    if engine.dialect.name == "sqlite":
        for verb, sql in triggers.items():
            yield _sql(
                f"""
CREATE TRIGGER IF NOT EXISTS tr_{table}__{verb}
INSTEAD OF {verb.upper()} ON {table}
BEGIN
{_sql(sql, indent=1)}
END;
                """
            )
    elif engine.dialect.name == "postgresql":
        for verb, sql in triggers.items():
            yield _sql(
                f"""
CREATE OR REPLACE FUNCTION tf_{table}__{verb}() RETURNS TRIGGER AS $$
BEGIN
{_sql(sql, indent=1)}
    return new;
END;
$$LANGUAGE plpgsql;
                """
            )
            yield _sql(
                f"""
                CREATE OR REPLACE TRIGGER tr_{table}__{verb}
                INSTEAD OF {verb.upper()} ON {table}
                FOR EACH ROW EXECUTE FUNCTION tf_{table}__{verb}();
                """
            )
