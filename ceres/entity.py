import re
import textwrap
from abc import ABC, abstractmethod
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Generic,
    Iterable,
    Sequence,
    TypedDict,
    TypeVar,
)
from uuid import UUID

import pydantic
from apscheduler.job import uuid4
from pydantic import Field, NonNegativeInt
from sqlalchemy import (
    ClauseElement,
    ColumnElement,
    ColumnExpressionArgument,
    Delete,
    Dialect,
    Engine,
    PrimaryKeyConstraint,
    Select,
    Table,
    Update,
    select,
)
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    MappedAsDataclass,
    QueryableAttribute,
    declared_attr,
    mapped_column,
)
from sqlalchemy.schema import CreateIndex, CreateTable, SchemaItem
from sqlalchemy.sql import expression
from sqlalchemy.sql.base import ReadOnlyColumnCollection
from typing_extensions import Annotated

from ceres._internal.cli.plumbing import CLIOption
from ceres._internal.database.types import UUIDMapper
from ceres._internal.utilities import as_sequence, escape_like_expression
from ceres.data import ImmutableDataObject
from ceres.database.enums import DatabaseType
from ceres.filter import BaseFilter, BaseFilterArgs

_StatementT = TypeVar("_StatementT", bound=Select[tuple[Any, ...]] | Update | Delete)


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


class BaseEntityRow(
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

    id: Mapped[UUID] = mapped_column(UUIDMapper, sort_order=-3000, default_factory=uuid4)

    @staticmethod
    def get_entity_row_classes() -> list[type["BaseEntityRow"]]:
        from ceres.alert import AlertRow
        from ceres.logs import LogEntryRow
        from ceres.message import MessageRow
        from ceres.store import StoreRow
        from ceres.user import UserRow

        return [
            UserRow,
            StoreRow,
            MessageRow,
            AlertRow,
            LogEntryRow,
        ]

    @classmethod
    def get_primary_key_constraint(cls) -> PrimaryKeyConstraint:
        return cls.__table__.primary_key

    @classmethod
    def get_primary_key_columns(cls) -> ReadOnlyColumnCollection[str, ColumnElement[Any]]:
        return cls.__table__.primary_key.columns

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
        return (PrimaryKeyConstraint("id", name=f"pk_{cls.__tablename__}"),)

    @classmethod
    def __get_table_kwargs__(cls) -> dict[str, Any]:
        return {}


class BaseEntityFilterArgs(BaseFilterArgs, total=False):
    search: str | None
    search_field: str | Sequence[str] | None
    id: UUID | Sequence[UUID] | None
    limit: NonNegativeInt | None
    offset: NonNegativeInt | None


_EntityT = TypeVar("_EntityT", bound="BaseEntity")


class BaseEntityFilter(BaseFilter, Generic[_EntityT], ABC):
    search: Annotated[str | None, CLIOption(str | None)] = Field(
        default=None,
        description="Filter by text content of field(s) in `search-field`.",
    )
    search_field: Annotated[str | Sequence[str] | None, CLIOption(list[str] | None)] = Field(
        default=None,
        description="Field(s) matched by `search`. Defaults to all.",
    )
    id: Annotated[UUID | Sequence[UUID] | None, CLIOption(list[UUID])] = Field(
        default=None,
        description="Filter by ID(s).",
    )
    limit: Annotated[NonNegativeInt | None, CLIOption(int | None)] = Field(
        default=None,
        description="Limit the number of returned results.",
        ge=0,
    )
    offset: Annotated[NonNegativeInt | None, CLIOption(int | None)] = Field(
        default=None,
        description="Skip over a given number of results.",
        ge=0,
    )

    @abstractmethod
    def _get_row_cls(self) -> type[BaseEntityRow]: ...

    @abstractmethod
    def _get_search_content(self, obj: _EntityT) -> dict[str, str]: ...

    @abstractmethod
    def _get_database_search_content(
        self,
        dialect: DatabaseType,
    ) -> dict[str, QueryableAttribute[str | bytes]]: ...

    def _get_database_search_encoded_fields(self) -> set[str]:
        return set()

    def matches(self, obj: _EntityT) -> bool:
        if self.search is not None:
            values = self._get_search_content(obj)
            fields = values if self.search_field is None else as_sequence(self.search_field)
            matched = False
            for field in fields:
                value = values.get(field)
                if value is None:
                    continue

                if self.search in value:
                    matched = True
                    break

            if not matched:
                return False

        if self.id is not None:
            if obj.id not in as_sequence(self.id):
                return False

        return True

    def _get_where(self, dialect: DatabaseType) -> Iterable[ColumnExpressionArgument[Any]]:
        columns = self._get_row_cls()
        encoded = self._get_database_search_encoded_fields()

        if self.search is not None:
            pattern = "%" + escape_like_expression(self.search) + "%"

            values = self._get_database_search_content(dialect)
            fields = values if self.search_field is None else as_sequence(self.search_field)
            condition: ColumnExpressionArgument[bool] | None = expression.false()

            for field in fields:
                value = values.get(field)
                if value is None:
                    continue

                if field in encoded:
                    condition |= value.like(pattern.encode("latin-1", "ignore"))
                else:
                    condition |= value.like(pattern)

            yield condition

        if self.id is not None:
            yield columns.id.in_(as_sequence(self.id))

    def _get_order_by(self) -> ColumnExpressionArgument[Any] | None:
        return None

    def apply(self, statement: _StatementT, dialect: DatabaseType) -> _StatementT:
        columns = self._get_row_cls()
        ids = (
            select(columns.id)
            .where(*self._get_where(dialect))
            .order_by(self._get_order_by())
            .limit(self.limit)
            .offset(self.offset)
        )

        if isinstance(statement, Update | Delete):
            return statement.where(columns.id.in_(ids))

        return statement.where(columns.id.in_(ids)).order_by(self._get_order_by())


class BaseEntityCreate(ImmutableDataObject):
    id: Annotated[UUID, CLIOption(UUID)] = Field(default_factory=uuid4)


class BaseEntityUpdate(TypedDict, total=False):
    pass


class BaseEntity(BaseEntityCreate):
    Row: ClassVar = BaseEntityRow
    Create: ClassVar = BaseEntityCreate
    Update: ClassVar = BaseEntityUpdate
    Filter: ClassVar = BaseEntityFilter
    FilterArgs: ClassVar = BaseEntityFilterArgs
