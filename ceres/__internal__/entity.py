import dataclasses
from abc import ABC, abstractmethod
from collections.abc import (
    AsyncIterator,
    Awaitable,
    Callable,
    Generator,
    Iterable,
    Mapping,
    Sequence,
)
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Final,
    Literal,
    Self,
    TypeAlias,
    TypedDict,
    Unpack,
    cast,
    final,
    is_typeddict,
    override,
)
from uuid import UUID

from pydantic import Field, NonNegativeInt, model_validator
from sqlalchemy import (
    ClauseElement,
    Delete,
    Dialect,
    Engine,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Result,
    Row,
    Select,
    SQLColumnExpression,
    Table,
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
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncResult
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, declared_attr, mapped_column
from sqlalchemy.schema import CreateIndex, CreateTable, SchemaItem

from ceres.__internal__.database.errors import wrap_database_errors
from ceres.__internal__.database.types import AddressMapper, DateTimeMapper, UUIDMapper
from ceres.__internal__.filter import BaseFilter, BaseFilterArgs
from ceres.__internal__.manager import BaseDatabaseManager
from ceres.__internal__.utilities.case import kebabcase, snakecase
from ceres.__internal__.utilities.classes import cached_class_property
from ceres.__internal__.utilities.collections import seq
from ceres.__internal__.utilities.functions import call_partial
from ceres.__internal__.utilities.typing import get_generic_superclass_argument
from ceres.address import Address, AddressSelector
from ceres.channel import OutputChannel
from ceres.concurrency import sleep
from ceres.data import (
    DataObject,
    DateTime,
    FromYAML,
    MaybeSequence,
    NonNegativeTimeDelta,
    PositiveTimeDelta,
    create,
    uuid7,
)
from ceres.database import DatabaseType
from ceres.timing import utc

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.sql.dml import ReturningDelete, ReturningUpdate

    from ceres.__internal__.protocols import DatabaseSource
    from ceres.database import Database
    from ceres.entity import Entity
    from ceres.node import Node

    _Rows = Result[tuple[object, ...]]
    _AsyncRows: TypeAlias = AsyncResult[tuple[object, ...]]


class BaseEntityRow(
    MappedAsDataclass,
    DeclarativeBase,
    kw_only=True,
):
    """Abstract SQLAlchemy declarative base for entity table rows.

    Provide DDL generation helpers for creating tables and indexes, and a ``values`` method
    that extracts column data as a plain dict.
    """

    __abstract__: ClassVar[bool] = True
    __mapper_args__: ClassVar[Mapping[str, Any]] = {
        "eager_defaults": True,
    }

    if TYPE_CHECKING:
        __tablename__: ClassVar[str]
        __table__: ClassVar[Table]

    @classmethod
    def get_ddl(
        cls,
        dialect: Dialect | Engine | AsyncEngine,
        *,
        table: bool = True,
        indexes: bool = True,
        if_not_exists: bool = True,
    ) -> Iterable[str]:
        """Yield compiled DDL statements for creating this row's table and indexes.

        Args:
            dialect: The SQLAlchemy dialect (or engine) to compile against.
            table: Include the ``CREATE TABLE`` statement when ``True``.
            indexes: Include ``CREATE INDEX`` statements when ``True``.
            if_not_exists: Use ``IF NOT EXISTS`` in the generated DDL when ``True``.

        Yields:
            DDL statement strings ready for execution.
        """
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
        """Compile and return the ``CREATE TABLE`` DDL statement for this row class.

        Args:
            dialect: The SQLAlchemy dialect (or engine) to compile against.
            name: Override the table name in the generated DDL, or ``None`` to use the
                default.
            temporary: Produce a ``CREATE TEMPORARY TABLE`` statement when ``True``.
            if_not_exists: Use ``IF NOT EXISTS`` in the generated DDL when ``True``.

        Returns:
            A single DDL string ending with a trailing semicolon.
        """
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
        """Yield compiled ``CREATE INDEX`` DDL statements for this row's table indexes.

        Skip indexes whose ``_ddl_if`` dialect constraint does not match the given dialect.

        Args:
            dialect: The SQLAlchemy dialect (or engine) to compile against.
            if_not_exists: Use ``IF NOT EXISTS`` in the generated DDL when ``True``.

        Yields:
            DDL statement strings, one per applicable index, sorted by index name.
        """
        if isinstance(dialect, Engine | AsyncEngine):
            dialect = dialect.dialect

        for index in sorted(cls.__table__.indexes, key=lambda index: str(index.name or "")):
            if index._ddl_if is not None:
                # `DDLif.dialect` can be a tuple of dialect names, despite the type annotation being
                # `str | None` at the time of writing.
                if dialect.name not in seq(index._ddl_if.dialect):
                    continue

            yield _compile(dialect, CreateIndex(index, if_not_exists=if_not_exists))

    def values(self) -> dict[str, Any]:
        """Return this row's column values as a plain dictionary keyed by column name."""
        __dict__ = self.__dict__
        return {column.name: __dict__[column.name] for column in self.__table__.columns}

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
    """Compile a SQLAlchemy DDL element into a formatted, semicolon-terminated string.

    Args:
        dialect: The SQLAlchemy dialect (or engine) to compile against.
        element: The DDL clause element to compile.

    Returns:
        A cleaned-up DDL string with normalized indentation and a trailing semicolon.
    """
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
    """TypedDict for keyword arguments accepted by entity filter constructors."""

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
    """Base filter for entity queries, supporting ordering, pagination, and boolean composition.

    Subfilters can be combined with ``|`` (OR) and ``&`` (AND) operators. The ``and__`` group
    is evaluated first, then ``or__``, so ``A & B | C`` matches when (A and B) or C.
    """

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

        # The core schema is already built by this point, so it still validates subfilters against
        # the inherited annotation. Rebuild so subfilters accept the fields this subclass declares.
        cls.model_rebuild(force=True)

    @model_validator(mode="after")
    def _resolve_and_or(self) -> Self:
        if self.or__:
            for subfilter in seq(self.or__):
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
            for subfilter in seq(self.and__):
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
            return self.__class__(and__=cast("Any", [self, other]))

        # Otherwise, we can append the filter to the `and__` conditions.
        and__ = [*(self.and__ or ()), other]
        return self.model_copy(update={"and__": and__})

    @classmethod
    @abstractmethod
    def _get_row_cls(cls) -> type[BaseEntityRow]: ...

    def matches(self, obj: EntityT) -> bool:
        """Test whether `obj` satisfies this filter, including all ``and__`` and ``or__`` subfilters.

        Args:
            obj: The entity to test against this filter.

        Returns:
            ``True`` if the entity matches.
        """
        ands: Sequence[Self] = seq(self.and__ or ())
        ors: Sequence[Self] = seq(self.or__ or ())

        return (
            self._matches(obj)
            and all(subcondition.matches(obj) for subcondition in ands)
            or any(subcondition.matches(obj) for subcondition in ors)
        )

    @abstractmethod
    def _matches(self, obj: EntityT) -> bool:
        return True

    def _get_combined_where(self, dialect: DatabaseType) -> Iterable[SQLColumnExpression[bool]]:
        """Yield SQL ``WHERE`` clauses combining this filter with its ``and__`` and ``or__`` groups.

        Args:
            dialect: The database dialect, used to generate dialect-specific expressions.

        Yields:
            Boolean column expressions to be applied to a query.
        """
        ands = list(self._get_where(dialect))

        if self.and__:
            for subcondition in seq(self.and__):
                ands.extend(subcondition._get_combined_where(dialect))

        if not self.or__:
            yield from ands
        else:
            ors: list[SQLColumnExpression[bool]] = []
            for subcondition in seq(self.or__):
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
        """Build the ``ORDER BY`` column tuple from this filter's ``order`` (or the default)."""
        order = self.order
        if order is None:
            order = self._get_default_order()

        Row = self._get_row_cls()
        columns: list[SQLColumnExpression[Any]] = []
        for value in seq(order):
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
        """Apply this filter's ``WHERE``, ``ORDER BY``, ``LIMIT``, and ``OFFSET`` to `statement`.

        For ``UPDATE`` and ``DELETE`` statements that include ``LIMIT``/``OFFSET`` or
        ``RETURNING``, a primary-key subquery is used because those statements cannot
        directly carry ordering and pagination.

        Args:
            statement: A SQLAlchemy ``SELECT``, ``UPDATE``, or ``DELETE`` statement.
            dialect: The database dialect, used for dialect-specific SQL generation.
            always_use_subquery: Force subquery filtering even when it could be avoided.
            ignore_where: Skip applying ``WHERE`` clauses.
            ignore_order: Skip applying ``ORDER BY``.

        Returns:
            The modified statement with filter criteria applied.
        """
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

        pk = self._get_row_cls().__table__.primary_key.columns
        pks = select(*pk).where(*where).order_by(*order_by).limit(limit).offset(offset)

        pk = pk[0] if len(pk) == 1 else tuple_(*pk)

        if isinstance(statement, Update | Delete):
            return statement.where(pk.in_(pks))

        return statement.where(pk.in_(pks)).order_by(*order_by)


class BaseEntityCreate(DataObject, abstract=True, slots=True):
    """Abstract base for entity creation data objects."""

    pass


class BaseEntityUpdate(TypedDict, total=False):
    """Base TypedDict for entity update payloads (fields that can be modified)."""

    pass


@dataclasses.dataclass(init=False, slots=True)
class EntityNaming:
    """Derive conventional names (table, route, CLI command, etc.) from an entity's singular name.

    All fields besides ``singular`` are auto-generated from ``singular`` when not explicitly
    provided. For example, ``EntityNaming("alert")`` produces ``plural="alerts"``,
    ``table="alerts"``, ``route="alerts"``, and so on.
    """

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
        self.table = table if table else snakecase(self.container)
        self.route = route if route else kebabcase(self.container)
        self.command = command if command else kebabcase(self.container)
        self.manager = manager if manager else snakecase(self.container)


class ResultsIterator[EntityT: BaseEntity]:
    """Async iterator over entity query results with convenience methods for first/all."""

    __slots__ = ("_results",)

    def __init__(self, results: AsyncIterator[EntityT]) -> None:
        self._results: Final = results

    def __aiter__(self) -> ResultsIterator[EntityT]:
        return self

    async def __anext__(self) -> EntityT:
        return await self._results.__anext__()

    async def first(self) -> EntityT | None:
        """Return the next entity, or ``None`` if the iterator is exhausted."""
        try:
            return await self.__anext__()
        except StopAsyncIteration:
            return None

    async def all(self) -> list[EntityT]:
        """Consume the iterator and return all remaining entities as a list."""
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
    """Abstract executor that runs a SQL statement against an entity query.

    Support three consumption modes: ``await`` for the default result, async context manager
    for streaming iteration, and explicit ``first``/``all`` methods. Subclasses define the
    concrete statement (select, update, or delete) and what ``await`` resolves to.
    """

    __slots__ = (
        "_query",
        "_connection",
        "_stream",
    )

    def __init__(
        self,
        *,
        query: EntityQuery[EntityT, FilterT, BaseEntityUpdate],
    ) -> None:
        self._query: Final = query
        self._connection: AsyncConnection | None = None
        self._stream: _AsyncRows | None = None

    @override
    def __eq__(self, value: object, /) -> bool:
        if type(value) is not type(self):
            return False

        return self._query == value._query

    def __await__(self) -> Generator[Any, Any, AwaitT]:
        return self._await().__await__()

    async def __aenter__(self) -> ResultsIterator[EntityT]:
        with wrap_database_errors():
            if self._connection is None:
                self._connection = await self._query._get_database().use()
                await self._connection.__aenter__()
            if self._stream is None:
                self._stream = await self._connection.stream(
                    await self._get_statement(True),
                )

        return ResultsIterator(self._parse_async_rows(self._stream))

    async def __aexit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        try:
            if self._stream is not None:
                await self._stream.close()
        finally:
            self._stream = None
            if self._connection is not None:
                if exc_type is None and self._should_commit():
                    await self._connection.commit()
                try:
                    await self._connection.__aexit__(exc_type, exc_value, traceback)
                finally:
                    self._connection = None

    def limit(self, limit: int) -> Self:
        """Return a new executor with a ``LIMIT`` clause set to `limit`."""
        return self._with_query(self._query.limit(limit))

    def offset(self, offset: int) -> Self:
        """Return a new executor with an ``OFFSET`` clause set to `offset`."""
        return self._with_query(self._query.offset(offset))

    async def first(self) -> EntityT | None:
        """Execute the query with a limit of 1 and return the first entity, or ``None``."""
        resolved = self._query._get_resolved_filter()
        if resolved.limit is None or resolved.limit > 1:
            self = self.limit(1)

        assert self._query._get_resolved_filter().limit == 1
        entities = await self.all()
        return entities[0] if entities else None

    async def all(self) -> list[EntityT]:
        """Execute the query and return all matching entities as a list.

        Use streaming when the result set may be large (above
        ``_EXECUTOR_STREAM_THRESHOLD``), falling back to eager loading for smaller sets.
        """
        resolved = self._query._get_resolved_filter()
        database = self._query._get_database()
        statement = await self._get_statement(True)

        async with await database.use() as connection:
            if resolved.limit is not None and resolved.limit <= _EXECUTOR_STREAM_THRESHOLD:
                result = await connection.execute(statement)
                entities = await self._parse_rows(result)
                if self._should_commit():
                    await connection.commit()
            else:
                stream = await connection.stream(statement)
                entities = [entity async for entity in self._parse_async_rows(stream)]
                if self._should_commit():
                    await connection.commit()

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

    def _get_parser(self) -> Callable[[Row], EntityT | None]:
        """Build a row-to-entity parser function, optionally applying a transform."""
        Entity = self._query._get_entity_class()
        transform = self._query._get_transform()

        if transform is None:

            def parse(row: Row) -> EntityT | None:
                values: Mapping[str, Any] = row._mapping  # type: ignore
                entity = create(Entity, values, True)
                return entity

        else:

            def parse(row: Row) -> EntityT | None:
                values: Mapping[str, Any] = row._mapping  # type: ignore
                entity: Any = create(Entity, values, True)
                entity = transform(entity)
                return entity

        return parse

    async def _parse_rows(self, rows: _Rows) -> list[EntityT]:
        """Parse a synchronous result set into a list of entities, yielding control periodically."""
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
                await sleep(0)
                await sleep(0)

        return entities

    async def _parse_async_rows(self, rows: _AsyncRows) -> AsyncIterator[EntityT]:
        """Async-iterate over a streaming result set, yielding parsed entities."""
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
                await sleep(0)
                await sleep(0)


class SelectExecutor[
    EntityT: BaseEntity,
    FilterT: BaseEntityFilter[Any, Any, Any],
](_BaseStatementExecutor[EntityT, FilterT, list[EntityT]]):
    """Executor that builds and runs a ``SELECT`` statement, returning entities."""

    __slots__ = ()

    @override
    async def _await(self) -> list[EntityT]:
        return await self.all()

    @override
    async def _get_statement(self, returning: bool = True) -> Select[tuple[Any]]:
        Row = self._query._get_row_class()
        database = self._query._get_database()
        statement = select(*Row.__table__.columns)
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
    """Executor that builds and runs an ``UPDATE`` statement, returning the number of affected rows.

    When consumed as a streaming async context manager, yield the updated entities via a
    ``RETURNING`` clause.
    """

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

        with wrap_database_errors():
            async with await database.use() as connection:
                result = await connection.execute(statement)
                await connection.commit()
                return result.rowcount

    @override
    async def _get_statement(self, returning: bool) -> Update | ReturningUpdate:
        Row = self._query._get_row_class()
        database = self._query._get_database()
        assign = await self._query._assign_transform(self._assign)

        statement = update(Row).values(assign)
        if returning:
            statement = statement.returning(*Row.__table__.columns)

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
    """Executor that builds and runs a ``DELETE`` statement, returning the number of affected rows.

    When consumed as a streaming async context manager, yield the deleted entities via a
    ``RETURNING`` clause.
    """

    __slots__ = ()

    @override
    async def _await(self) -> int:
        database = self._query._get_database()
        statement = await self._get_statement(False)

        with wrap_database_errors():
            async with await database.use() as connection:
                result = await connection.execute(statement)
                await connection.commit()
                return result.rowcount

    @override
    async def _get_statement(self, returning: bool) -> Delete | ReturningDelete:
        Row = self._query._get_row_class()
        database = self._query._get_database()

        statement = delete(Row)
        if returning:
            statement = statement.returning(*Row.__table__.columns)

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
    """Abstract query builder that provides ``where``, ``select``, ``update``, ``delete``, ``count``,
    and ``any`` operations for entities.

    Subclasses supply the concrete database, entity class, filter, and transform.
    """

    __slots__ = ()

    def where(
        self,
        filter: FilterT | None = None,
        **kwargs: Unpack[BaseEntityFilterArgs],
    ) -> QueryT:
        """Return a new query narrowed by `filter` and/or keyword filter arguments.

        Args:
            filter: An optional filter instance to apply.
            **kwargs: Additional filter keyword arguments merged into the query.

        Returns:
            A new ``EntityQuery`` with the combined filter criteria.
        """
        filter = self._get_resolved_filter(filter, kwargs)
        return self._get_query_class()(
            database=self._get_database(),
            entity_class=self._get_entity_class(),
            filter=filter,
            filter_defaults=self._get_filter_defaults(),
        )

    def select(self) -> SelectExecutor[EntityT, FilterT]:
        """Create a ``SelectExecutor`` for this query."""
        return SelectExecutor(query=self.where())

    def update(self, assign: UpdateT) -> UpdateExecutor[EntityT, FilterT, UpdateT]:
        """Create an ``UpdateExecutor`` that assigns the given values to matching entities."""
        return UpdateExecutor(query=self.where(), assign=assign)

    def delete(self) -> DeleteExecutor[EntityT, FilterT]:
        """Create a ``DeleteExecutor`` for this query."""
        return DeleteExecutor(query=self.where())

    async def count(self) -> int:
        """Return the number of entities matching this query's filter."""
        database = self._get_database()
        filter = self._get_resolved_filter()
        statement = select(func.count()).select_from(self._get_row_class())
        statement = filter.apply(
            statement,
            database.type,
            ignore_order=True,
            always_use_subquery=filter.limit is not None or filter.offset is not None,
        )

        async with await database.use() as connection:
            results = await connection.execute(statement)
            return results.scalar() or 0

    async def any(self) -> bool:
        """Return ``True`` if at least one entity matches this query's filter."""
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

        async with await database.use() as connection:
            results = await connection.execute(statement)
            count = results.scalar() or 0
            return count > 0

    @abstractmethod
    def _get_database(self) -> Database: ...

    @abstractmethod
    def _get_entity_class(self) -> type[EntityT]: ...

    @abstractmethod
    def _get_base_filter(self) -> FilterT: ...

    @abstractmethod
    def _get_filter_defaults(self) -> FilterT: ...

    def _get_hard_filter(self) -> FilterT | None:
        return None

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

    def _get_resolved_filter(
        self,
        filter: FilterT | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> FilterT:
        """Merge `filter`, keyword arguments, base filter, defaults, and hard filter into one.

        Args:
            filter: An optional filter instance whose set fields override the base.
            kwargs: Additional keyword arguments to construct a filter from.

        Returns:
            A fully resolved filter combining all sources.
        """
        Filter = self._get_filter_class()
        resolved = (
            Filter(**cast("Any", kwargs or {}))
            .with_defaults(filter)
            .with_defaults(self._get_base_filter())
            .with_defaults(self._get_filter_defaults())
        )

        hard = self._get_hard_filter()
        if hard is not None:
            resolved &= hard

        return resolved

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
    """Concrete, awaitable query that can be used as an async context manager for streaming.

    Awaiting the query returns a ``list`` of matching entities. Using it as an async context
    manager yields a ``ResultsIterator`` for streamed consumption.
    """

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
        if not isinstance(value, type(self)) or type(value) is not type(self):
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
    def _get_base_filter(self) -> FilterT:
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


type Filtering[FilterT] = FilterT | Callable[[], FilterT | None] | None


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
    """Database-backed manager for a specific entity type.

    Combine query building (``where``, ``select``, ``update``, ``delete``, ``count``,
    ``any``) with entity creation (``create``) and an optional hard filter that restricts
    all operations to a subset of rows.
    """

    __slots__ = ("_entity_class", "_filtering")

    @override
    def __init__(
        self,
        source: DatabaseSource,
        cls: type[EntityT],
        /,
        filtering: Filtering[FilterT] = None,
    ) -> None:
        super().__init__(source)
        self._entity_class: Final = cls
        self._filtering: Final = filtering

    @override
    def _get_database(self) -> Database:
        return self.__database__

    @override
    def _get_entity_class(self) -> type[EntityT]:
        return self._entity_class

    @override
    def _get_base_filter(self) -> FilterT:
        return self._get_filter_class()()

    @override
    def _get_filter_defaults(self) -> FilterT:
        Filter = self._get_filter_class()

        return call_partial(Filter, **self.__get_filter_defaults__())

    @override
    def _get_hard_filter(self) -> FilterT | None:
        if callable(self._filtering):
            return self._filtering()

        return self._filtering

    @override
    def _get_transform(self) -> EntityTransform[EntityT] | None:
        return None

    async def _create_transform(self, data: CreateT) -> EntityT:
        """Convert creation data into a full entity instance. Override for custom transforms."""
        if isinstance(data, self._entity_class):
            return data

        return self._entity_class(**dict(data))

    async def create(
        self,
        data: CreateT,
        *,
        upsert: bool = False,
    ) -> EntityT:
        """Transform `data` into an entity and insert it into the database.

        Args:
            data: The creation payload.
            upsert: When ``True``, perform an upsert (``ON CONFLICT DO UPDATE``) instead of
                a plain insert.

        Returns:
            The created (or upserted) entity.
        """
        result = await self._create_transform(data)
        await self._insert(result, upsert=upsert)
        return result

    async def _insert(
        self,
        data: EntityT,
        *,
        upsert: bool = False,
    ) -> RowT:
        """Insert an entity's column values into the database.

        Args:
            data: The entity to persist.
            upsert: When ``True``, use dialect-specific ``ON CONFLICT DO UPDATE`` to update
                non-primary-key columns if the row already exists.

        Returns:
            The constructed row object.
        """
        Row = self._get_row_class()
        values = data.__entity_to_column_values__()
        row = Row(**values)

        match self.__database__.type:
            case DatabaseType.SQLITE:
                from sqlalchemy.dialects.sqlite import insert
            case DatabaseType.POSTGRES:
                from sqlalchemy.dialects.postgresql import insert

        with wrap_database_errors():
            async with await self.__database__.use() as connection:
                statement = insert(Row).values(values)
                pk = Row.__table__.primary_key.columns

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

                await connection.execute(statement)
                await connection.commit()
                return row  # type: ignore


class BaseEntity(BaseEntityCreate, abstract=True, slots=True):
    """Abstract base for all entity types, associating a row class, filter, and manager."""

    Manager = BaseEntityManager
    Row = BaseEntityRow
    Create = BaseEntityCreate
    Update = BaseEntityUpdate
    Filter = BaseEntityFilter
    FilterArgs = BaseEntityFilterArgs
    Field = str
    Order = str

    @cached_class_property
    @classmethod
    @override
    def __entity_columns__(cls) -> tuple[str, ...]:
        columns = cls.Row.__table__.columns
        return tuple(field for field in cls.__data_object_fields__ if field in columns)

    def __entity_to_column_values__(self) -> dict[str, Any]:
        """Return a dict mapping column names to their values for this entity instance."""
        return {field: getattr(self, field) for field in self.__entity_columns__}

    @abstractmethod
    def __entity_to_row__(self) -> BaseEntityRow:
        return self.Row(**self.__entity_to_column_values__())


_REQUIRED_CONCRETE_CLASS_ATTRIBUTES: dict[str, tuple[type[Any], bool]] = {
    "__entity_naming__": (EntityNaming, False),
    "Manager": (BaseEntityManager, True),
    "Create": (BaseEntityCreate, True),
    "Update": (BaseEntityUpdate, True),
    "Filter": (BaseEntityFilter, True),
    "FilterArgs": (BaseEntityFilterArgs, True),
    "Field": (object, True),
    "Order": (object, True),
}


class ConcreteEntity[TRow: BaseEntityRow](BaseEntity, abstract=True, slots=True):
    """Abstract entity that auto-resolves its ``Row`` class from its generic type parameter.

    Direct subclasses are validated at class creation time to ensure all required class
    attributes (``__entity_naming__``, ``Manager``, ``Filter``, etc.) are defined.
    """

    __entity_naming__: ClassVar[EntityNaming]

    @cached_class_property
    @classmethod
    def Row(cls) -> type[TRow]:
        return get_generic_superclass_argument(cls, ConcreteEntity, 0)

    @override
    def __entity_to_row__(self) -> TRow:
        return self.Row(**self.__entity_to_column_values__())

    @classmethod
    @override
    def __data_object_init_subclass__(cls, **kwargs: Any) -> None:
        super().__data_object_init_subclass__(**kwargs)
        try:
            if not any(base is ConcreteEntity for base in cls.__bases__):
                return
        except NameError:
            return

        if cls.__data_object_generic_alias__ is not None:
            return

        for attribute, (constraint, in_dictionary) in _REQUIRED_CONCRETE_CLASS_ATTRIBUTES.items():
            if in_dictionary:
                value = cls.__dict__.get(attribute)
            else:
                value = getattr(cls, attribute, None)

            if value is None:
                raise TypeError(
                    f"Concrete entity class `{cls}` must define `{attribute}` as a class attribute."
                )
            elif constraint is not None:
                if is_typeddict(constraint):
                    continue

                if isinstance(value, type):
                    if not issubclass(value, constraint):
                        raise TypeError(
                            f"Concrete entity class `{cls}` must define `{attribute}` as a subclass of `{constraint}`."
                        )
                else:
                    if not isinstance(value, constraint):
                        raise TypeError(
                            f"Concrete entity class `{cls}` must define `{attribute}` as an instance of `{constraint}`."
                        )

        Filter = cls.__dict__["Filter"]
        try:
            Filter()
        except Exception:
            raise TypeError(f"Filter class `{Filter}` must be constructable with no arguments.")


class BaseUUIDEntityRow(BaseEntityRow):
    """Abstract row that adds a UUID primary key column (``id``)."""

    __abstract__: ClassVar[bool] = True

    id: Mapped[UUID] = mapped_column(UUIDMapper, sort_order=-3000, default_factory=uuid7)

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            PrimaryKeyConstraint("id", name=f"pk_{cls.__tablename__}"),
        )


type BaseUUIDEntityField = Literal["id"]
type BaseUUIDEntityOrder = Literal[
    "id",
    "id:asc",
    "id:desc",
]


class BaseUUIDEntityFilterArgs[
    FieldT: str,
    OrderT: str,
](BaseEntityFilterArgs[FieldT, OrderT], total=False):
    """TypedDict adding an ``id`` keyword argument for UUID-based entity filters."""

    id: MaybeSequence[UUID] | None


class BaseUUIDEntityFilter[
    EntityT: BaseUUIDEntity,
    FieldT: str,
    OrderT: str,
](BaseEntityFilter[EntityT, FieldT, OrderT]):
    """Entity filter that adds UUID ``id`` matching."""

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

        if not self._match_value(obj.id, self.id):
            return False

        return True

    @override
    def _get_where(self, dialect: DatabaseType) -> Iterable[SQLColumnExpression[bool]]:
        yield from super()._get_where(dialect)
        columns = self._get_row_cls()

        if self.id is not None:
            yield self._sql_match_value(columns.id, self.id)


class BaseUUIDEntityCreate(BaseEntityCreate, abstract=True, slots=True):
    """Creation data for UUID-keyed entities, auto-generating the ``id`` field."""

    id: UUID = Field(default_factory=uuid7)


class BaseUUIDEntityUpdate(BaseEntityUpdate, total=False):
    """Update payload for UUID-keyed entities (no additional mutable fields by default)."""

    pass


class BaseUUIDEntity(BaseEntity, BaseUUIDEntityCreate, abstract=True, slots=True):
    """Abstract entity with a UUID primary key (``id``)."""

    pass


class BaseAddressEntityRow(BaseEntityRow, kw_only=True):
    """Abstract row that adds an indexed ``address`` column."""

    __abstract__: ClassVar[bool] = True

    address: Mapped[Address] = mapped_column(AddressMapper, sort_order=-2000)

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            Index(f"ix_{cls.__tablename__}__address", cls.address),
        )


