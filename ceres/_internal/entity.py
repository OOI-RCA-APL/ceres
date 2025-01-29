from __future__ import annotations

from abc import abstractmethod
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Iterable,
    Literal,
    Mapping,
    TypeAlias,
    TypedDict,
    override,
)
from uuid import UUID

from pydantic import Field, NonNegativeInt
from sqlalchemy import (
    ClauseElement,
    ColumnElement,
    Delete,
    Dialect,
    Engine,
    Select,
    SQLColumnExpression,
    Update,
    select,
    tuple_,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, declared_attr, mapped_column
from sqlalchemy.schema import CreateIndex, CreateTable, PrimaryKeyConstraint, SchemaItem, Table
from sqlalchemy.sql.base import ReadOnlyColumnCollection

from ceres._internal import util
from ceres._internal.database.types import UUIDMapper
from ceres._internal.filter import BaseFilter, BaseFilterArgs
from ceres._internal.lazy import lazy_imports
from ceres.data import DeferBuild, ImmutableDataObject, MaybeSequence, uuid7
from ceres.database import DatabaseType

with lazy_imports(__name__):
    from sqlalchemy.ext.asyncio import AsyncEngine


class BaseEntityRow(
    MappedAsDataclass,
    DeclarativeBase,
    kw_only=True,
):
    __abstract__: ClassVar[bool] = True
    __mapper_args__: ClassVar[Mapping[str, Any]] = {
        "eager_defaults": True,
    }

    if TYPE_CHECKING:
        __tablename__: ClassVar[str]
        __table__: ClassVar[Table]

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
        return ()

    @classmethod
    def __get_table_kwargs__(cls) -> dict[str, Any]:
        return {}


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


class BaseEntityFilterArgs[
    FieldT: str,
    OrderT: str,
](BaseFilterArgs, total=False):
    order: MaybeSequence[OrderT] | None
    limit: NonNegativeInt | None
    offset: NonNegativeInt | None


class BaseEntityFilter[
    EntityT: BaseEntity,
    FieldT: str,
    OrderT: str,
](BaseFilter):
    order: MaybeSequence[OrderT] | None = None
    """Specify ordering of results by field. Prefix field names with '-' for descending order."""
    limit: NonNegativeInt | None = None
    """Limit the number of returned results."""
    offset: NonNegativeInt | None = None
    """Skip over a given number of results."""

    @classmethod
    @abstractmethod
    def _get_row_cls(cls) -> type[BaseEntityRow]: ...

    def matches(self, obj: EntityT) -> bool:
        return True

    def _get_where(self, dialect: DatabaseType) -> Iterable[SQLColumnExpression[bool]]:
        return ()

    @abstractmethod
    def _get_default_order(self) -> OrderT: ...

    def _get_order_by(self) -> tuple[SQLColumnExpression[Any], ...]:
        order = self.order
        if order is None:
            order = self._get_default_order()

        Row = self._get_row_cls()
        columns: list[SQLColumnExpression[Any]] = []
        for value in util.as_sequence(order):
            base = value.lstrip("-+")
            ascending = not value.startswith("-")
            column = Row.__table__.columns[base]
            columns.append(column if ascending else column.desc())

        return tuple(columns)

    def apply[StatementT: Select[tuple[Any, ...]] | Update | Delete](
        self,
        statement: StatementT,
        dialect: DatabaseType,
        *,
        always_use_subquery: bool = False,
        ignore_where: bool = False,
        ignore_order: bool = False,
    ) -> StatementT:
        where = () if ignore_where else tuple(self._get_where(dialect))
        order_by = () if ignore_order else tuple(self._get_order_by())
        limit = self.limit
        offset = self.offset

        # Opportunistically avoid using subquery filtering if possible.
        if not always_use_subquery:
            if isinstance(statement, Select):
                return statement.where(*where).order_by(*order_by).limit(limit).offset(offset)
            else:
                # This is an update or delete statement, and if there is no `limit` or `offset`,
                # `order_by` does not matter, so we can avoid using a subquery.
                if limit is None and offset is None:
                    return statement.where(*where)

        pk = self._get_row_cls().get_primary_key_columns()
        pks = select(*pk).where(*where).order_by(*order_by).limit(limit).offset(offset)

        pk = pk[0] if len(pk) == 1 else tuple_(*pk)

        if isinstance(statement, (Update, Delete)):
            return statement.where(pk.in_(pks))

        return statement.where(pk.in_(pks)).order_by(*order_by)


class BaseEntityCreate(ImmutableDataObject, DeferBuild):
    pass


class BaseEntityUpdate(TypedDict, total=False):
    pass


class BaseEntity(BaseEntityCreate):
    Row: ClassVar[type[BaseEntityRow]] = BaseEntityRow
    Create: ClassVar[type[BaseEntityCreate]] = BaseEntityCreate
    Update: ClassVar[type[BaseEntityUpdate]] = BaseEntityUpdate

    if TYPE_CHECKING:
        Filter: ClassVar = BaseEntityFilter
        FilterArgs: ClassVar = BaseEntityFilterArgs
        Field: ClassVar = str
        Order: ClassVar = str
    else:
        Filter: ClassVar[type[BaseEntityFilter]] = BaseEntityFilter
        FilterArgs: ClassVar[type[BaseEntityFilterArgs]] = BaseEntityFilterArgs
        Field: ClassVar[type[str]] = str
        Order: ClassVar[type[str]] = str


class BaseUUIDEntityRow(BaseEntityRow):
    __abstract__: ClassVar[bool] = True

    id: Mapped[UUID] = mapped_column(UUIDMapper, sort_order=-3000, default_factory=uuid7)

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            PrimaryKeyConstraint("id", name=f"pk_{cls.__tablename__}"),
        )


