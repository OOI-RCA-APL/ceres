import re
from datetime import datetime
from textwrap import dedent
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    ClauseElement,
    Engine,
    ForeignKey,
    Index,
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


def _compile_to_sql_statement(engine: Engine, element: ClauseElement) -> str:
    statement = re.sub(
        r"[\n\r]+\t",
        "\n    ",
        dedent(str(element.compile(engine)).strip()),
    )

    if not statement.endswith(";"):
        statement += ";"

    return statement


class Entity(MappedAsDataclass, DeclarativeBase, kw_only=True):
    __abstract__ = True
    __mapper_args__ = {
        "eager_defaults": True,
    }

    @staticmethod
    def get_entity_classes() -> list[type["Entity"]]:
        classes: list[type[Entity]] = [
            AddressEntity,
            ComponentEntity,
            MessageEntity,
            AlertEntity,
            LogEntryEntity,
        ]

        classes.extend(
            mapper.class_
            for mapper in Entity.registry.mappers
            if mapper.class_ not in classes and issubclass(mapper.class_, Entity)
        )

        return classes

    @classmethod
    def get_entity_table(cls) -> Table:
        assert isinstance(cls.__table__, Table)
        return cls.__table__

    @classmethod
    def get_entity_ddl(cls, engine: Engine) -> Iterable[str]:
        table = cls.get_entity_table()
        yield _compile_to_sql_statement(engine, CreateTable(table, if_not_exists=True))
        for index in sorted(table.indexes, key=lambda index: str(index.name)):
            yield _compile_to_sql_statement(engine, CreateIndex(index, if_not_exists=True))

    def values(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__table__.columns.keys()}


@final
class AddressEntity(Entity):
    __tablename__ = "addresses"

    id: Mapped[UUID] = mapped_column(UUIDMapper)
    address: Mapped[Address] = mapped_column(AddressMapper)

    __table_args__ = (
        PrimaryKeyConstraint("id", name=f"pk_{__tablename__}"),
        Index(f"ix_{__tablename__}__address", "address", unique=True),
    )


@final
class ComponentEntity(Entity):
    __tablename__ = "components"

    address: Mapped[Address] = mapped_column(AddressMapper)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=expression.false())

    __table_args__ = (PrimaryKeyConstraint("address", name=f"pk_{__tablename__}"),)


class ItemEntity(Entity):
    __abstract__ = True

    id: Mapped[UUID] = mapped_column(UUIDMapper, sort_order=-3000)

    @declared_attr
    def address_id(cls) -> Mapped[UUID]:
        return mapped_column(
            UUIDMapper,
            ForeignKey(
                AddressEntity.id,
                name=f"fk_{cls.__tablename__}__address_id__{AddressEntity.__tablename__}",
            ),
            sort_order=-2000,
        )

    @declared_attr
    def address_entity(cls) -> Mapped[AddressEntity]:
        return relationship(AddressEntity, lazy="joined")

    @declared_attr  # type: ignore
    def address(cls) -> AssociationProxy[Address]:
        return association_proxy("address_entity", "address")

    timestamp: Mapped[datetime] = mapped_column(DateTimeMapper, sort_order=-1000)

    @declared_attr
    def __table_args__(cls) -> Any:
        return (
            PrimaryKeyConstraint("id", name=f"pk_{cls.__tablename__}"),
            Index(f"ix_{cls.__tablename__}__address_id", "address_id"),
            Index(f"ix_{cls.__tablename__}__address_id__timestamp", "address_id", "timestamp"),
            Index(f"ix_{cls.__tablename__}__timestamp", "timestamp"),
        )


@final
class MessageEntity(ItemEntity):
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
class AlertEntity(ItemEntity):
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
class LogEntryEntity(ItemEntity):
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
