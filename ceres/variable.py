from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any, ClassVar, Literal, TypedDict, Unpack, overload, override

from pydantic import ValidationError
from sqlalchemy import JSON, Index, PrimaryKeyConstraint, Text, cast
from sqlalchemy.orm import Mapped, mapped_column

from ceres.__internal__.entity import (
    BaseAddressEntity,
    BaseAddressEntityCreate,
    BaseAddressEntityField,
    BaseAddressEntityFilter,
    BaseAddressEntityFilterArgs,
    BaseAddressEntityOrder,
    BaseAddressEntityRow,
    BaseEntityManager,
    BaseEntityQuery,
    ConcreteEntity,
    EntityNaming,
    EntityOutputChannel,
    EntityQuery,
)
from ceres.__internal__.manager import BaseNodeManager
from ceres.data import FromYAML, JSONSerializable, MaybeSequence, StrEnum, to_json, validate

if TYPE_CHECKING:
    from sqlalchemy import SQLColumnExpression
    from sqlalchemy.schema import SchemaItem

    from ceres.__internal__.protocols import DatabaseSource, NodeSource
    from ceres.address import Address
    from ceres.database import DatabaseType

__all__ = [
    "Variable",
]


class VariableRow(BaseAddressEntityRow, kw_only=True):
    """SQLAlchemy row type backing the `Variable` entity."""

    __tablename__: ClassVar[str] = "variables"

    name: Mapped[str] = mapped_column(Text)
    value: Mapped[JSONSerializable] = mapped_column(JSON)

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *(
                current
                for current in super().__get_table_args__()
                if not isinstance(current, Index) or "address" not in (current.name or "")
            ),
            PrimaryKeyConstraint("address", "name", name=f"pk_{cls.__tablename__}"),
        )


type VariableField = (
    BaseAddressEntityField
    | Literal[
        "name",
        "value",
    ]
)
"""Field names selectable in `Variable` queries."""

type VariableOrder = (
    BaseAddressEntityOrder
    | Literal[
        "name",
        "name:asc",
        "name:desc",
        "value",
        "value:asc",
        "value:desc",
    ]
)
"""Ordering keys accepted by `Variable` queries."""


class VariableFilterArgs(BaseAddressEntityFilterArgs[VariableField, VariableOrder], total=False):
    """Keyword-argument form of `VariableFilter` for ergonomic call sites."""

    name: MaybeSequence[str] | None
    name_contains: MaybeSequence[str] | None
    name_prefix: MaybeSequence[str] | None
    name_suffix: MaybeSequence[str] | None
    internal: bool | None
    value: JSONSerializable | None


