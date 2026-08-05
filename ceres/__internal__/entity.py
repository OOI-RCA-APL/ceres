import dataclasses
from abc import ABC, abstractmethod
from collections.abc import (
    AsyncIterator,
    Awaitable,
    Callable,
    Generator,
    Mapping,
)
from datetime import datetime
from functools import cache, lru_cache
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Final,
    Literal,
    Self,
    TypedDict,
    Unpack,
    cast,
    final,
    is_typeddict,
    override,
)
from uuid import UUID

from pydantic import Field, NonNegativeInt, model_validator

from ceres.__internal__.database.errors import wrap_database_errors
from ceres.__internal__.filter import BaseFilter, BaseFilterArgs
from ceres.__internal__.manager import BaseDatabaseManager
from ceres.__internal__.utilities.case import kebabcase, snakecase
from ceres.__internal__.utilities.classes import cached_class_property
from ceres.__internal__.utilities.collections import seq
from ceres.__internal__.utilities.functions import call_partial
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
    StrEnum,
    create,
    to_json,
    uuid7,
)
from ceres.timing import utc

if TYPE_CHECKING:
    from ceres.__internal__.protocols import DatabaseSource
    from ceres.database import Database
    from ceres.entity import Entity
    from ceres.node import Node


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
    Specify ordering of results by field. Suffix a field name with ':desc' for descending order,
    or with ':asc' for ascending order, which is also the default.

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

    __table__: ClassVar[str]
    """Table this filter selects from, which is what the compiler types its columns by."""

    __nullable_filters__: ClassVar[frozenset[str]] = frozenset()
    """Fields where naming `None` filters for null rather than not filtering at all.

    Almost every field reads an absent value as "not filtered", so a `None` is dropped
    before the compiler sees it. A field listed here is one the compiler reads as asking
    whether the field was set rather than whether it is `None`, so a caller that named
    `None` meant the null and the dump has to carry it.
    """

    def _native_dump(self) -> str:
        """Serialize this filter for the native compiler, in its wire JSON form."""
        dumped = self.model_dump(mode="json", by_alias=True, exclude_none=True)
        for name in self.__nullable_filters__ & self.model_fields_set:
            dumped.setdefault(name, None)

        return to_json(dumped)

    def _native_filter(self) -> Any:
        """The native compiler's parsed form of this filter.

        The compiler is the single authority on filter semantics, so the statement a
        query runs is compiled here and in-memory matching reads rows through the same
        parsed filter. Every table the managers serve compiles, so nothing above this
        needs a second path for the ones that do not.
        """
        return _parsed_filter(self.__table__, self._native_dump())

    def matches(self, obj: EntityT) -> bool:
        """Test whether `obj` satisfies this filter, including all ``and__`` and ``or__`` subfilters.

        The native compiler is the single authority on filter semantics, so matching
        reads the entity through the same parsed filter the queries compile from.

        Args:
            obj: The entity to test against this filter.

        Returns:
            ``True`` if the entity matches.
        """
        return self._native_filter().matches(to_json(obj), utc())


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


@lru_cache(maxsize=1024)
def _parsed_filter(table: str, dump: str) -> Any:
    """Parse one filter's wire form against its table, reusing an identical parse.

    The cache is keyed on what the filter says rather than held on the filter object,
    because filters are copied constantly. `with_defaults` returns a copy carrying the
    original's private attributes, so a cache kept on the instance would follow a filter
    into a copy that no longer says the same thing, and the copy would run the original's
    statement.
    """
    from ceres.__internal__.core import NativeFilter

    return NativeFilter.from_json(table, dump)


def _native_assign(assign: Mapping[str, Any]) -> str:
    """Serialize an update's new values for the native encoder, in its wire JSON form.

    A bytes column crosses as latin-1 text, which is the convention the encoder reads back.
    JSON carries no byte string of its own, and latin-1 is the one text encoding that maps
    every byte to exactly one character, so the round trip is byte for byte.
    """
    from ceres.data import to_json

    return to_json(
        {
            key: value.decode("latin-1") if isinstance(value, bytes) else value
            for key, value in assign.items()
        }
    )