type BaseAddressEntityField = Literal["address"]
type BaseAddressEntityOrder = Literal[
    "address",
    "address:asc",
    "address:desc",
]


class BaseAddressEntityFilterArgs[
    FieldT: str,
    OrderT: str,
](BaseEntityFilterArgs[FieldT, OrderT], total=False):
    """TypedDict adding ``address`` and ``root`` keyword arguments for address-based filters."""

    root: Address | None
    address: AddressSelector | str | None


class BaseAddressEntityFilter[
    ItemT: BaseAddressEntity,
    FieldT: str,
    OrderT: str,
](BaseEntityFilter[ItemT, FieldT, OrderT]):
    """Entity filter that adds ``address`` selector matching relative to a ``root``."""

    address: AddressSelector | None = None
    """Filter by `address` matching one or more address selectors."""
    root: Address | None = None
    """The address which relative address selectors in `address` are relative to, `None` means
    all components."""

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


class BaseAddressEntityCreate(BaseEntityCreate, abstract=True, slots=True):
    """Creation data for address-keyed entities."""

    address: Address


class BaseAddressEntityUpdate(BaseEntityUpdate, total=False):
    """Update payload for address-keyed entities."""

    address: Address


class BaseAddressEntity(BaseEntity, BaseAddressEntityCreate, abstract=True, slots=True):
    """Abstract entity with an ``address`` field."""

    pass


