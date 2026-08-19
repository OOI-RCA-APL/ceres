from collections.abc import Callable
from typing import TYPE_CHECKING, Any, ClassVar, Unpack, overload, override

from pydantic import ValidationError

from ceres.__internal__.entity import (
    BaseAddressEntity,
    BaseEntityManager,
    BaseEntityQuery,
    ConcreteEntity,
    EntityNaming,
    EntityOutputChannel,
    EntityQuery,
)
from ceres.__internal__.manager import BaseNodeManager
from ceres.__internal__.models.variables import (
    VariableCreate,
    VariableField,
    VariableFilter,
    VariableFilterArgs,
    VariableOrder,
    VariableUpdate,
)
from ceres.data import StrEnum, validate

if TYPE_CHECKING:
    from ceres.__internal__.protocols import DatabaseSource, NodeSource
    from ceres.address import Address

__all__ = [
    "Variable",
]


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
    ConcreteEntity,
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

    __entity_naming__: ClassVar[EntityNaming] = EntityNaming("variable")


class InternalVariableName(StrEnum):
    """Well-known internal variable names recognized by built-in components."""

    ENABLED = "__enabled__"
