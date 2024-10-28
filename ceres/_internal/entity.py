from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    ClassVar,
    Iterable,
    Literal,
    Mapping,
    Sequence,
    TypedDict,
    override,
)
from uuid import UUID, uuid4

import pydantic
from pydantic import Field, NonNegativeInt
from sqlalchemy.orm.decl_api import DeclarativeBase, MappedAsDataclass

from ceres._internal.cli.plumbing import CLIOption
from ceres._internal.database.types import AddressMapper, DateTimeMapper, UUIDMapper
from ceres._internal.filter import BaseFilter, BaseFilterArgs
from ceres._internal.lazy import lazy_imports
from ceres.address import Address, AddressSelector
from ceres.data import DateTime, ImmutableDataObject, PositiveTimeDelta
from ceres.database.enums import DatabaseType
from ceres.timing import utc

with lazy_imports(__name__):
    from sqlalchemy.engine import Dialect, Engine
    from sqlalchemy.ext.asyncio import AsyncEngine
    from sqlalchemy.orm import Mapped, declared_attr, mapped_column
    from sqlalchemy.schema import (
        CreateIndex,
        CreateTable,
        Index,
        PrimaryKeyConstraint,
        SchemaItem,
        Table,
    )
    from sqlalchemy.sql import (
        ClauseElement,
        ColumnElement,
        Delete,
        Select,
        SQLColumnExpression,
        Update,
        expression,
        select,
        tuple_,
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


class BaseEntityFilterArgs[
    FieldT: str,
    OrderT: str,
](BaseFilterArgs, total=False):
    search: str | None
    search_field: FieldT | Sequence[FieldT] | None
    order: OrderT | Sequence[OrderT] | None
    limit: NonNegativeInt | None
    offset: NonNegativeInt | None


class BaseEntityFilter[
    EntityT: BaseEntity,
    FieldT: str,
    OrderT: str,
](BaseFilter, ABC):
    search: Annotated[str | None, CLIOption(str | None)] = Field(
        default=None,
        description="Filter by text content of field(s) in `search-field`.",
    )
    search_field: Annotated[FieldT | Sequence[FieldT] | None, CLIOption(list[str] | None)] = Field(
        default=None,
        description="Field(s) matched by `search`. Defaults to all.",
    )
    order: Annotated[OrderT | Sequence[OrderT] | None, CLIOption(list[str] | None)] = Field(
        default=None,
        description="Specify ordering of results by field. Prefix field names with '-' for descending order.",
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

    @classmethod
    @abstractmethod
    def _get_row_cls(cls) -> type[BaseEntityRow]: ...

    def _get_search_content(self, obj: EntityT) -> Mapping[str, str]:
        return {}

    def _get_database_search_content(
        self,
        dialect: DatabaseType,
    ) -> Mapping[str, SQLColumnExpression[Any]]:
        return {}

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

        return True

    def _get_where(self, dialect: DatabaseType) -> Iterable[SQLColumnExpression[bool]]:
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
        ignore_where: bool = False,
        ignore_order: bool = False,
    ) -> StatementT:
        where = () if ignore_where else self._get_where(dialect)
        order_by = () if ignore_order else self._get_order_by()
        limit = self.limit
        offset = self.offset

        if isinstance(statement, Select) and limit is None and offset is None:
            return statement.select_from(self._get_row_cls()).where(*where).order_by(*order_by)

        pk = self._get_row_cls().get_primary_key_columns()
        pks = select(*pk).where(*where).order_by(*order_by).limit(limit).offset(offset)

        pk = pk[0] if len(pk) == 1 else tuple_(*pk)

        if isinstance(statement, Update | Delete):
            return statement.where(pk.in_(pks))

        return statement.where(pk.in_(pks)).order_by(*order_by)


class BaseEntityCreate(ImmutableDataObject):
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

    id: Mapped[UUID] = mapped_column(UUIDMapper, sort_order=-3000, default_factory=uuid4)

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            PrimaryKeyConstraint("id", name=f"pk_{cls.__tablename__}"),
        )


BaseUUIDEntityField = Literal["id"]
BaseUUIDEntityOrder = Literal["id", "-id"]


class BaseUUIDEntityFilterArgs[
    FieldT: str,
    OrderT: str,
](BaseEntityFilterArgs[FieldT, OrderT], total=False):
    id: UUID | Sequence[UUID] | None