BaseUUIDEntityField: TypeAlias = Literal["id"]
BaseUUIDEntityOrder: TypeAlias = Literal["id", "-id"]


class BaseUUIDEntityFilterArgs[
    FieldT: str,
    OrderT: str,
](BaseEntityFilterArgs[FieldT, OrderT], total=False):
    id: MaybeSequence[UUID] | None


class BaseUUIDEntityFilter[
    EntityT: BaseUUIDEntity,
    FieldT: str,
    OrderT: str,
](BaseEntityFilter[EntityT, FieldT, OrderT]):
    id: MaybeSequence[UUID] | None = None
    """Filter by `id` being equal to one or more given UUIDs."""

    @classmethod
    @abstractmethod
    @override
    def _get_row_cls(cls) -> type[BaseUUIDEntityRow]: ...

    @override
    def matches(self, obj: EntityT) -> bool:
        if not super().matches(obj):
            return False

        if self.id is not None:
            if obj.id not in util.as_sequence(self.id):
                return False

        return True

    @override
    def _get_where(self, dialect: DatabaseType) -> Iterable[SQLColumnExpression[bool]]:
        yield from super()._get_where(dialect)
        columns = self._get_row_cls()
        if self.id is not None:
            yield columns.id.in_(util.as_sequence(self.id))


class BaseUUIDEntityCreate(BaseEntity):
    id: UUID = Field(default_factory=uuid7)


class BaseUUIDEntityUpdate(BaseEntityUpdate, total=False):
    pass


class BaseUUIDEntity(BaseUUIDEntityCreate):
    Row: ClassVar[type[BaseUUIDEntityRow]] = BaseUUIDEntityRow
    Create: ClassVar[type[BaseUUIDEntityCreate]] = BaseUUIDEntityCreate
    Update: ClassVar[type[BaseUUIDEntityUpdate]] = BaseUUIDEntityUpdate

    if TYPE_CHECKING:
        Filter: ClassVar = BaseUUIDEntityFilter
        FilterArgs: ClassVar = BaseUUIDEntityFilterArgs
        Field: ClassVar = BaseUUIDEntityField
        Order: ClassVar = BaseUUIDEntityOrder
    else:
        Filter: ClassVar[type[BaseUUIDEntityFilter]] = BaseUUIDEntityFilter
        FilterArgs: ClassVar[type[BaseUUIDEntityFilterArgs]] = BaseUUIDEntityFilterArgs
        Field: ClassVar[type[BaseUUIDEntityField]] = BaseUUIDEntityField
        Order: ClassVar[type[BaseUUIDEntityOrder]] = BaseUUIDEntityOrder
