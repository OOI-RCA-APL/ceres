from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Annotated, Any, ClassVar, Iterable, Mapping, Sequence, TypedDict
from uuid import UUID, uuid4

import pydantic
from pydantic import Field, NonNegativeInt
from sqlalchemy.orm.decl_api import DeclarativeBase, MappedAsDataclass

from ceres._internal.cli.plumbing import CLIOption
from ceres._internal.database.types import UUIDMapper
from ceres._internal.lazy import lazy_imports
from ceres.data import ImmutableDataObject
from ceres.database.enums import DatabaseType
from ceres.filter import BaseFilter, BaseFilterArgs

with lazy_imports(__name__):
    from sqlalchemy.engine import Dialect, Engine
    from sqlalchemy.ext.asyncio import AsyncEngine
    from sqlalchemy.orm import Mapped, declared_attr, mapped_column
    from sqlalchemy.schema import CreateIndex, CreateTable, PrimaryKeyConstraint, SchemaItem, Table
    from sqlalchemy.sql import (
        ClauseElement,
        ColumnElement,
        Delete,
        Select,
        SQLColumnExpression,
        Update,
        expression,
        select,
    )
    from sqlalchemy.sql.base import ReadOnlyColumnCollection

    from ceres._internal import util


def _compile(dialect: AsyncEngine | Engine | Dialect, element: ClauseElement) -> str:
    import re
    import textwrap

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
    __abstract__: ClassVar[bool] = True
    __mapper_args__: ClassVar[Mapping[str, Any]] = {
        "eager_defaults": True,
    }

    if TYPE_CHECKING:
        __tablename__: ClassVar[str]
        __table__: ClassVar[Table]

    id: Mapped[UUID] = mapped_column(UUIDMapper, sort_order=-3000, default_factory=uuid4)

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
        if isinstance(dialect, (Engine, AsyncEngine)):
            dialect = dialect.dialect

        for index in sorted(cls.__table__.indexes, key=lambda index: str(index.name)):
            if index._ddl_if is not None:
                if dialect.name not in util.as_sequence(index._ddl_if.dialect):
                    continue

            yield _compile(dialect, CreateIndex(index, if_not_exists=if_not_exists))

    def values(self) -> dict[str, Any]:
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

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


class BaseEntityFilter[EntityT: BaseEntity](BaseFilter, ABC):
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
    def _get_search_content(self, obj: EntityT) -> dict[str, str]: ...

    @abstractmethod
    def _get_database_search_content(
        self,
        dialect: DatabaseType,
    ) -> dict[str, SQLColumnExpression[Any]]: ...

    def _get_database_search_content_encoded_fields(self, dialect: DatabaseType) -> set[str]:
        return set()

    def matches(self, obj: EntityT) -> bool:
        if self.search is not None:
            values = self._get_search_content(obj)
            fields = values if self.search_field is None else util.as_sequence(self.search_field)
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
            if obj.id not in util.as_sequence(self.id):
                return False

        return True

    def _get_where(self, dialect: DatabaseType) -> Iterable[SQLColumnExpression[bool]]:
        columns = self._get_row_cls()
        encoded = self._get_database_search_content_encoded_fields(dialect)

        if self.search is not None:
            pattern = "%" + util.escape_like_expression(self.search) + "%"

            values = self._get_database_search_content(dialect)
            fields = values if self.search_field is None else util.as_sequence(self.search_field)
            condition: SQLColumnExpression[bool] | None = expression.false()

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
            yield columns.id.in_(util.as_sequence(self.id))

    def _get_order_by(self) -> SQLColumnExpression[Any] | None:
        return None

    def apply[
        StatementT: Select[tuple[Any, ...]] | Update | Delete
    ](self, statement: StatementT, dialect: DatabaseType) -> StatementT:
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
    Row: ClassVar[type[BaseEntityRow]] = BaseEntityRow
    Create: ClassVar[type[BaseEntityCreate]] = BaseEntityCreate
    Update: ClassVar[type[BaseEntityUpdate]] = BaseEntityUpdate

    if TYPE_CHECKING:
        Filter: ClassVar = BaseEntityFilter
    else:
        Filter: ClassVar[type[BaseEntityFilter]] = BaseEntityFilter

    FilterArgs: ClassVar[type[BaseEntityFilterArgs]] = BaseEntityFilterArgs
