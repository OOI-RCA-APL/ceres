from __future__ import annotations

import asyncio
import dataclasses
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
    is_typeddict,
    override,
)
from uuid import UUID

from pydantic import ConfigDict, Field, NonNegativeInt, model_validator
from sqlalchemy import (
    Delete,
    Dialect,
    Engine,
    Index,
    Integer,
    Select,
    Update,
    and_,
    delete,
    func,
    literal,
    or_,
    select,
    tuple_,
    update,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, declared_attr, mapped_column
from sqlalchemy.schema import CreateIndex, CreateTable, PrimaryKeyConstraint, SchemaItem, Table

from ceres._internal import util
from ceres._internal.database.types import AddressMapper, DateTimeMapper, UUIDMapper
from ceres._internal.filter import BaseFilter, BaseFilterArgs
from ceres._internal.lazy import lazy_imports
from ceres._internal.manager import BaseDatabaseManager
from ceres.address import Address, AddressSelector
from ceres.data import (
    DateTime,
    DeferBuild,
    FromYAML,
    ImmutableDataObject,
    MaybeSequence,
    NonNegativeTimeDelta,
    PositiveTimeDelta,
    uuid7,
)
from ceres.database import DatabaseType
from ceres.timing import utc

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy import ClauseElement, ColumnElement, ScalarResult, SQLColumnExpression
    from sqlalchemy.ext.asyncio import AsyncScalarResult, AsyncSession
    from sqlalchemy.schema import SchemaItem
    from sqlalchemy.sql.base import ReadOnlyColumnCollection
    from sqlalchemy.sql.dml import ReturningDelete, ReturningUpdate

    from ceres._internal.protocols import DatabaseSource

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

        for index in sorted(cls.__table__.indexes, key=lambda index: str(index.name or "")):
            if index._ddl_if is not None:
                # `DDLif.dialect` can be a tuple of dialect names, despite the type annotation being
                # `str | None` at the time of writing.
                if dialect.name not in util.seq(index._ddl_if.dialect):
                    continue

            yield _compile(dialect, CreateIndex(index, if_not_exists=if_not_exists))

    def values(self) -> dict[str, Any]:
        values = self.__dict__
        return {column: values[column] for column in self.__table__.columns.keys()}

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

    or__: FromYAML[MaybeSequence[FromYAML[Self | BaseEntityFilter[Any, FieldT, OrderT]]] | None]
    and__: FromYAML[MaybeSequence[FromYAML[Self | BaseEntityFilter[Any, FieldT, OrderT]]] | None]


seen: set[int] = set()


class BaseEntityFilter[
    EntityT: BaseEntity,
    FieldT: str,
    OrderT: str,
](BaseFilter):
    order: MaybeSequence[OrderT] | None = None
    """
    Specify ordering of results by field. Prefix field names with '-' for descending order.

    If `and__` subfilters are defined, and `order` is unspecified in this root `order` argument, the
    last `order` defined in `and__` will be used instead.
    """

    limit: NonNegativeInt | None = None

    """
    Limit the number of returned results.

    If any `and__` subfilters are defined, and any of them specify a `limit` which is lower than
    this root `limit` argument, the lowest defined `limit` value in `and__` will be used instead.
    """

    offset: NonNegativeInt | None = None
    """
    Skip over a given number of results.

    If any `and__` subfilters are defined, and any of them specify an `offset` which is higher than
    this root `offset` argument, the highest defined `offset` value in `and__` will be used instead.
    """

    or__: MaybeSequence[FromYAML[Self]] | None = Field(
        default=None,
        validation_alias="or",
        serialization_alias="or",
    )
    """
    One or more subfilters, where in the case any match the queried value, the overall filter should
    match.

    This is a logical OR operation, and can be added to using the `|` operator.

    If both `or__` and `and__` are defined within the same filter object, `and__` is evaluated
    first, meaning whether or not all conditions in `and__` are matched, if any condition in `or__`
    is matched, the overall filter will match.
    """

    and__: MaybeSequence[FromYAML[Self]] | None = Field(
        default=None,
        validation_alias="and",
        serialization_alias="and",
    )
    """
    One or more subfilters, where in the case all of them they match the queried value, the overall
    filter should match.

    This is a logical AND operation, and can be added to using the `&` operator.

    If both `or__` and `and__` are defined within the same filter object, `and__` is evaluated
    first, meaning whether or not all conditions in `and__` are matched, if any condition in `or__`
    is matched, the overall filter will match.
    """

    @classmethod
    @override
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        # This is a hacky workaround for FastAPI not being able to generate query parameters for
        # `Query()`models when `Self` is used in a field's type annotation. Here we just replace the
        # annotations of `or__` and `and__` with the actual concrete type of this filter class.
        super().__pydantic_init_subclass__(**kwargs)
        or__ = cls.__pydantic_fields__["or__"]
        or__.annotation = cast("type[Any]", FromYAML[MaybeSequence[FromYAML[cls]]] | None)
        and__ = cls.__pydantic_fields__["and__"]
        and__.annotation = cast("type[Any]", FromYAML[MaybeSequence[FromYAML[cls]]] | None)

    @model_validator(mode="after")
    def _resolve_and_or(self) -> Self:
        if self.or__:
            for subfilter in util.seq(self.or__):
                if subfilter.order is not None:
                    raise ValueError(
                        "Cannot specify `order` in `or__` subfilters. Use `and__` instead."
                    )
                if subfilter.limit is not None:
                    raise ValueError(
                        "Cannot specify `limit` in `or__` subfilters. Use `and__` instead."
                    )
                if subfilter.offset is not None:
                    raise ValueError(
                        "Cannot specify `offset` in `or__` subfilters. Use `and__` instead."
                    )

        if self.and__:
            for subfilter in util.seq(self.and__):
                if subfilter.order is not None:
                    object.__setattr__(self, "order", subfilter.order)
                    self.model_fields_set.add("order")
                if subfilter.limit is not None:
                    if self.limit is None or subfilter.limit < self.limit:
                        object.__setattr__(self, "limit", subfilter.limit)
                        self.model_fields_set.add("limit")
                if subfilter.offset is not None:
                    if self.offset is None or subfilter.offset > self.offset:
                        object.__setattr__(self, "offset", subfilter.offset)
                        self.model_fields_set.add("offset")

        return self

    def __or__(self, other: Self, /) -> Self:
        # Because `or__` has lower precedence than `and__` within the same filter, we can always
        # just append the filter to the `or__` conditions.
        or__ = [*(self.or__ or ()), other]
        return self.model_copy(update={"or__": or__})

    def __and__(self, other: Self, /) -> Self:
        # Because `and__` has higher precedence than `or__` within the same filter, if `or__` is
        # present, we need create a new parent filter to maintain operator precedence.
        if self.or__ or other.or__:
            return self.__class__(and__=[self, cast("Self", other)])

        # Otherwise, we can append the filter to the `and__` conditions.
        and__ = [*(self.and__ or ()), other]
        return self.model_copy(update={"and__": and__})

    @classmethod
    @abstractmethod
    def _get_row_cls(cls) -> type[BaseEntityRow]: ...

    def matches(self, obj: EntityT) -> bool:
        ands: Sequence[Self] = util.seq(self.and__ or ())
        ors: Sequence[Self] = util.seq(self.or__ or ())

        return (
            self._matches(obj)
            and all(subcondition.matches(obj) for subcondition in ands)
            or any(subcondition.matches(obj) for subcondition in ors)
        )

    @abstractmethod
    def _matches(self, obj: EntityT) -> bool:
        return True

    def _get_combined_where(self, dialect: DatabaseType) -> Iterable[SQLColumnExpression[bool]]:
        ands = list(self._get_where(dialect))

        if self.and__:
            for subcondition in util.seq(self.and__):
                ands.extend(subcondition._get_combined_where(dialect))

        if not self.or__:
            yield from ands
        else:
            ors: list[SQLColumnExpression[bool]] = []
            for subcondition in util.seq(self.or__):
                ors.extend(subcondition._get_combined_where(dialect))

            if ands:
                yield or_(and_(*ands), *ors)
            else:
                yield or_(*ors)

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
        for value in util.seq(order):
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
        where = () if ignore_where else tuple(self._get_combined_where(dialect))
        order_by = () if ignore_order else tuple(self._get_order_by())
        limit = self.limit
        offset = self.offset

        # Opportunistically avoid using subquery filtering if possible.
        if not always_use_subquery:
            if isinstance(statement, Select):
                return statement.where(*where).order_by(*order_by).limit(limit).offset(offset)

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


@dataclasses.dataclass(init=False, slots=True)
class EntityNaming:
    singular: str
    plural: str
    container: str
    table: str
    command: str
    route: str
    manager: str

    def __init__(
        self,
        singular: str,
        *,
        plural: str | None = None,
        container: str | None = None,
        table: str | None = None,
        command: str | None = None,
        route: str | None = None,
        manager: str | None = None,
    ) -> None:
        self.singular = singular
        self.plural = plural if plural else singular + "s"
        self.container = container if container else self.plural
        self.table = table if table else util.snakecase(self.container)
        self.route = route if route else util.kebabcase(self.container)
        self.command = command if command else util.kebabcase(self.container)
        self.manager = manager if manager else util.snakecase(self.container)


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

_EXECUTOR_STREAM_THRESHOLD = 5000
_EXECUTOR_PARSE_YIELD_CONTROL_EVERY = 50


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
        self._stream: AsyncScalarResult[BaseEntityRow] | None = None

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
                self._stream = await self._session.stream_scalars(
                    await self._get_statement(True),
                )

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

        assert self._query._get_resolved_filter().limit == 1
        entities = await self.all()
        return entities[0] if entities else None

    async def all(self) -> list[EntityT]:
        resolved = self._query._get_resolved_filter()
        database = self._query._get_database()
        statement = await self._get_statement(True)

        async with await database.init() as session:
            if resolved.limit is not None and resolved.limit <= _EXECUTOR_STREAM_THRESHOLD:
                result = await session.scalars(statement)
                if self._should_commit():
                    await session.commit()

                entities = await self._parse_rows(result)
            else:
                stream = await session.stream_scalars(statement)
                if self._should_commit():
                    await session.commit()

                entities = [entity async for entity in self._parse_async_rows(stream)]

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

    def _get_parser(self) -> Callable[[BaseEntityRow], EntityT | None]:
        from ceres._internal.util import construct_model

        Entity = self._query._get_entity_class()
        transform = self._query._get_transform()

        def parse(row: BaseEntityRow) -> EntityT | None:
            entity = construct_model(Entity, row.values())
            if transform is not None:
                entity = transform(entity)

            return entity  # type: ignore

        return parse

    async def _parse_rows(
        self,
        rows: ScalarResult[BaseEntityRow],
    ) -> list[EntityT]:
        parse = self._get_parser()
        entities: list[EntityT] = []

        count = 0
        for row in rows:
            entity = parse(row)
            if entity is not None:
                entities.append(entity)

            count += 1
            if count >= _EXECUTOR_PARSE_YIELD_CONTROL_EVERY:
                count = 0
                # Yield control to the event loop.
                await asyncio.sleep(0)
                await asyncio.sleep(0)

        return entities

    async def _parse_async_rows(
        self,
        rows: AsyncScalarResult[BaseEntityRow],
    ) -> AsyncIterator[EntityT]:
        parser = self._get_parser()

        count = 0
        async for row in rows:
            entity = parser(row)
            if entity is not None:
                yield entity

            count += 1
            if count >= _EXECUTOR_PARSE_YIELD_CONTROL_EVERY:
                count = 0
                # Yield control to the event loop.
                await asyncio.sleep(0)
                await asyncio.sleep(0)


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
        statement = select(Row)
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
        super().__init__(query=cast("Any", query))
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
            statement = statement.returning(Row)

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
            statement = statement.returning(Row)

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
        **kwargs: Unpack[BaseEntityFilterArgs],
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

    async def any(self) -> bool:
        database = self._get_database()
        filter = self._get_resolved_filter()
        statement = select("*").select_from(self._get_row_class())
        statement = filter.apply(
            statement,
            database.type,
            ignore_order=True,
            always_use_subquery=filter.limit is not None or filter.offset is not None,
        )
        statement = select(statement.exists())

        async with await database.init() as session:
            results = await session.execute(statement)
            count = results.scalar() or 0
            return count > 0

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
        kwargs: Mapping[str, Any],
    ) -> FilterT:
        Filter = self._get_filter_class()
        return (
            Filter(**cast("Any", kwargs))
            .with_defaults(filter)
            .with_defaults(self._get_resolved_filter())
        )

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
        return await self.select().all()

    async def first(self) -> EntityT | None:
        return await self.select().first()

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
        upsert: bool = False,
    ) -> EntityT:
        result = await self._create_transform(data)
        await self._insert(result, upsert=upsert)
        return result

    async def _insert(
        self,
        data: EntityT,
        *,
        upsert: bool = False,
    ) -> RowT:
        Row = self._get_row_class()
        row = Row(
            **{key: value for key, value in data.__dict__.items() if key in data.model_fields_set}
        )
        match self.__database__.type:
            case DatabaseType.SQLITE:
                from sqlalchemy.dialects.sqlite import insert
            case DatabaseType.POSTGRES:
                from sqlalchemy.dialects.postgresql import insert

        with util.wrap_database_errors():
            async with await self.__database__.init() as session:
                statement = insert(Row).values(row.values())
                pk = Row.get_primary_key_columns()

                if upsert:
                    upsert_columns = {
                        name: column
                        for name, column in statement.excluded.items()
                        if name not in pk
                    }
                    statement = statement.on_conflict_do_update(
                        index_elements=pk,
                        set_=upsert_columns,
                    )

                await session.execute(statement)
                await session.commit()
                return row  # type: ignore