@cache
def _column_wrappers(Entity: type[BaseEntity]) -> dict[str, type[Any]]:
    """The columns whose stored value has to become a Python object, and what makes one.

    The store hands back the primitives a column holds, so a UUID arrives as a `UUID` and
    a timestamp as an aware `datetime`, but an address arrives as its text and an enum
    member as its value. Those are Python classes rather than primitives, and the entity's
    own annotation names which class each column wants, so the conversion follows the
    model rather than a list of column names kept beside it.
    """
    wrappers: dict[str, type[Any]] = {}
    for name, field in Entity.__pydantic_fields__.items():
        annotation = field.annotation
        # An optional column annotates as a union, whose one concrete member is the class
        # the value takes when it is present.
        members = [
            member
            for member in getattr(annotation, "__args__", (annotation,))
            if member is not type(None)
        ]
        if len(members) != 1:
            continue

        target = members[0]
        if not isinstance(target, type) or issubclass(target, DataObject):
            continue

        # The primitives cross as themselves, and a subclass of one is still the model's
        # own type, so only the classes a stored value is not already an instance of need
        # building.
        if issubclass(target, str | int | float | bool | bytes | datetime | UUID | dict | list):
            if issubclass(target, StrEnum) or target is not str:
                wrappers[name] = target

            continue

        wrappers[name] = target

    return wrappers


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
        "_chunks",
    )

    def __init__(
        self,
        *,
        query: EntityQuery[EntityT, FilterT, BaseEntityUpdate],
    ) -> None:
        self._query: Final = query
        self._chunks: Any | None = None

    @override
    def __eq__(self, value: object, /) -> bool:
        if type(value) is not type(self):
            return False

        return self._query == value._query

    def __await__(self) -> Generator[Any, Any, AwaitT]:
        return self._await().__await__()

    async def __aenter__(self) -> ResultsIterator[EntityT]:
        store, sql, parameters = await self._native_statement(returning=True)
        if self._chunks is None:
            with wrap_database_errors():
                self._chunks = store.stream(sql, parameters, self._native_table())

        return ResultsIterator(self._parse_chunks(self._chunks))

    async def __aexit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        # Dropping the chunks closes the channel the query writes into, which is what ends
        # a query the caller stopped reading part way through.
        self._chunks = None

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
        """Execute the query and return all matching entities as a list."""
        store, sql, parameters = await self._native_statement(returning=True)
        parse = self._get_native_parser()
        with wrap_database_errors():
            rows = await store.fetch(sql, parameters, self._native_table())

        entities: list[EntityT] = []
        for values in rows:
            entity = parse(values)
            if entity is not None:
                entities.append(entity)

        return entities

    async def mappings(self) -> list[Mapping[str, Any]]:
        """Execute the query and return raw row mappings without materializing entities.

        The wire paths serialize straight from these values, so no Python entity objects
        are built for rows that only pass through to a response body.
        """
        store, sql, parameters = await self._native_statement(returning=True)
        with wrap_database_errors():
            return await store.fetch(sql, parameters, self._native_table())

    async def compiled(self) -> tuple[str, list[Any]]:
        """Compile the query into SQL text and positionally-ordered parameters.

        This is the same statement the executor runs, compiled by the same compiler, so a
        caller handing the SQL to something else gets exactly the rows an ``await`` would
        have. The parameters come out as the primitive values the driver takes.
        """
        return await self._compile_native(returning=True)

    @abstractmethod
    def _should_commit(self) -> bool: ...

    @abstractmethod
    def _with_query(
        self,
        query: EntityQuery[EntityT, FilterT, BaseEntityUpdate],
    ) -> Self: ...

    @abstractmethod
    async def _await(self) -> AwaitT: ...

    async def _native_statement(self, *, returning: bool) -> tuple[Any, str, list[Any]]:
        """The store and the compiled statement this executor runs.

        The clock the compiler resolves age-relative conditions against is this session's,
        so a frozen or faked time stays authoritative all the way down.

        `returning` asks a write for the rows it touched, which is what a caller consuming
        one as entities rather than as a count is after. A read ignores it, already
        selecting the rows it matched.
        """
        store = await self._query._native_store()
        sql, parameters = await self._compile_native(returning=returning)
        return store, sql, parameters

    @abstractmethod
    async def _compile_native(self, *, returning: bool) -> tuple[str, list[Any]]:
        """Compile this executor's statement for the native store."""
        ...

    def _native_table(self) -> str:
        """The table the rows come from, which is what types their columns."""
        return self._query._get_entity_class().__entity_naming__.table

    async def _parse_chunks(self, chunks: Any) -> AsyncIterator[EntityT]:
        """Async-iterate a streamed result, one chunk of column mappings at a time."""
        parse = self._get_native_parser()

        count = 0
        while (rows := await chunks.next()) is not None:
            for values in rows:
                entity = parse(values)
                if entity is not None:
                    yield entity

                count += 1
                if count >= _EXECUTOR_PARSE_YIELD_CONTROL_EVERY:
                    count = 0
                    # Yield control to the event loop.
                    await sleep(0)
                    await sleep(0)

    def _get_native_parser(self) -> Callable[[dict[str, Any]], EntityT | None]:
        """Build a parser over the column mappings the native store returns."""
        Entity = self._query._get_entity_class()
        transform = self._query._get_transform()
        wrap = _column_wrappers(Entity)

        def parse(values: dict[str, Any]) -> EntityT | None:
            for name, into in wrap.items():
                held = values.get(name)
                # A column the store already hands over as its own type is left alone,
                # since building a `UUID` from a `UUID` is an error rather than a copy.
                if held is not None and not isinstance(held, into):
                    values[name] = into(held)

            entity: Any = create(Entity, values, True)
            if transform is not None:
                entity = transform(entity)

            return cast("EntityT | None", entity)

        return parse


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
    async def _compile_native(self, *, returning: bool) -> tuple[str, list[Any]]:
        # A select already names the rows it matched, so it has nothing to return on top.
        native = self._query._get_resolved_filter()._native_filter()
        return native.compiled(self._query._get_database().type.value, now=utc())

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
        store, sql, parameters = await self._native_statement(returning=False)
        with wrap_database_errors():
            return await store.execute(sql, parameters)

    @override
    async def _compile_native(self, *, returning: bool) -> tuple[str, list[Any]]:
        assign = await self._query._assign_transform(self._assign)
        native = self._query._get_resolved_filter()._native_filter()
        # The compile refuses an assignment the column cannot hold, and that refusal is the
        # caller's own to read rather than something to run past the constraint wordings a
        # driver failure is matched on, so it stays outside the error wrapper.
        return native.update_compiled(
            self._query._get_database().type.value,
            _native_assign(assign),
            returning,
            utc(),
        )

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
        store, sql, parameters = await self._native_statement(returning=False)
        with wrap_database_errors():
            return await store.execute(sql, parameters)

    @override
    async def _compile_native(self, *, returning: bool) -> tuple[str, list[Any]]:
        native = self._query._get_resolved_filter()._native_filter()
        return native.delete_compiled(
            self._query._get_database().type.value,
            returning,
            utc(),
        )

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

    async def _native_store(self) -> Any:
        """The store this query's statements run on.

        Bootstrapping happens here, because the store reads the database directly rather
        than through a connection something else opened, and a database nobody has
        bootstrapped has no tables and, for a temporary one, no file either.
        """
        database = self._get_database()
        await database.ready()
        return database._store()

    async def count(self) -> int:
        """Return the number of entities matching this query's filter."""
        database = self._get_database()
        filter = self._get_resolved_filter()
        store = await self._native_store()

        sql, parameters = filter._native_filter().compiled(
            database.type.value,
            count=True,
            now=utc(),
        )
        with wrap_database_errors():
            rows = await store.fetch(sql, parameters)

        # The count is the statement's only column, and its name is whatever the backend
        # calls a `COUNT(*)` expression, so the row is read by position.
        return next(iter(rows[0].values())) if rows else 0

    async def any(self) -> bool:
        """Return ``True`` if at least one entity matches this query's filter."""
        database = self._get_database()
        filter = self._get_resolved_filter()
        store = await self._native_store()

        sql, parameters = filter._native_filter().exists_compiled(database.type.value, utc())
        with wrap_database_errors():
            rows = await store.fetch(sql, parameters)

        return bool(next(iter(rows[0].values()))) if rows else False

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

    async def mappings(self) -> list[Mapping[str, Any]]:
        """Execute the query and return raw row mappings without materializing entities."""
        return await self.select().mappings()

    async def compiled(self) -> tuple[str, list[Any]]:
        """Compile the query into SQL text and positionally-ordered parameters."""
        return await self.select().compiled()

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
    ) -> None:
        """Insert an entity's column values into the database.

        Args:
            data: The entity to persist.
            upsert: When ``True``, use dialect-specific ``ON CONFLICT DO UPDATE`` to update
                non-primary-key columns if the row already exists.
        """
        from ceres.__internal__.core import insert_compiled

        values = data.__entity_to_column_values__()
        database = self.__database__
        await database.ready()

        # The compile stays outside the wrapper, a column the row cannot hold is the
        # caller's own error rather than a driver failure to translate.
        sql, parameters = insert_compiled(
            self._get_entity_class().__entity_naming__.table,
            database.type.value,
            _native_assign(values),
            upsert,
        )
        with wrap_database_errors():
            await database._store().execute(sql, parameters)