class BaseUUIDEntityFilter[
    EntityT: BaseUUIDEntity,
    FieldT: str,
    OrderT: str,
](BaseEntityFilter[EntityT, FieldT, OrderT]):
    id: Annotated[UUID | Sequence[UUID] | None, CLIOption(list[UUID])] = Field(
        default=None,
        description="Filter by ID(s).",
    )

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
    id: Annotated[UUID, CLIOption(UUID)] = Field(default_factory=uuid4)


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


class BaseItemRow(BaseEntityRow, kw_only=True):
    __abstract__: ClassVar[bool] = True

    address: Mapped[Address] = mapped_column(AddressMapper, sort_order=-2000)

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            Index(f"ix_{cls.__tablename__}__address", cls.address),
        )


BaseItemField = Literal["address"]
BaseItemOrder = Literal["address", "-address"]


class BaseItemFilterArgs[
    FieldT: str,
    OrderT: str,
](BaseEntityFilterArgs[FieldT, OrderT], total=False):
    root: Address
    address: AddressSelector | None


class BaseItemFilter[
    ItemT: BaseItem,
    FieldT: str,
    OrderT: str,
](BaseEntityFilter[ItemT, FieldT, OrderT]):
    address: Annotated[AddressSelector | None, CLIOption(str | None)] = Field(
        default=None,
        description="Filter by associated address.",
    )
    root: Annotated[Address, CLIOption(str | None)] = Field(
        default=Address.ROOT,
        description="The root address relative `address` selectors are mapped to.",
    )

    @override
    def matches(self, obj: ItemT) -> bool:  # type: ignore
        if not super().matches(obj):
            return False

        if self.address is not None:
            if not self.address.matches(obj.address, self.root):
                return False

        return True

    @classmethod
    @abstractmethod
    @override
    def _get_row_cls(cls) -> type[BaseItemRow]: ...

    @override
    def _get_search_content(self, obj: ItemT) -> Mapping[str, str]:
        return {
            **super()._get_search_content(obj),
            "address": str(obj.address),
        }

    @override
    def _get_database_search_content(
        self,
        dialect: DatabaseType,
    ) -> Mapping[str, SQLColumnExpression[Any]]:
        columns = self._get_row_cls()

        return {
            **super()._get_database_search_content(dialect),
            "address": columns.address,
        }

    @override
    def _get_where(self, dialect: DatabaseType) -> Iterable[SQLColumnExpression[bool]]:
        yield from super()._get_where(dialect)
        columns = self._get_row_cls()

        if self.address is not None:
            yield self.address.matches_expression(columns.address, self.root)


class BaseItemCreate(BaseEntity):
    address: Annotated[Address, CLIOption(str)]


class BaseItemUpdate(BaseEntityUpdate, total=False):
    address: Address


class BaseItem(BaseItemCreate):
    Row: ClassVar[type[BaseItemRow]] = BaseItemRow
    Create: ClassVar[type[BaseItemCreate]] = BaseItemCreate
    Update: ClassVar[type[BaseItemUpdate]] = BaseItemUpdate

    if TYPE_CHECKING:
        Filter: ClassVar = BaseItemFilter
        FilterArgs: ClassVar = BaseItemFilterArgs
        Field: ClassVar = BaseItemField
        Order: ClassVar = BaseItemOrder
    else:
        Filter: ClassVar[type[BaseItemFilter]] = BaseItemFilter
        FilterArgs: ClassVar[type[BaseItemFilterArgs]] = BaseItemFilterArgs
        Field: ClassVar[type[BaseItemField]] = BaseItemField
        Order: ClassVar[type[BaseItemOrder]] = BaseItemOrder


class BaseRecordRow(BaseItemRow, BaseUUIDEntityRow, kw_only=True):
    __abstract__: ClassVar[bool] = True

    timestamp: Mapped[datetime] = mapped_column(DateTimeMapper, sort_order=-1000)

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            Index(f"ix_{cls.__tablename__}__timestamp", "timestamp", postgresql_using="brin"),
        )


BaseRecordField = BaseUUIDEntityField | BaseItemField | Literal["timestamp"]
BaseRecordOrder = (
    BaseUUIDEntityOrder
    | BaseItemOrder
    | Literal[
        "timestamp",
        "-timestamp",
    ]
)