class BaseEntity(BaseEntityCreate):
    Manager: ClassVar[type[BaseEntityManager]] = BaseEntityManager
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


_REQUIRED_CONCRETE_CLASS_ATTRIBUTES: dict[str, type[Any] | None] = {
    "__naming__": EntityNaming,
    "Manager": BaseEntityManager,
    "Row": BaseEntityRow,
    "Create": BaseEntityCreate,
    "Update": BaseEntityUpdate,
    "Filter": BaseEntityFilter,
    "FilterArgs": BaseEntityFilterArgs,
    "Field": None,
    "Order": None,
}


class ConcreteEntity(BaseEntity):
    __naming__: ClassVar[EntityNaming]

    def __init_subclass__(cls, **kwargs: Unpack[ConfigDict]) -> None:
        super().__init_subclass__(**kwargs)
        if cls.__name__.startswith("Base"):
            return

        for attribute, constraint in _REQUIRED_CONCRETE_CLASS_ATTRIBUTES.items():
            value = cls.__dict__.get(attribute)
            if value is None:
                raise TypeError(
                    f"Concrete entity class `{cls.__name__}` must define `{attribute}` as a class attribute."
                )
            elif constraint is not None:
                if is_typeddict(constraint):
                    continue

                if isinstance(value, type):
                    if not issubclass(value, constraint):
                        raise TypeError(
                            f"Concrete entity class `{cls.__name__}` must define `{attribute}` as a subclass of `{constraint.__name__}`."
                        )
                else:
                    if not isinstance(value, constraint):
                        raise TypeError(
                            f"Concrete entity class `{cls.__name__}` must define `{attribute}` as an instance of `{constraint.__name__}`."
                        )

        Filter = cls.__dict__["Filter"]
        try:
            Filter()
        except Exception:
            raise TypeError(f"Filter class `{Filter}` must be constructable with no arguments.")


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
    def _matches(self, obj: EntityT) -> bool:
        if not super()._matches(obj):
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