class VariableFilter(BaseAddressEntityFilter["Variable", VariableField, VariableOrder]):
    """Filter for selecting `Variable` records by name, internal status, or value."""

    name: MaybeSequence[str] | None = None
    """Filter by `name` being equal to one or more given names."""
    name_contains: MaybeSequence[str] | None = None
    """Filter by `name` containing one or more given substrings."""
    name_prefix: MaybeSequence[str] | None = None
    """Filter by `name` starting with one or more given prefixes."""
    name_suffix: MaybeSequence[str] | None = None
    """Filter by `name` ending with one or more given suffixes."""
    internal: bool | None = None
    """
    Filter variables based on whether they are internal or not. Internal variables are those that
    start with an end with two underscores. For example, `__enabled__`. If `None`, both internal and
    non-internal variables will be matched.
    """
    value: JSONSerializable | None = None
    """Filter by `value` being exactly equal to the given JSON-serializable value."""

    @override
    def _matches(self, obj: Variable) -> bool:
        if not super()._matches(obj):
            return False

        if not self._match_value(obj.name, self.name):
            return False
        if not self._match_string_contains(obj.name, self.name_contains):
            return False
        if not self._match_string_prefix(obj.name, self.name_prefix):
            return False
        if not self._match_string_suffix(obj.name, self.name_suffix):
            return False

        if self.internal is not None:
            internal = obj.name.startswith("__") and obj.name.endswith("__")
            if internal != self.internal:
                return False

        if "value" in self.model_fields_set:
            if to_json(obj.value) != to_json(self.value):
                return False

        return True

    @classmethod
    @override
    def _get_row_cls(cls) -> type[VariableRow]:
        return VariableRow

    @override
    def _get_where(self, dialect: DatabaseType) -> Iterable[SQLColumnExpression[bool]]:
        yield from super()._get_where(dialect)
        columns = self._get_row_cls()

        if self.name is not None:
            yield self._sql_match_value(columns.name, self.name)
        if self.name_contains is not None:
            yield self._sql_match_string_contains(columns.name, self.name_contains)
        if self.name_prefix is not None:
            yield self._sql_match_string_prefix(columns.name, self.name_prefix)
        if self.name_suffix is not None:
            yield self._sql_match_string_suffix(columns.name, self.name_suffix)

        if self.internal is not None:
            internal = self._sql_match_string_prefix(columns.name, "__")
            internal &= self._sql_match_string_suffix(columns.name, "__")
            yield internal if self.internal else ~internal

        if "value" in self.model_fields_set:
            yield self._sql_match_value(cast(columns.value, Text), to_json(self.value))

    @override
    def _get_default_order(self) -> MaybeSequence[VariableOrder]:
        return ("address", "name")


class VariableCreate(BaseAddressEntityCreate, slots=True):
    """Payload for creating a new `Variable` record."""

    name: str
    """Name of the variable, unique per owning address."""
    value: FromYAML[JSONSerializable]
    """Arbitrary JSON-serializable value stored for this variable."""


class VariableUpdate(TypedDict, total=False):
    """Partial update for an existing `Variable` record."""

    name: str
    value: FromYAML[JSONSerializable]


class _BaseVariableQuery(
    BaseEntityQuery[
        "Variable",
        VariableFilter,
        VariableUpdate,
        "VariableQuery",
    ]
):
    __slots__ = ()

    @override
    def _get_query_class(self) -> type[VariableQuery]:
        return VariableQuery

    @override
    def where(  # type: ignore
        self,
        filter: VariableFilter | None = None,
        **kwargs: Unpack[VariableFilterArgs],
    ) -> VariableQuery:
        return super().where(filter, **kwargs)


class VariableQuery(
    EntityQuery[
        "Variable",
        VariableFilter,
        VariableUpdate,
    ],
    _BaseVariableQuery,
):
    """Query builder for `Variable` records."""

    __slots__ = ()


class VariableManager(
    BaseEntityManager[
        "Variable",
        VariableRow,
        VariableCreate,
        VariableUpdate,
        VariableFilter,
        VariableFilterArgs,
    ],
    _BaseVariableQuery,
):
    """Database-bound manager for `Variable` records."""

    __slots__ = ()

    def __init__(self, source: DatabaseSource, /) -> None:
        super().__init__(source, Variable)

    async def get(self, address: Address, name: str, /) -> Variable | None:
        """Fetch a single variable by its composite key.

        Args:
            address: Address of the owning node.
            name: Name of the variable.

        Returns:
            The matching variable, or `None` if no variable with that key exists.
        """
        return await self.where(address=address, name=name).first()