class BaseRecordFilterArgs[
    FieldT: str,
    OrderT: str,
](
    BaseUUIDEntityFilterArgs[FieldT, OrderT],
    BaseItemFilterArgs[FieldT, OrderT],
    total=False,
):
    before: DateTime | None
    after: DateTime | None
    max_age: PositiveTimeDelta | None
    min_age: PositiveTimeDelta | None


class BaseRecordFilter[
    RecordT: BaseRecord,
    FieldT: str,
    OrderT: str,
](
    BaseUUIDEntityFilter[RecordT, FieldT, OrderT],
    BaseItemFilter[RecordT, FieldT, OrderT],
):
    after: Annotated[DateTime | None, CLIOption(datetime)] = Field(
        default=None,
        description="Filter by minimum timestamp.",
    )
    before: Annotated[DateTime | None, CLIOption(datetime)] = Field(
        default=None,
        description="Filter by maximum timestamp.",
    )
    min_age: Annotated[PositiveTimeDelta | None, CLIOption(str | None, metavar="DURATION")] = Field(
        default=None,
        description="Filter by minimum age relative to the current time.",
    )
    max_age: Annotated[PositiveTimeDelta | None, CLIOption(str | None, metavar="DURATION")] = Field(
        default=None,
        description="Filter by maximum age relative to the current time.",
    )

    @override
    def matches(self, obj: RecordT) -> bool:  # type: ignore
        if not super().matches(obj):
            return False

        now = utc()
        if self.max_age is not None:
            if obj.timestamp < now - self.max_age:
                return False
        if self.min_age is not None:
            if obj.timestamp >= now - self.min_age:
                return False

        if self.after is not None:
            if obj.timestamp < self.after:
                return False
        if self.before is not None:
            if obj.timestamp >= self.before:
                return False

        return True

    @classmethod
    @abstractmethod
    @override
    def _get_row_cls(cls) -> type[BaseRecordRow]: ...

    @override
    def _get_search_content(self, obj: RecordT) -> Mapping[str, str]:
        return {
            **super()._get_search_content(obj),
            "timestamp": util.format_timestamp(obj.timestamp),
        }

    @override
    def _get_database_search_content(
        self,
        dialect: DatabaseType,
    ) -> Mapping[str, SQLColumnExpression[Any]]:
        columns = self._get_row_cls()

        return {
            **super()._get_database_search_content(dialect),
            "timestamp": util.format_sql_timestamp(columns.timestamp, dialect),
        }

    @override
    def _get_where(self, dialect: DatabaseType) -> Iterable[SQLColumnExpression[bool]]:
        yield from super()._get_where(dialect)
        columns = self._get_row_cls()

        now = utc()
        if self.max_age is not None:
            yield columns.timestamp >= now - self.max_age
        if self.min_age is not None:
            yield columns.timestamp < now - self.min_age

        if self.after is not None:
            yield columns.timestamp >= self.after
        if self.before is not None:
            yield columns.timestamp < self.before

    @override
    def _get_default_order(self) -> OrderT:
        return "timestamp"  # type: ignore


class BaseRecordCreate(BaseItem, BaseUUIDEntity):
    timestamp: Annotated[DateTime, CLIOption(datetime)] = Field(default_factory=utc)


class BaseRecordUpdate(BaseUUIDEntityUpdate, BaseItemUpdate, total=False):
    timestamp: DateTime


class BaseRecord(BaseRecordCreate):
    Row: ClassVar[type[BaseRecordRow]] = BaseRecordRow
    Create: ClassVar[type[BaseRecordCreate]] = BaseRecordCreate
    Update: ClassVar[type[BaseRecordUpdate]] = BaseRecordUpdate

    if TYPE_CHECKING:
        Filter: ClassVar = BaseRecordFilter
        FilterArgs: ClassVar = BaseRecordFilterArgs
        Field: ClassVar = BaseRecordField
        Order: ClassVar = BaseRecordOrder
    else:
        Filter: ClassVar[type[BaseRecordFilter]] = BaseRecordFilter
        FilterArgs: ClassVar[type[BaseRecordFilterArgs]] = BaseRecordFilterArgs
        Field: ClassVar[type[BaseRecordField]] = BaseRecordField
        Order: ClassVar[type[BaseRecordOrder]] = BaseRecordOrder