class BaseAddressEntityRow(BaseEntityRow, kw_only=True):
    __abstract__: ClassVar[bool] = True

    address: Mapped[Address] = mapped_column(AddressMapper, sort_order=-2000)

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            Index(f"ix_{cls.__tablename__}__address", cls.address),
        )


BaseAddressEntityField: TypeAlias = Literal["address"]
BaseAddressEntityOrder: TypeAlias = Literal[
    "address",
    "address:asc",
    "address:desc",
]


class BaseAddressEntityFilterArgs[
    FieldT: str,
    OrderT: str,
](BaseEntityFilterArgs[FieldT, OrderT], total=False):
    root: Address
    address: AddressSelector | str | None


class BaseAddressEntityFilter[
    ItemT: BaseAddressEntity,
    FieldT: str,
    OrderT: str,
](BaseEntityFilter[ItemT, FieldT, OrderT]):
    address: AddressSelector | None = None
    """Filter by `address` matching one or more address selectors."""
    root: Address = Address.ROOT
    """The address which relative address selectors in `address` are relative to."""

    @override
    def _matches(self, obj: ItemT) -> bool:
        if not super()._matches(obj):
            return False

        if self.address is not None:
            if not self.address.matches(obj.address, self.root):
                return False

        return True

    @classmethod
    @abstractmethod
    @override
    def _get_row_cls(cls) -> type[BaseAddressEntityRow]: ...

    @override
    def _get_where(self, dialect: DatabaseType) -> Iterable[SQLColumnExpression[bool]]:
        yield from super()._get_where(dialect)
        columns = self._get_row_cls()

        if self.address is not None:
            yield self.address.matches_expression(columns.address, self.root)


