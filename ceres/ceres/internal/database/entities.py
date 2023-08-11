import re
from datetime import datetime
from textwrap import dedent
from typing import TYPE_CHECKING, Any, ClassVar, Iterable
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    ClauseElement,
    Column,
    Engine,
    FetchedValue,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    PrimaryKeyConstraint,
    Table,
    Text,
)
from sqlalchemy.ext.associationproxy import AssociationProxy, association_proxy
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
from typing_extensions import final, override

from sqlalchemy.sql.base import ReadOnlyColumnCollection

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


def _compile_to_sql_statement(engine: Engine, element: ClauseElement) -> str:
    statement = re.sub(
        r"[\n\r]+\t",
        "\n    ",
        dedent(str(element.compile(engine)).strip()),
    )

    if not statement.endswith(";"):
        statement += ";"

    return statement


class _EntityMethods:
    if TYPE_CHECKING:
        __table__: ClassVar[Table]

    @classmethod
    def get_entity_table(cls) -> Table:
        return cls.__table__

    @classmethod
    def get_entity_columns(cls) -> ReadOnlyColumnCollection[str, Column[Any]]:
        return cls.get_entity_table().columns

    @classmethod
    def get_entity_ddl(cls, engine: Engine) -> Iterable[str]:
        table = cls.get_entity_table()
        yield _compile_to_sql_statement(engine, CreateTable(table, if_not_exists=True))
        for index in sorted(table.indexes, key=lambda index: str(index.name)):
            yield _compile_to_sql_statement(engine, CreateIndex(index, if_not_exists=True))

    def values(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__table__.columns.keys()}


class DumpEntity(_EntityMethods, MappedAsDataclass, DeclarativeBase, kw_only=True):
    __abstract__ = True
    __mapper_args__ = {
        "eager_defaults": True,
    }


class Entity(_EntityMethods, MappedAsDataclass, DeclarativeBase, kw_only=True):
    __abstract__ = True
    __mapper_args__ = {
        "eager_defaults": True,
    }

    @staticmethod
    def get_entity_classes() -> list[type["Entity"]]:
        return [
            ComponentEntity,
            BinEntity,
            MessageEntity,
            AlertEntity,
            LogEntryEntity,
        ]

    @classmethod
    def get_entity_dump_cls(cls) -> type[DumpEntity] | None:
        return None


@final
class ComponentDumpEntity(DumpEntity, kw_only=True):
    __tablename__ = "components"

    address: Mapped[Address] = mapped_column(AddressMapper)
    enabled: Mapped[bool] = mapped_column(Boolean)

    __table_args__ = (PrimaryKeyConstraint("address", name=f"pk_{__tablename__}"),)


@final
class ComponentEntity(Entity, kw_only=True):
    __tablename__ = "components"

    address: Mapped[Address] = mapped_column(AddressMapper)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=expression.false())

    __table_args__ = (PrimaryKeyConstraint("address", name=f"pk_{__tablename__}"),)

    @override
    @classmethod
    def get_entity_dump_cls(cls) -> type[ComponentDumpEntity]:
        return ComponentDumpEntity


@final
class BinEntity(Entity, kw_only=True):
    __tablename__ = "bins"

    id: Mapped[int] = mapped_column(
        Integer,
        autoincrement=True,
        server_default=FetchedValue(),
        default=None,
    )
    address: Mapped[Address] = mapped_column(AddressMapper)

    __table_args__ = (
        PrimaryKeyConstraint("id", name=f"pk_{__tablename__}"),
        Index(f"ix_{__tablename__}__address", "address", unique=True),
    )


class ItemDumpEntity(DumpEntity, kw_only=True):
    __abstract__ = True

    id: Mapped[UUID] = mapped_column(UUIDMapper, sort_order=-3000)
    address: Mapped[Address] = mapped_column(AddressMapper, sort_order=-2000)
    timestamp: Mapped[datetime] = mapped_column(DateTimeMapper, sort_order=-1000)

    @declared_attr
    def __table_args__(cls) -> Any:
        return (PrimaryKeyConstraint("id", name=f"pk_{cls.__tablename__}"),)


