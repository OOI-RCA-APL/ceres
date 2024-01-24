import re
import textwrap
from datetime import datetime
from typing import TYPE_CHECKING, Any, ClassVar, Iterable
from uuid import UUID

import pydantic
from sqlalchemy import (
    JSON,
    Boolean,
    ClauseElement,
    Dialect,
    Engine,
    Index,
    LargeBinary,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    MappedAsDataclass,
    declared_attr,
    mapped_column,
    validates,
)
from sqlalchemy.schema import CreateIndex, CreateTable, SchemaItem
from sqlalchemy.sql import expression
from typing_extensions import final, override

from ceres.address import Address
from ceres.data import EmailStr, UsernameStr
from ceres.internal.auth import validate_password_hash
from ceres.internal.database.types import (
    AddressMapper,
    DateTimeMapper,
    EnumConstraint,
    EnumMapper,
    UUIDMapper,
)
from ceres.level import Level
from ceres.message import MessageDirection
from ceres.user import UserRole


def _sql(statement: str, *, indent: int = 0) -> str:
    statement = textwrap.dedent(statement).strip()
    import sqlparse

    sqlparse.format(statement, keyword_case="upper").strip()
    statement = statement.rstrip(";")
    statement += ";"
    if indent:
        statement = textwrap.indent(statement, " " * (indent * 4))
    return statement


def _compile(dialect: AsyncEngine | Engine | Dialect, element: ClauseElement) -> str:
    if isinstance(dialect, Engine):
        dialect = dialect.dialect
    elif isinstance(dialect, AsyncEngine):
        dialect = dialect.sync_engine.dialect

    statement = str(element.compile(dialect=dialect))
    statement = re.sub(
        r"[\n\r]+\t",
        "\n    ",
        textwrap.dedent(statement.strip()),
    ).strip()

    if not statement.endswith(";"):
        statement += ";"
    return statement


class Entity(
    MappedAsDataclass,
    DeclarativeBase,
    dataclass_callable=pydantic.dataclasses.dataclass,
    kw_only=True,
):
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
            UserEntity,
            StoreEntity,
            MessageEntity,
            AlertEntity,
            LogEntryEntity,
        ]

    @classmethod
    def get_ddl(
        cls,
        dialect: Dialect | Engine | AsyncEngine,
        *,
        table: bool = True,
        indexes: bool = True,
        if_not_exists: bool = True,
    ) -> Iterable[str]:
        if table:
            yield cls.get_table_ddl(dialect, if_not_exists=if_not_exists)
        if indexes:
            yield from cls.get_index_ddl(dialect, if_not_exists=if_not_exists)

    @classmethod
    def get_table_ddl(
        cls,
        dialect: Dialect | Engine | AsyncEngine,
        *,
        name: str | None = None,
        temporary: bool = False,
        if_not_exists: bool = True,
    ) -> str:
        statement = _compile(dialect, CreateTable(cls.__table__, if_not_exists=if_not_exists))

        if name:
            if if_not_exists:
                statement = statement.replace(
                    f"CREATE TABLE IF NOT EXISTS {cls.__tablename__}",
                    f"CREATE TABLE IF NOT EXISTS {name}",
                )
            else:
                statement = statement.replace(
                    f"CREATE TABLE {cls.__tablename__}",
                    f"CREATE TABLE {name}",
                )
        if temporary:
            statement = statement.replace("CREATE TABLE", "CREATE TEMPORARY TABLE")

        return statement

    @classmethod
    def get_index_ddl(
        cls,
        dialect: Dialect | Engine | AsyncEngine,
        *,
        if_not_exists: bool = True,
    ) -> Iterable[str]:
        for index in sorted(cls.__table__.indexes, key=lambda index: str(index.name)):
            yield _compile(dialect, CreateIndex(index, if_not_exists=if_not_exists))

    def values(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__table__.columns.keys()}

    @declared_attr
    def __table_args__(cls) -> Any:
        return (
            *cls.__get_table_args__(),
            cls.__get_table_kwargs__(),
        )

    @classmethod
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return ()

    @classmethod
    def __get_table_kwargs__(cls) -> dict[str, Any]:
        return {}


@final
class UserEntity(Entity, kw_only=True):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(UUIDMapper)
    username: Mapped[UsernameStr] = mapped_column(Text)
    hash: Mapped[str] = mapped_column(Text)  # A password hash created using bcrypt.
    role: Mapped[UserRole] = mapped_column(
        EnumMapper(UserRole),
        default=UserRole.OPERATOR,
        server_default=str(UserRole.OPERATOR),
    )
    disabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=expression.false(),
    )
    email: Mapped[EmailStr] = mapped_column(Text)

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            PrimaryKeyConstraint("id", name=f"pk_{cls.__tablename__}"),
            UniqueConstraint("username", name=f"uq_{cls.__tablename__}__username"),
            EnumConstraint("role", UserRole, name=f"ck_{cls.__tablename__}__role"),
        )

    @validates("hash")
    def _validate_hash(self, column: str, hash: str) -> str:
        if not validate_password_hash(hash):
            raise ValueError("only bcrypt hashes are supported")

        return hash


@final
class StoreEntity(Entity, kw_only=True):
    __tablename__ = "stores"

    address: Mapped[Address] = mapped_column(AddressMapper)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=expression.false())

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            PrimaryKeyConstraint("address", name=f"pk_{cls.__tablename__}"),
        )


class ItemEntity(Entity, kw_only=True):
    __abstract__ = True

    id: Mapped[UUID] = mapped_column(UUIDMapper, sort_order=-3000)
    address: Mapped[Address] = mapped_column(AddressMapper, sort_order=-2000)
    timestamp: Mapped[datetime] = mapped_column(DateTimeMapper, sort_order=-1000)

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            PrimaryKeyConstraint("id", name=f"pk_{cls.__tablename__}"),
            Index(f"ix_{cls.__tablename__}__address", "address"),
            Index(f"ix_{cls.__tablename__}__timestamp", "timestamp"),
        )


@final
class MessageEntity(ItemEntity, kw_only=True):
    __tablename__ = "messages"

    direction: Mapped[MessageDirection] = mapped_column(EnumMapper(MessageDirection))
    content: Mapped[bytes] = mapped_column(LargeBinary)

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            EnumConstraint("direction", MessageDirection, f"ck_{cls.__tablename__}__direction"),
            Index(f"ix_{cls.__tablename__}__content", "content"),
        )


@final
class AlertEntity(ItemEntity, kw_only=True):
    __tablename__ = "alerts"

    level: Mapped[Level] = mapped_column(EnumMapper(Level))
    code: Mapped[str] = mapped_column(Text)
    info: Mapped[dict[str, Any]] = mapped_column(JSON, default_factory=dict)

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            EnumConstraint("level", Level, f"ck_{cls.__tablename__}__level"),
            Index(f"ix_{cls.__tablename__}__code", "code"),
        )


@final
class LogEntryEntity(ItemEntity, kw_only=True):
    __tablename__ = "log_entries"

    level: Mapped[Level] = mapped_column(EnumMapper(Level))
    content: Mapped[str] = mapped_column(Text)

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            EnumConstraint("level", Level, name=f"ck_{cls.__tablename__}__level"),
            Index(f"ix_{cls.__tablename__}__content", "content"),
        )