@cache
def _stored_columns(table: str) -> frozenset[str]:
    """The columns the native layer reads and writes for `table`."""
    from ceres.__internal__.core import stored_columns

    for name, columns in stored_columns():
        if name == table:
            return frozenset(column for column, _ in columns)

    raise KeyError(f"No table named `{table}` is stored.")


class BaseEntity(BaseEntityCreate, abstract=True, slots=True):
    """Abstract base for all entity types, associating a filter and a manager with a table."""

    Manager = BaseEntityManager
    Create = BaseEntityCreate
    Update = BaseEntityUpdate
    Filter = BaseEntityFilter
    FilterArgs = BaseEntityFilterArgs
    Field = str
    Order = str

    __entity_naming__: ClassVar[EntityNaming]

    @cached_class_property
    @classmethod
    @override
    def __entity_columns__(cls) -> tuple[str, ...]:
        # Taken from the native layer, so an entity field and the column it persists to are
        # the same name in one place rather than two that can drift apart.
        columns = _stored_columns(cls.__entity_naming__.table)
        return tuple(field for field in cls.__data_object_fields__ if field in columns)

    def __entity_to_column_values__(self) -> dict[str, Any]:
        """Return a dict mapping column names to their values for this entity instance."""
        return {field: getattr(self, field) for field in self.__entity_columns__}


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