class BaseTimestampEntityRow(BaseEntityRow):
    """Abstract row that adds an indexed ``timestamp`` column defaulting to the current UTC time."""

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


type BaseTimestampEntityField = Literal["timestamp"]
type BaseTimestampEntityOrder = Literal[
    "timestamp",
    "timestamp:asc",
    "timestamp:desc",
]


class BaseTimestampEntityFilterArgs[
    FieldT: str,
    OrderT: str,
](BaseEntityFilterArgs[FieldT, OrderT], total=False):
    """TypedDict adding timestamp, time-range, and time-of-day keyword arguments for filters."""

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
    """Entity filter with time-range, age-based, and time-of-day matching on ``timestamp``."""

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
            if obj.timestamp not in seq(self.timestamp):
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

        if self.timestamp is not None:
            yield self._sql_match_value(columns.timestamp, self.timestamp)
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
                    from sqlalchemy import cast

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
                    from sqlalchemy import cast

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
        """Compute the effective start and end times from the combined time-range filter fields.

        Args:
            now: The current time, used to resolve age-based and relative timespan bounds.

        Returns:
            A ``(start, end)`` tuple. Either value may be ``None`` if no lower or upper
            bound can be determined from the filter's fields.
        """
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


class BaseTimestampEntityCreate(BaseEntityCreate, abstract=True, slots=True):
    """Creation data for timestamp entities, defaulting ``timestamp`` to the current UTC time."""

    timestamp: DateTime = Field(default_factory=utc)