class BaseAddressEntityCreate(BaseEntity):
    address: Address


class BaseAddressEntityUpdate(BaseEntityUpdate, total=False):
    address: Address


class BaseAddressEntity(BaseAddressEntityCreate):
    Row: ClassVar[type[BaseAddressEntityRow]] = BaseAddressEntityRow
    Create: ClassVar[type[BaseAddressEntityCreate]] = BaseAddressEntityCreate
    Update: ClassVar[type[BaseAddressEntityUpdate]] = BaseAddressEntityUpdate

    if TYPE_CHECKING:
        Filter: ClassVar = BaseAddressEntityFilter
        FilterArgs: ClassVar = BaseAddressEntityFilterArgs
        Field: ClassVar = BaseAddressEntityField
        Order: ClassVar = BaseAddressEntityOrder
    else:
        Filter: ClassVar[type[BaseAddressEntityFilter]] = BaseAddressEntityFilter
        FilterArgs: ClassVar[type[BaseAddressEntityFilterArgs]] = BaseAddressEntityFilterArgs
        Field: ClassVar[type[BaseAddressEntityField]] = BaseAddressEntityField
        Order: ClassVar[type[BaseAddressEntityOrder]] = BaseAddressEntityOrder


class BaseTimestampEntityRow(BaseEntityRow):
    __abstract__: ClassVar[bool] = True

    timestamp: Mapped[DateTime] = mapped_column(
        DateTimeMapper,
        sort_order=-1000,
        default_factory=utc,
        server_default=func.now(),
    )

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            Index(f"ix_{cls.__tablename__}__timestamp", "timestamp"),
        )