class BoundVariableManager(VariableManager, BaseNodeManager):
    """Component-bound variable manager that exposes the live assignment stream and helpers.

    Use `assign()` to set a variable and emit a `VariableAssignedEvent`, and `read()` to fetch
    the current value with optional type validation.
    """

    __slots__ = ()

    def __init__(self, source: NodeSource, /) -> None:
        super().__init__(source)

    @property
    def stream(self) -> VariableOutputChannel:
        """Return an output channel that yields variables from `VariableAssignedEvent` events."""
        from ceres.event import VariableAssignedEvent

        return VariableOutputChannel(
            self.__node__.events.stream.every(VariableAssignedEvent)
            .map(lambda event: event.variable)
            .where(lambda variable: self._get_resolved_filter().matches(variable))
        )

    def assign(self, name: str, value: Any) -> Variable:
        """Assign a variable on the bound node and broadcast a `VariableAssignedEvent`.

        The variable is stored in the database and emitted so listeners receive the update
        immediately.

        Args:
            name: Name of the variable to assign.
            value: Value to store, must be JSON-serializable.

        Returns:
            The newly created or updated `Variable` instance.
        """
        from ceres.event import VariableAssignedEvent

        variable = Variable(
            address=self.__node__.address,
            name=name,
            value=value,
        )

        self.__node__.store(variable)
        self.__node__.events.emit(VariableAssignedEvent, variable=variable)
        return variable

    @overload
    async def read(
        self,
        name: str,
        parse: None = None,
        default: None = None,
        *,
        address: Address | None = None,
    ) -> Any | None: ...

    @overload
    async def read(
        self,
        name: str,
        parse: None,
        default: Any,
        *,
        address: Address | None = None,
    ) -> Any: ...

    @overload
    async def read[T, D](
        self,
        name: str,
        parse: type[T],
        default: D,
        *,
        address: Address | None = None,
    ) -> T | D: ...

    async def read(
        self,
        name: str,
        parse: type | None = None,
        default: Any = None,
        *,
        address: Address | None = None,
    ) -> Any | None:
        """Read a variable's value, optionally parsing it against a target type.

        Args:
            name: Name of the variable to read.
            parse: Optional target type, the stored value is validated against this type and
                `default` is returned if validation fails.
            default: Value to return when the variable is missing or fails `parse` validation.
            address: Address to read from, defaults to the bound node's address.

        Returns:
            The parsed value, the raw stored value when `parse` is `None`, or `default` when
            the variable is missing or cannot be parsed.
        """
        address = address or self.__node__.address
        variable = await self.where(address=address, name=name, limit=1).first()
        if variable is None:
            return default

        if parse is not None:
            try:
                return validate(parse, variable.value)
            except ValidationError:
                return default

        return variable.value


class VariableOutputChannel(
    EntityOutputChannel[
        "Variable",
        VariableFilter,
        VariableFilterArgs,
    ]
):
    """Output channel for streaming `Variable` instances with filtering helpers."""

    __slots__ = ()

    @override
    def _get_filter_class(self) -> type[VariableFilter]:
        return VariableFilter

    @override
    def where(  # type: ignore
        self,
        filter: VariableFilter | Callable[[Variable], bool] | None = None,
        /,
        **kwargs: Unpack[VariableFilterArgs],
    ) -> VariableOutputChannel:
        """Return a new channel that only yields variables matching the given filter.

        Args:
            filter: A `VariableFilter`, a callable predicate, or `None` to filter by keyword
                arguments only.
            **kwargs: Additional filter fields forwarded to `VariableFilter`.

        Returns:
            A filtered `VariableOutputChannel`.
        """
        return super().where(filter, **kwargs)


class Variable(
    BaseAddressEntity,
    VariableCreate,
    ConcreteEntity[VariableRow],
    slots=True,
):
    """Named JSON-serializable value owned by an addressed node.

    Variables store configuration and state keyed by `(address, name)`. Internal variables use the
    `__name__` convention and are treated specially by some components. Assignments are broadcast
    as `VariableAssignedEvent` so listeners see updates in real time.
    """

    Manager = VariableManager
    BoundManager = BoundVariableManager
    Create = VariableCreate
    Update = VariableUpdate
    Filter = VariableFilter
    FilterArgs = VariableFilterArgs
    Field = VariableField
    Order = VariableOrder

    __entity_naming__: ClassVar[EntityNaming] = EntityNaming("user")


class InternalVariableName(StrEnum):
    """Well-known internal variable names recognized by built-in components."""

    ENABLED = "__enabled__"