class ConcreteEntity(BaseEntity, abstract=True, slots=True):
    """Abstract entity for a table of its own, validated at class creation time.

    Direct subclasses must define all the required class attributes
    (``__entity_naming__``, ``Manager``, ``Filter``, and the rest).
    """

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


class BaseUUIDEntityCreate(BaseEntityCreate, abstract=True, slots=True):
    """Creation data for UUID-keyed entities, auto-generating the ``id`` field."""

    id: UUID = Field(default_factory=uuid7)


class BaseUUIDEntityUpdate(BaseEntityUpdate, total=False):
    """Update payload for UUID-keyed entities (no additional mutable fields by default)."""

    pass


class BaseUUIDEntity(BaseEntity, BaseUUIDEntityCreate, abstract=True, slots=True):
    """Abstract entity with a UUID primary key (``id``)."""

    pass


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


class BaseAddressEntityCreate(BaseEntityCreate, abstract=True, slots=True):
    """Creation data for address-keyed entities."""

    address: Address


class BaseAddressEntityUpdate(BaseEntityUpdate, total=False):
    """Update payload for address-keyed entities."""

    address: Address


class BaseAddressEntity(BaseEntity, BaseAddressEntityCreate, abstract=True, slots=True):
    """Abstract entity with an ``address`` field."""

    pass


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