BaseTimestampEntityField: TypeAlias = Literal["timestamp"]
BaseTimestampEntityOrder: TypeAlias = Literal[
    "timestamp",
    "timestamp:asc",
    "timestamp:desc",
]


class BaseTimestampEntityFilterArgs[
    FieldT: str,
    OrderT: str,
](BaseEntityFilterArgs[FieldT, OrderT], total=False):
    timestamp: MaybeSequence[DateTime] | None
    after: DateTime | None
    before: DateTime | None
    timespan: PositiveTimeDelta | None
    min_age: NonNegativeTimeDelta | None
    max_age: NonNegativeTimeDelta | None
    after_hour: NonNegativeInt | None
    before_hour: NonNegativeInt | None


class BaseTimestampEntityFilter[
    EntityT: BaseTimestampEntity,
    FieldT: str,
    OrderT: str,
](BaseEntityFilter[EntityT, FieldT, OrderT]):
    timestamp: MaybeSequence[DateTime] | None = None
    """Filter by `timestamp` being exactly equal to one or more given datetimes."""
    after: DateTime | None = None
    """Filter by `timestamp` being greater than or equal to a given datetime."""
    before: DateTime | None = None
    """Filter by `timestamp` being less than a given datetime."""

    timespan: PositiveTimeDelta | None = None
    """
    Filter by maximum age relative to `after`, or minimum age relative to `before` if `after` is
    `None`. If both `after` and `before` are `None`, filter by maximum age relative to the current
    time.
    """

    min_age: NonNegativeTimeDelta | None = None
    """
    Filter by the age of `timestamp`, relative to the current time, being greater than or equal to a
    given threshold.
    """

    max_age: NonNegativeTimeDelta | None = None
    """
    Filter by the age of `timestamp`, relative to the current time, being less than a given
    threshold.
    """

    after_hour: NonNegativeInt | None = Field(default=None, le=24)
    """Filter by the hour value of `timestamp` being greater than or equal to a given value."""
    before_hour: NonNegativeInt | None = Field(default=None, le=24)
    """Filter by the hour value of `timestamp` being less than a given value."""
    after_minute: NonNegativeInt | None = Field(default=None, le=60)
    """Filter by the minute value of `timestamp` being greater than or equal to a given value."""
    before_minute: NonNegativeInt | None = Field(default=None, le=60)
    """Filter by the minute of `timestamp` being less than a given value."""

    @override
    def _matches(self, obj: EntityT, *, now: datetime | None = None) -> bool:
        if not super()._matches(obj):
            return False

        if self.timestamp is not None:
            if obj.timestamp not in util.seq(self.timestamp):
                return False
        if self.after is not None:
            if obj.timestamp < self.after:
                return False
        if self.before is not None:
            if obj.timestamp >= self.before:
                return False

        now = utc(now)
        if self.timespan is not None:
            if self.after is not None:
                if obj.timestamp >= (self.after + self.timespan):
                    return False
            elif self.before is not None:
                if obj.timestamp < ((self.before or now) - self.timespan):
                    return False
            else:
                if obj.timestamp < now - self.timespan:
                    return False
                if obj.timestamp >= now:
                    return False

        if self.max_age is not None:
            if obj.timestamp <= now - self.max_age:
                return False
        if self.min_age is not None:
            if obj.timestamp > now - self.min_age:
                return False

        if self.after_hour is not None or self.before_hour is not None:
            if obj.timestamp is None:
                return False

            min_hour = self.after_hour if self.after_hour is not None else 0
            max_hour = self.before_hour if self.before_hour is not None else 24
            within_min = obj.timestamp.hour >= min_hour
            within_max = obj.timestamp.hour < max_hour
            if min_hour <= max_hour:
                if not within_min or not within_max:
                    return False
            else:
                if not within_min and not within_max:
                    return False

        if self.after_minute is not None or self.before_minute is not None:
            if obj.timestamp is None:
                return False

            min_minute = self.after_minute if self.after_minute is not None else 0
            max_minute = self.before_minute if self.before_minute is not None else 60
            within_min = obj.timestamp.minute >= min_minute
            within_max = obj.timestamp.minute < max_minute
            if min_minute <= max_minute:
                if not within_min or not within_max:
                    return False
            else:
                if not within_min and not within_max:
                    return False

        return True

    @classmethod
    @abstractmethod
    @override
    def _get_row_cls(cls) -> type[BaseTimestampEntityRow]: ...

    @override
    def _get_where(
        self,
        dialect: DatabaseType,
        *,
        now: datetime | None = None,
    ) -> Iterable[SQLColumnExpression[bool]]:
        yield from super()._get_where(dialect)
        columns = self._get_row_cls()

        from sqlalchemy import cast

        if self.timestamp is not None:
            yield util.sql_match_value(columns.timestamp, self.timestamp)
        if self.after is not None:
            yield columns.timestamp >= self.after
        if self.before is not None:
            yield columns.timestamp < self.before

        now = utc(now)
        if self.timespan is not None:
            if self.after is not None:
                yield columns.timestamp < self.after + self.timespan
            elif self.before is not None:
                yield columns.timestamp >= self.before - self.timespan
            else:
                yield columns.timestamp >= now - self.timespan
                yield columns.timestamp < now

        if self.max_age is not None:
            yield columns.timestamp > now - self.max_age
        if self.min_age is not None:
            yield columns.timestamp <= now - self.min_age

        if self.after_hour is not None or self.before_hour is not None:
            min_hour = self.after_hour if self.after_hour is not None else 0
            max_hour = self.before_hour if self.before_hour is not None else 24
            match dialect:
                case DatabaseType.POSTGRES:
                    hour = func.date_part(
                        literal("hour", literal_execute=True),
                        columns.timestamp.op("AT TIME ZONE")(literal("UTC", literal_execute=True)),
                    )
                case DatabaseType.SQLITE:
                    hour = cast(func.strftime("%H", columns.timestamp), Integer)

            within_min = hour >= min_hour
            within_max = hour < max_hour
            if min_hour <= max_hour:
                yield within_min & within_max
            else:
                yield within_min | within_max

        if self.after_minute is not None or self.before_minute is not None:
            min_minute = self.after_minute if self.after_minute is not None else 0
            max_minute = self.before_minute if self.before_minute is not None else 60
            match dialect:
                case DatabaseType.POSTGRES:
                    minute = func.date_part(
                        literal("minute", literal_execute=True),
                        columns.timestamp.op("AT TIME ZONE")(literal("UTC", literal_execute=True)),
                    )
                case DatabaseType.SQLITE:
                    minute = cast(func.strftime("%M", columns.timestamp), Integer)

            within_min = minute >= min_minute
            within_max = minute < max_minute
            if min_minute <= max_minute:
                yield within_min & within_max
            else:
                yield within_min | within_max

    @override
    def _get_default_order(self) -> MaybeSequence[OrderT]:
        return "timestamp"  # type: ignore

    def _get_time_bounds(self, now: datetime) -> tuple[datetime | None, datetime | None]:
        starts: list[datetime] = []
        ends: list[datetime] = []

        if self.after is not None:
            starts.append(self.after)
        if self.before is not None:
            ends.append(self.before)

        if self.timespan is not None:
            if self.after is not None:
                ends.append(self.after + self.timespan)
            elif self.before is not None:
                starts.append(self.before - self.timespan)
            else:
                starts.append(now - self.timespan)
                ends.append(now)

        if self.max_age is not None:
            starts.append(now - self.max_age)
        if self.min_age is not None:
            ends.append(now - self.min_age)

        start = max(starts) if starts else None
        end = min(ends) if ends else None

        return start, end


