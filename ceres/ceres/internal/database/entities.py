import re
import textwrap
from datetime import datetime
from typing import TYPE_CHECKING, Any, ClassVar, Iterable
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    ClauseElement,
    Engine,
    Index,
    LargeBinary,
    PrimaryKeyConstraint,
    Table,
    Text,
    text,
)
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    MappedAsDataclass,
    declared_attr,
    mapped_column,
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
    import sqlparse

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
        __tablename__: str
        __table__: ClassVar[Table]

    @staticmethod
    def get_entity_classes() -> list[type["Entity"]]:
        return [
            ComponentEntity,
            MessageEntity,
            AlertEntity,
            LogEntryEntity,
        ]

    @classmethod
    def get_entity_ddl(
        cls,
        engine: Engine,
        *,
        table: bool = True,
        indexes: bool = True,
    ) -> Iterable[str]:
        if table:
            yield _compile(engine, CreateTable(cls.__table__, if_not_exists=True))

        if indexes:
            for index in sorted(cls.__table__.indexes, key=lambda index: str(index.name)):
                yield _compile(engine, CreateIndex(index, if_not_exists=True))

    @classmethod
    async def create_all(
        cls,
        engine: AsyncEngine,
        *,
        table: bool = True,
        indexes: bool = True,
    ) -> None:
        async with engine.begin() as connection:
            for cls in cls.get_entity_classes():
                for statement in cls.get_entity_ddl(
                    engine.sync_engine,
                    table=table,
                    indexes=indexes,
                ):
                    await connection.execute(text(statement))

            await connection.commit()

    def values(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__table__.columns.keys()}


@final
class ComponentEntity(Entity, kw_only=True):
    __tablename__ = "components"

    address: Mapped[Address] = mapped_column(AddressMapper)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=expression.false())

    __table_args__ = (PrimaryKeyConstraint("address", name=f"pk_{__tablename__}"),)


class ItemEntity(Entity, kw_only=True):
    __abstract__ = True

    id: Mapped[UUID] = mapped_column(UUIDMapper, sort_order=-3000)
    address: Mapped[Address] = mapped_column(AddressMapper, sort_order=-2000)
    timestamp: Mapped[datetime] = mapped_column(DateTimeMapper, sort_order=-1000)

    @declared_attr
    def __table_args__(cls) -> Any:
        return (
            PrimaryKeyConstraint("id", name=f"pk_{cls.__tablename__}"),
            Index(f"ix_{cls.__tablename__}__address", "address"),
            Index(f"ix_{cls.__tablename__}__timestamp", "timestamp"),
        )


@final
class MessageEntity(ItemEntity, kw_only=True):
    __tablename__ = "messages"

    direction: Mapped[MessageDirection] = mapped_column(EnumMapper(MessageDirection))
    content: Mapped[bytes] = mapped_column(LargeBinary)

    @declared_attr
    def __table_args__(cls) -> Any:
        return (
            *super().__table_args__,
            EnumConstraint("direction", MessageDirection, f"ck_{cls.__tablename__}__direction"),
            Index(f"ix_{cls.__tablename__}__content", "content"),
        )


@final
class AlertEntity(ItemEntity, kw_only=True):
    __tablename__ = "alerts"

    level: Mapped[Level] = mapped_column(EnumMapper(Level))
    code: Mapped[str] = mapped_column(Text)
    info: Mapped[dict[str, Any]] = mapped_column(JSON, default_factory=dict)

    @declared_attr
    def __table_args__(cls) -> Any:
        return (
            *super().__table_args__,
            EnumConstraint("level", Level, f"ck_{cls.__tablename__}__level"),
            Index(f"ix_{cls.__tablename__}__code", "code"),
        )


@final
class LogEntryEntity(ItemEntity, kw_only=True):
    __tablename__ = "log_entries"

    level: Mapped[Level] = mapped_column(EnumMapper(Level))
    content: Mapped[str] = mapped_column(Text)

    @declared_attr
    def __table_args__(cls) -> Any:
        return (
            *super().__table_args__,
            EnumConstraint("level", Level, name=f"ck_{cls.__tablename__}__level"),
            Index(f"ix_{cls.__tablename__}__content", "content"),
        )