class ItemEntity(Entity, kw_only=True):
    __abstract__ = True

    id: Mapped[UUID] = mapped_column(UUIDMapper, sort_order=-3000)

    @declared_attr
    def bin_id(cls) -> Mapped[int]:
        return mapped_column(
            Integer,
            ForeignKey(
                BinEntity.id,
                name=f"fk_{cls.__tablename__}__bin_id__{BinEntity.__tablename__}",
            ),
            sort_order=-2000,
        )

    timestamp: Mapped[datetime] = mapped_column(DateTimeMapper, sort_order=-1000)

    @declared_attr
    def bin(cls) -> Mapped[BinEntity]:
        return relationship(BinEntity, lazy="joined")

    @declared_attr  # type: ignore
    def address(cls) -> AssociationProxy[Address]:
        return association_proxy("bin", "address")

    @declared_attr
    def __table_args__(cls) -> Any:
        return (
            PrimaryKeyConstraint("id", name=f"pk_{cls.__tablename__}"),
            Index(f"ix_{cls.__tablename__}__bin_id", "bin_id"),
            Index(f"ix_{cls.__tablename__}__bin_id__timestamp", "bin_id", "timestamp"),
            Index(f"ix_{cls.__tablename__}__timestamp", "timestamp"),
        )


@final
class MessageDumpEntity(ItemDumpEntity, kw_only=True):
    __tablename__ = "messages"

    direction: Mapped[MessageDirection] = mapped_column(EnumMapper(MessageDirection))
    content: Mapped[bytes] = mapped_column(LargeBinary)


@final
class MessageEntity(ItemEntity, kw_only=True):
    __tablename__ = "messages"
    __dump__ = MessageDumpEntity

    direction: Mapped[MessageDirection] = mapped_column(EnumMapper(MessageDirection))
    content: Mapped[bytes] = mapped_column(LargeBinary)

    @declared_attr
    def __table_args__(cls) -> Any:
        return (
            *super().__table_args__,
            EnumConstraint("direction", MessageDirection, f"ck_{cls.__tablename__}__direction"),
            Index(f"ix_{cls.__tablename__}__content", "content"),
        )

    @override
    @classmethod
    def get_entity_dump_cls(cls) -> type[MessageDumpEntity]:
        return MessageDumpEntity


@final
class AlertDumpEntity(ItemDumpEntity, kw_only=True):
    __tablename__ = "alerts"

    level: Mapped[Level] = mapped_column(EnumMapper(Level))
    code: Mapped[str] = mapped_column(Text)
    info: Mapped[dict[str, Any]] = mapped_column(JSON)


@final
class AlertEntity(ItemEntity, kw_only=True):
    __tablename__ = "alerts"
    __dump__ = AlertDumpEntity

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

    @override
    @classmethod
    def get_entity_dump_cls(cls) -> type[AlertDumpEntity]:
        return AlertDumpEntity


@final
class LogEntryDumpEntity(ItemDumpEntity, kw_only=True):
    __tablename__ = "log_entries"

    level: Mapped[Level] = mapped_column(EnumMapper(Level))
    content: Mapped[str] = mapped_column(Text)


@final
class LogEntryEntity(ItemEntity, kw_only=True):
    __tablename__ = "log_entries"
    __dump__ = LogEntryDumpEntity

    level: Mapped[Level] = mapped_column(EnumMapper(Level))
    content: Mapped[str] = mapped_column(Text)

    @declared_attr
    def __table_args__(cls) -> Any:
        return (
            *super().__table_args__,
            EnumConstraint("level", Level, name=f"ck_{cls.__tablename__}__level"),
            Index(f"ix_{cls.__tablename__}__content", "content"),
        )

    @override
    @classmethod
    def get_entity_dump_cls(cls) -> type[LogEntryDumpEntity]:
        return LogEntryDumpEntity
