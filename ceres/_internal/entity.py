from __future__ import annotations

from abc import ABC, abstractmethod
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    ClassVar,
    Final,
    Generator,
    Iterable,
    Literal,
    Mapping,
    Self,
    Sequence,
    TypeAlias,
    TypedDict,
    Unpack,
    cast,
    final,
    override,
)
from uuid import UUID

from pydantic import Field, NonNegativeInt
from sqlalchemy import (
    ClauseElement,
    Column,
    ColumnElement,
    Delete,
    Dialect,
    Engine,
    Result,
    Select,
    SQLColumnExpression,
    Update,
    delete,
    func,
    select,
    tuple_,
    update,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, declared_attr, mapped_column
from sqlalchemy.schema import CreateIndex, CreateTable, PrimaryKeyConstraint, SchemaItem, Table
from sqlalchemy.sql.base import ReadOnlyColumnCollection
from sqlalchemy.sql.dml import ReturningDelete, ReturningUpdate
from sqlalchemy.sql.roles import DDLConstraintColumnRole

from ceres._internal import util
from ceres._internal.database.types import UUIDMapper
from ceres._internal.filter import BaseFilter, BaseFilterArgs
from ceres._internal.lazy import lazy_imports
from ceres._internal.manager import BaseDatabaseManager
from ceres._internal.protocols import DatabaseSource
from ceres.data import DeferBuild, ImmutableDataObject, MaybeSequence, uuid7
from ceres.database import DatabaseType

with lazy_imports(__name__):
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncResult, AsyncSession


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
    def get_columns(cls) -> ReadOnlyColumnCollection[str, ColumnElement[Any]]:
        return cls.__table__.columns

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
    def _get_default_order(self) -> MaybeSequence[OrderT]: ...

    def _get_order_by(self) -> tuple[SQLColumnExpression[Any], ...]:
        order = self.order
        if order is None:
            order = self._get_default_order()

        Row = self._get_row_cls()
        columns: list[SQLColumnExpression[Any]] = []
        for value in util.as_sequence(order):
            base = value.split(":")[0]
            ascending = not value.endswith(":desc")
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
                if limit is None and offset is None and not statement._returning:
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
BaseUUIDEntityOrder: TypeAlias = Literal[
    "id",
    "id:asc",
    "id:desc",
]


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

        if not util.match_value(obj.id, self.id):
            return False

        return True

    @override
    def _get_where(self, dialect: DatabaseType) -> Iterable[SQLColumnExpression[bool]]:
        yield from super()._get_where(dialect)
        columns = self._get_row_cls()

        if self.id is not None:
            yield util.sql_match_value(columns.id, self.id)


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


if TYPE_CHECKING:
    from ceres.database import Database


class ResultsIterator[EntityT: BaseEntity]:
    __slots__ = ("_results",)

    def __init__(self, results: AsyncIterator[EntityT]) -> None:
        self._results: Final = results

    def __aiter__(self) -> ResultsIterator[EntityT]:
        return self

    async def __anext__(self) -> EntityT:
        return await anext(self._results)

    async def first(self) -> EntityT | None:
        try:
            return await anext(self)
        except StopAsyncIteration:
            return None

    async def all(self) -> list[EntityT]:
        return [result async for result in self]


type EntityTransform[EntityT] = Callable[[EntityT], BaseEntity | None]
type EntityParser[EntityT] = Callable[[Any], EntityT | None]


class _BaseStatementExecutor[
    EntityT: BaseEntity,
    FilterT: BaseEntityFilter[Any, Any, Any],
    AwaitT,
](ABC):
    __slots__ = (
        "_query",
        "_session",
        "_stream",
    )

    def __init__(
        self,
        *,
        query: EntityQuery[EntityT, FilterT, BaseEntityUpdate],
    ) -> None:
        self._query: Final = query
        self._session: AsyncSession | None = None
        self._stream: AsyncResult[Any] | None = None

    @override
    def __eq__(self, value: object, /) -> bool:
        if type(value) is not type(self):
            return False

        return self._query == value._query

    def __await__(self) -> Generator[Any, Any, AwaitT]:
        return self._await().__await__()

    async def __aenter__(self) -> ResultsIterator[EntityT]:
        with util.wrap_database_errors():
            if self._session is None:
                self._session = await self._query._get_database().init()
            if self._stream is None:
                self._stream = await self._session.stream(await self._get_statement(True))

        return ResultsIterator(self._parse_async_rows(self._stream))

    async def __aexit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        try:
            if self._stream is not None:
                await self._stream.close()
        finally:
            self._stream = None
            if self._session is not None:
                if exc_type is None and self._should_commit():
                    await self._session.commit()
                try:
                    await self._session.__aexit__(exc_type, exc_value, traceback)
                finally:
                    self._session = None

    def limit(self, limit: int) -> Self:
        return self._with_query(self._query.limit(limit))

    def offset(self, offset: int) -> Self:
        return self._with_query(self._query.offset(offset))

    async def first(self) -> EntityT | None:
        resolved = self._query._get_resolved_filter()
        if resolved.limit is None or resolved.limit > 1:
            self = self.limit(1)

        entities = await self.all()
        return entities[0] if entities else None

    async def all(self) -> list[EntityT]:
        database = self._query._get_database()
        statement = await self._get_statement(True)

        async with await database.init() as session:
            result = await session.execute(statement)
            if self._should_commit():
                await session.commit()

            entities = list(self._parse_rows(result))
            return entities

    @abstractmethod
    def _should_commit(self) -> bool: ...

    @abstractmethod
    def _with_query(
        self,
        query: EntityQuery[EntityT, FilterT, BaseEntityUpdate],
    ) -> Self: ...

    @abstractmethod
    async def _await(self) -> AwaitT: ...

    @abstractmethod
    async def _get_statement(
        self,
        returning: bool,
    ) -> Select[Any] | Update | ReturningUpdate | Delete | ReturningDelete: ...

    def _get_parser(self) -> Callable[[Any], EntityT | None]:
        from ceres._internal.util import construct_model

        Entity = self._query._get_entity_class()
        transform = self._query._get_transform()

        def parse(row: Any) -> EntityT | None:
            entity = construct_model(Entity, row._mapping)
            if transform is not None:
                entity = transform(entity)

            return entity  # type: ignore

        return parse

    async def _parse_async_rows(self, rows: AsyncResult[Any]) -> AsyncIterator[EntityT]:
        parser = self._get_parser()

        async for row in rows:
            entity = parser(row)
            if entity is not None:
                yield entity

    def _parse_rows(self, rows: Result[Any]) -> list[EntityT]:
        parse = self._get_parser()

        collected: Sequence[Any] = rows.all()
        if not isinstance(collected, list):
            collected = list(collected)

        count = 0
        for row in collected:
            entity = parse(row)
            if entity is not None:
                collected[count] = entity
                count += 1

        del collected[count:]

        return collected


class SelectExecutor[
    EntityT: BaseEntity,
    FilterT: BaseEntityFilter[Any, Any, Any],
](_BaseStatementExecutor[EntityT, FilterT, list[EntityT]]):
    @override
    async def _await(self) -> list[EntityT]:
        return await self.all()

    @override
    async def _get_statement(self, returning: bool = True) -> Select[tuple[Any]]:
        Row = self._query._get_row_class()
        database = self._query._get_database()
        statement = select(*Row.get_columns())
        statement = self._query._get_resolved_filter().apply(statement, database.type)
        return statement

    @override
    def _should_commit(self) -> bool:
        return False

    @override
    def _with_query(
        self,
        query: EntityQuery[EntityT, FilterT, BaseEntityUpdate],
    ) -> SelectExecutor[EntityT, FilterT]:
        return SelectExecutor(query=query)


class UpdateExecutor[
    EntityT: BaseEntity,
    FilterT: BaseEntityFilter[Any, Any, Any],
    UpdateT: BaseEntityUpdate,
](_BaseStatementExecutor[EntityT, FilterT, int]):
    __slots__ = ("_assign",)

    def __init__(
        self,
        *,
        query: EntityQuery[EntityT, FilterT, UpdateT],
        assign: UpdateT,
        assign_transform: Callable[[UpdateT], Awaitable[UpdateT]] | None = None,
    ) -> None:
        self._query: Final = query  # type: ignore
        self._assign: Final = assign

    @override
    def __eq__(self, value: object, /) -> bool:
        if not super().__eq__(value):
            return False

        assert isinstance(value, UpdateExecutor)
        return self._assign == value._assign

    @override
    async def _await(self) -> int:
        database = self._query._get_database()
        statement = await self._get_statement(False)

        with util.wrap_database_errors():
            async with await database.init() as session:
                result = await session.execute(statement)
                await session.commit()
                return result.rowcount

    @override
    async def _get_statement(self, returning: bool) -> Update | ReturningUpdate:
        Row = self._query._get_row_class()
        database = self._query._get_database()
        assign = await self._query._assign_transform(self._assign)

        statement = update(Row).values(assign)
        if returning:
            statement = statement.returning(*Row.get_columns())

        statement = self._query._get_resolved_filter().apply(statement, database.type)
        return statement

    @override
    def _should_commit(self) -> bool:
        return True

    @override
    def _with_query(
        self,
        query: EntityQuery[EntityT, FilterT, BaseEntityUpdate],
    ) -> UpdateExecutor[EntityT, FilterT, UpdateT]:
        return cast(
            "UpdateExecutor[EntityT, FilterT, UpdateT]",
            UpdateExecutor(query=query, assign=self._assign),
        )


class DeleteExecutor[
    EntityT: BaseEntity,
    FilterT: BaseEntityFilter[Any, Any, Any],
](_BaseStatementExecutor[EntityT, FilterT, int]):
    @override
    async def _await(self) -> int:
        database = self._query._get_database()
        statement = await self._get_statement(False)

        with util.wrap_database_errors():
            async with await database.init() as session:
                result = await session.execute(statement)
                await session.commit()
                return result.rowcount

    @override
    async def _get_statement(self, returning: bool) -> Delete | ReturningDelete:
        Row = self._query._get_row_class()
        database = self._query._get_database()

        statement = delete(Row)
        if returning:
            statement = statement.returning(*Row.get_columns())

        statement = self._query._get_resolved_filter().apply(statement, database.type)
        return statement

    @override
    def _should_commit(self) -> bool:
        return True

    @override
    def _with_query(
        self,
        query: EntityQuery[EntityT, FilterT, BaseEntityUpdate],
    ) -> DeleteExecutor[EntityT, FilterT]:
        return DeleteExecutor(query=query)


class BaseEntityQuery[
    EntityT: BaseEntity,
    FilterT: BaseEntityFilter[Any, Any, Any],
    UpdateT: BaseEntityUpdate,
    QueryT: EntityQuery[Any, Any, Any],
](ABC):
    __slots__ = ()

    def where(
        self,
        filter: FilterT | None = None,
        **kwargs: Unpack[BaseEntityFilterArgs[Any, Any]],
    ) -> QueryT:
        filter = self._get_resolved_filter_args(filter, kwargs)
        return self._get_query_class()(
            database=self._get_database(),
            entity_class=self._get_entity_class(),
            filter=filter,
            filter_defaults=self._get_filter_defaults(),
        )

    def select(self) -> SelectExecutor[EntityT, FilterT]:
        return SelectExecutor(query=self.where())

    def update(self, assign: UpdateT) -> UpdateExecutor[EntityT, FilterT, UpdateT]:
        return UpdateExecutor(query=self.where(), assign=assign)

    def delete(self) -> DeleteExecutor[EntityT, FilterT]:
        return DeleteExecutor(query=self.where())

    async def count(self) -> int:
        database = self._get_database()
        filter = self._get_resolved_filter()
        statement = select(func.count()).select_from(self._get_row_class())
        statement = filter.apply(
            statement,
            database.type,
            ignore_order=True,
            always_use_subquery=filter.limit is not None or filter.offset is not None,
        )

        async with await database.init() as session:
            results = await session.execute(statement)
            return results.scalar() or 0

    @abstractmethod
    def _get_database(self) -> Database: ...

    @abstractmethod
    def _get_entity_class(self) -> type[EntityT]: ...

    @abstractmethod
    def _get_filter(self) -> FilterT: ...

    @abstractmethod
    def _get_filter_defaults(self) -> FilterT: ...

    @abstractmethod
    def _get_transform(self) -> EntityTransform[EntityT] | None: ...

    @abstractmethod
    def _get_query_class(self) -> type[QueryT]: ...

    @final
    def _get_filter_class(self) -> type[FilterT]:
        return self._get_entity_class().Filter  # type: ignore

    @final
    def _get_row_class(self) -> type[BaseEntityRow]:
        return self._get_entity_class().Row

    def _get_resolved_filter(self) -> FilterT:
        filter = self._get_filter()
        filter = filter.with_defaults(self._get_filter_defaults())
        return filter

    def _get_resolved_filter_args(
        self,
        filter: FilterT | None,
        kwargs: BaseEntityFilterArgs,
    ) -> FilterT:
        Filter = self._get_filter_class()
        return Filter(**kwargs).with_defaults(filter).with_defaults(self._get_resolved_filter())

    async def _assign_transform(self, assign: UpdateT) -> UpdateT:
        return assign


class EntityQuery[
    EntityT: BaseEntity,
    FilterT: BaseEntityFilter[Any, Any, Any],
    UpdateT: BaseEntityUpdate,
](
    BaseEntityQuery[
        EntityT,
        FilterT,
        UpdateT,
        "EntityQuery[EntityT, FilterT, UpdateT]",
    ]
):
    __slots__ = (
        "_database",
        "_entity_class",
        "_filter",
        "_filter_defaults",
        "_select_executor",
    )

    def __init__(
        self,
        *,
        database: Database,
        entity_class: type[EntityT],
        filter: FilterT | None,
        filter_defaults: FilterT | None,
    ) -> None:
        self._database: Final = database
        self._entity_class: Final = entity_class
        self._filter: Final = filter
        self._filter_defaults: Final = filter_defaults
        self._select_executor: SelectExecutor | None = None

    @override
    def __eq__(self, value: object, /) -> bool:
        if type(value) is not type(self):
            return False

        return (
            self._database == value._database
            and self._entity_class == value._entity_class
            and self._filter == value._filter
            and self._filter_defaults == value._filter_defaults
        )

    def __await__(self) -> Generator[Any, Any, list[EntityT]]:
        return self.select().__await__()

    async def __aenter__(self) -> ResultsIterator[EntityT]:
        self._select_executor = self.select()
        return await self._select_executor.__aenter__()

    async def __aexit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        if self._select_executor is not None:
            try:
                await self._select_executor.__aexit__(exc_type, exc_value, traceback)
            finally:
                self._select_executor = None

    async def all(self) -> list[EntityT]:
        async with self as results:
            return await results.all()

    async def first(self) -> EntityT | None:
        resolved = self._get_resolved_filter()
        if resolved.limit is None or resolved.limit > 1:
            self = self.limit(1)

        assert self._filter is not None and self._filter.limit == 1
        async with self as results:
            return await results.first()

    def limit(self, limit: int) -> Self:
        return self.where(limit=limit)  # type: ignore

    def offset(self, offset: int) -> Self:
        return self.where(offset=offset)  # type: ignore

    @override
    def _get_database(self) -> Database:
        return self._database

    @override
    def _get_entity_class(self) -> type[EntityT]:
        return self._entity_class

    @override
    def _get_filter(self) -> FilterT:
        if self._filter is not None:
            return self._filter

        return self._get_filter_class()()

    @override
    def _get_filter_defaults(self) -> FilterT:
        if self._filter_defaults is None:
            return self._get_filter_class()()

        return self._filter_defaults

    @override
    def _get_transform(self) -> EntityTransform[EntityT] | None:
        return None


class BaseEntityManager[
    EntityT: BaseEntity,
    RowT: BaseEntityRow,
    CreateT: BaseEntityCreate,
    UpdateT: BaseEntityUpdate,
    FilterT: BaseEntityFilter[Any, Any, Any],
    FilterArgsT: BaseEntityFilterArgs[Any, Any],
](
    BaseDatabaseManager,
    BaseEntityQuery[
        EntityT,
        FilterT,
        UpdateT,
        EntityQuery[
            EntityT,
            FilterT,
            UpdateT,
        ],
    ],
):
    __slots__ = ("_entity_class",)

    @override
    def __init__(self, source: DatabaseSource, cls: type[EntityT], /) -> None:
        super().__init__(source)
        self._entity_class: Final = cls

    @override
    def _get_database(self) -> Database:
        return self.__database__

    @override
    def _get_entity_class(self) -> type[EntityT]:
        return self._entity_class

    @override
    def _get_filter(self) -> FilterT:
        return self._get_filter_class()()

    @override
    def _get_filter_defaults(self) -> FilterT:
        Filter = self._get_filter_class()
        return util.call_partial(Filter, **self.__get_filter_defaults__())

    @override
    def _get_transform(self) -> EntityTransform[EntityT] | None:
        return None

    async def _create_transform(self, data: CreateT) -> EntityT:
        if isinstance(data, self._entity_class):
            return data

        return self._entity_class(**data.__dict__)

    async def create(
        self,
        data: CreateT,
        *,
        upsert_on: Sequence[str | ColumnElement[Any] | DDLConstraintColumnRole] | None = None,
    ) -> EntityT:
        result = await self._create_transform(data)
        await self._insert(result, upsert_on=upsert_on)
        return result

    async def _insert(
        self,
        data: EntityT,
        *,
        upsert_on: Sequence[str | Column[Any] | DDLConstraintColumnRole] | None = None,
    ) -> RowT:
        Row = self._get_row_class()
        row = Row(**data.__dict__)
        match self.__database__.type:
            case DatabaseType.SQLITE:
                from sqlalchemy.dialects.sqlite import insert
            case DatabaseType.POSTGRES:
                from sqlalchemy.dialects.postgresql import insert

        with util.wrap_database_errors():
            async with await self.__database__.init() as session:
                statement = insert(Row).values(row.values())
                pk = Row.get_primary_key_columns()

                if upsert_on is not None:
                    upsert = {
                        name: column
                        for name, column in statement.excluded.items()
                        if name not in pk
                    }
                    statement = statement.on_conflict_do_update(
                        index_elements=upsert_on,
                        set_=upsert,
                    )

                await session.execute(statement)
                await session.commit()
                return row  # type: ignore
