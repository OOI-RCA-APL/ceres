import re
from datetime import datetime
from textwrap import dedent
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    ClauseElement,
    ColumnElement,
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
from sqlalchemy.sql.roles import ExpressionElementRole
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


class Entity(MappedAsDataclass, DeclarativeBase):
    __abstract__ = True
    __mapper_args__ = {
        "eager_defaults": True,
    }

    @staticmethod
    def get_entity_classes() -> list[type["Entity"]]:
        classes: list[type[Entity]] = [
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
class ComponentEntity(Entity):
    __tablename__ = "components"
    id: Mapped[UUID] = mapped_column(UUIDMapper)
    address: Mapped[Address] = mapped_column(AddressMapper)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        PrimaryKeyConstraint("id", name=f"pk_{__tablename__}"),
        Index(f"uq_{__tablename__}__address", "address", unique=True),
    )


@final
class MessageEntity(Entity):
    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(UUIDMapper)
    component_id: Mapped[UUID] = mapped_column(
        UUIDMapper,
        ForeignKey(
            ComponentEntity.id,
            name=f"fk_{__tablename__}__component_id__{ComponentEntity.__tablename__}",
        ),
    )
    timestamp: Mapped[datetime] = mapped_column(DateTimeMapper)
    direction: Mapped[MessageDirection] = mapped_column(EnumMapper(MessageDirection))
    content: Mapped[bytes] = mapped_column(LargeBinary)

    @declared_attr
    def component(cls) -> Mapped[ComponentEntity]:
        return relationship(ComponentEntity, lazy="joined")

    @declared_attr  # type: ignore
    def address(cls) -> AssociationProxy[Address]:
        return association_proxy("component", "address")

    __table_args__ = (
        PrimaryKeyConstraint("id", name=f"pk_{__tablename__}"),
        EnumConstraint("direction", MessageDirection, name=f"ck_{__tablename__}__direction"),
        Index(f"ix_{__tablename__}__component_id", "component_id"),
        Index(f"ix_{__tablename__}__component_id__timestamp", "component_id", "timestamp"),
        Index(f"ix_{__tablename__}__timestamp", "timestamp"),
        Index(f"ix_{__tablename__}__content", "content"),
    )


@final
class AlertEntity(Entity):
    __tablename__ = "alerts"

    id: Mapped[UUID] = mapped_column(UUIDMapper)
    component_id: Mapped[UUID] = mapped_column(
        UUIDMapper,
        ForeignKey(
            ComponentEntity.id,
            name=f"fk_{__tablename__}__component_id__{ComponentEntity.__tablename__}",
        ),
    )
    timestamp: Mapped[datetime] = mapped_column(DateTimeMapper)
    level: Mapped[Level] = mapped_column(EnumMapper(Level))
    code: Mapped[str] = mapped_column(Text)
    info: Mapped[dict[str, Any]] = mapped_column(JSON, default_factory=dict)

    @declared_attr
    def component(cls) -> Mapped[ComponentEntity]:
        return relationship(ComponentEntity, lazy="joined")

    @declared_attr  # type: ignore
    def address(cls) -> AssociationProxy[Address]:
        return association_proxy("component", "address")

    __table_args__ = (
        PrimaryKeyConstraint("id", name=f"pk_{__tablename__}"),
        EnumConstraint("level", Level, name=f"ck_{__tablename__}__level"),
        Index(f"ix_{__tablename__}__component_id", "component_id"),
        Index(f"ix_{__tablename__}__component_id__timestamp", "component_id", "timestamp"),
        Index(f"ix_{__tablename__}__timestamp", "timestamp"),
        Index(f"ix_{__tablename__}__code", "code"),
    )


@final
class LogEntryEntity(Entity):
    __tablename__ = "log_entries"

    id: Mapped[UUID] = mapped_column(UUIDMapper)
    component_id: Mapped[UUID] = mapped_column(
        UUIDMapper,
        ForeignKey(
            ComponentEntity.id,
            name=f"fk_{__tablename__}__component_id__{ComponentEntity.__tablename__}",
        ),
    )
    timestamp: Mapped[datetime] = mapped_column(DateTimeMapper)
    level: Mapped[Level] = mapped_column(EnumMapper(Level))
    content: Mapped[str] = mapped_column(Text)

    @declared_attr
    def component(cls) -> Mapped[ComponentEntity | None]:
        return relationship(ComponentEntity, lazy="joined")

    @declared_attr  # type: ignore
    def address(cls) -> AssociationProxy[Address]:
        return association_proxy("component", "address")

    __table_args__ = (
        PrimaryKeyConstraint("id", name=f"pk_{__tablename__}"),
        EnumConstraint("level", Level, name=f"ck_{__tablename__}__level"),
        Index(f"ix_{__tablename__}__component_id", "component_id"),
        Index(f"ix_{__tablename__}__component_id__timestamp", "component_id", "timestamp"),
        Index(f"ix_{__tablename__}__timestamp", "timestamp"),
    )


WhereExpression = ColumnElement[bool] | ExpressionElementRole[bool]
OrderByExpression = ColumnElement[Any] | ExpressionElementRole[Any]