class BaseTimestampEntityUpdate(BaseEntityUpdate, total=False):
    """Update payload for timestamp entities."""

    timestamp: DateTime


class BaseTimestampEntity(BaseEntity, BaseTimestampEntityCreate, abstract=True, slots=True):
    """Abstract entity with a ``timestamp`` field."""

    pass


class EntityOutputChannel[
    EntityT: BaseEntity,
    FilterT: BaseEntityFilter[Any, Any, Any],
    FilterArgsT: BaseEntityFilterArgs[Any, Any],
](OutputChannel[EntityT], ABC):
    """Output channel that can be filtered using entity filter objects or keyword arguments."""

    __slots__ = ()

    def __init__(self, source: OutputChannel[EntityT], /) -> None:
        super().__init__(source)

    @abstractmethod
    def _get_filter_class(self) -> type[FilterT]: ...

    @override
    def where(
        self,
        filter: FilterT | Callable[[EntityT], bool] | None = None,
        /,
        **kwargs: Unpack[BaseEntityFilterArgs[Any, Any]],
    ) -> Self:
        if callable(filter):
            condition = filter
            filtering = None
        else:
            condition = None
            filtering = filter

        if kwargs:
            filtering = self._get_filter_class()(**cast("Any", kwargs)).with_defaults(filtering)

        def where(entity: EntityT) -> bool:
            if condition is not None and not condition(entity):
                return False
            if filtering is not None and not filtering.matches(entity):
                return False

            return True

        return self.__class__(super().where(where))


def get_entity_manager(source: Database | Node, entity: type[Entity]) -> BaseEntityManager:
    """Look up the entity manager for `entity` on `source` by its conventional attribute name.

    Args:
        source: A ``Database`` or ``Node`` instance that owns the manager.
        entity: The entity type whose naming provides the manager attribute name.

    Returns:
        The ``BaseEntityManager`` instance for the given entity type.

    Raises:
        ValueError: If `source` has no attribute matching the entity's manager name.
    """
    naming = entity.__entity_naming__
    manager = getattr(source, naming.manager, None)
    if manager is None:
        raise ValueError(
            f"Object `{source}` has no manager for {entity} at attribute {naming.manager!r}."
        )

    return manager