class BaseTimestampEntityCreate(BaseEntity):
    timestamp: DateTime = Field(default_factory=utc)


class BaseTimestampEntityUpdate(BaseEntityUpdate, total=False):
    timestamp: DateTime


class BaseTimestampEntity(BaseTimestampEntityCreate):
    Row: ClassVar[type[BaseTimestampEntityRow]] = BaseTimestampEntityRow
    Create: ClassVar[type[BaseTimestampEntityCreate]] = BaseTimestampEntityCreate
    Update: ClassVar[type[BaseTimestampEntityUpdate]] = BaseTimestampEntityUpdate

    if TYPE_CHECKING:
        Filter: ClassVar = BaseTimestampEntityFilter
        FilterArgs: ClassVar = BaseTimestampEntityFilterArgs
        Field: ClassVar = BaseTimestampEntityField
        Order: ClassVar = BaseTimestampEntityOrder
    else:
        Filter: ClassVar[type[BaseTimestampEntityFilter]] = BaseTimestampEntityFilter
        FilterArgs: ClassVar[type[BaseTimestampEntityFilterArgs]] = BaseTimestampEntityFilterArgs
        Field: ClassVar[type[BaseTimestampEntityField]] = BaseTimestampEntityField
        Order: ClassVar[type[BaseTimestampEntityOrder]] = BaseTimestampEntityOrder
