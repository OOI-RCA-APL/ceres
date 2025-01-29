from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterable,
    ClassVar,
    Iterable,
    Literal,
    TypeAlias,
    TypedDict,
    Unpack,
    overload,
    override,
)

from pydantic import ValidationError
from sqlalchemy import JSON, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import Index, PrimaryKeyConstraint, SchemaItem
from sqlalchemy.sql import SQLColumnExpression

from ceres._internal import util
from ceres._internal.entity import BaseEntityManager
from ceres._internal.item import (
    BaseItem,
    BaseItemCreate,
    BaseItemField,
    BaseItemFilter,
    BaseItemFilterArgs,
    BaseItemOrder,
    BaseItemRow,
)
from ceres._internal.lazy import lazy_imports
from ceres._internal.manager import BaseBoundManager
from ceres._internal.util import get_type_adapter
from ceres.address import Address
from ceres.data import FromYaml, JSONSerializable, MaybeSequence
from ceres.database import DatabaseType
from ceres.stream import Stream


class VariableRow(BaseItemRow, kw_only=True):
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


VariableField: TypeAlias = (
    BaseItemField
    | Literal[
        "name",
        "value",
    ]
)
VariableOrder: TypeAlias = (
    BaseItemOrder
    | Literal[
        "name",
        "-name",
        "value",
        "-value",
    ]
)


class VariableFilterArgs(BaseItemFilterArgs[VariableField, VariableOrder], total=False):
    name: MaybeSequence[str] | None


class VariableFilter(BaseItemFilter["Variable", VariableField, VariableOrder]):
    name: MaybeSequence[str] | None = None
    """Filter by `name` being equal to one or more given names."""
    internal: bool | None = None
    """
    Filter variables based on whether they are internal or not. Internal variables are those that
    start with an end with two underscores. For example: `__enabled__`. If `None`, both internal and
    non-internal variables will be matched.
    """

    @override
    def matches(self, obj: Variable) -> bool:
        if not super().matches(obj):
            return False

        if self.name is not None:
            if obj.name not in util.as_sequence(self.name):
                return False
        if self.internal is not None:
            internal = obj.name.startswith("__") and obj.name.endswith("__")
            if internal != self.internal:
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
            yield columns.name.in_(util.as_sequence(self.name))
        if self.internal is not None:
            internal = columns.name.startswith("__") & columns.name.endswith("__")
            if not self.internal:
                internal = ~internal

            yield internal

    @override
    def _get_default_order(self) -> VariableOrder:
        return "name"


class VariableCreate(BaseItemCreate):
    name: str
    value: FromYaml[JSONSerializable]


class VariableUpdate(TypedDict, total=False):
    name: str
    value: FromYaml[JSONSerializable]


class Variable(BaseItem, VariableCreate):
    Row: ClassVar[type[VariableRow]] = VariableRow
    Create: ClassVar[type[VariableCreate]] = VariableCreate
    Update: ClassVar[type[VariableUpdate]] = VariableUpdate
    Filter: ClassVar[type[VariableFilter]] = VariableFilter
    FilterArgs: ClassVar[type[VariableFilterArgs]] = VariableFilterArgs
    Field = VariableField
    Order = VariableOrder


with lazy_imports(__name__):
    from ceres.database import Database
    from ceres.node import Node


class VariableManager(
    BaseEntityManager[
        Variable,
        Variable.Row,
        Variable.Create,
        Variable.Update,
        Variable.Filter,
        Variable.FilterArgs,
    ]
):
    def __init__(self, source: Database | Node, /) -> None:
        super().__init__(source, Variable)

    if TYPE_CHECKING:
        # See: https://github.com/python/typing/issues/1399
        _E = Variable
        _F = Variable.Filter
        _FA = Variable.FilterArgs

        @override
        async def get_all(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _F | None = None, /, **kwargs: Unpack[_FA]
        ) -> list[_E]: ...

        @override
        async def get(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _F | None = None, /, **kwargs: Unpack[_FA]
        ) -> _E | None: ...

        @override
        def select(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _F | None = None, **kwargs: Unpack[_FA]
        ) -> AsyncIterable[_E]: ...

        @override
        async def delete_all(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _F | None = None, **kwargs: Unpack[_FA]
        ) -> int: ...

        @override
        async def delete(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _F | None = None, /, **kwargs: Unpack[_FA]
        ) -> _E | None: ...

        @override
        async def count(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _F | None = None, /, **kwargs: Unpack[_FA]
        ) -> int: ...


class BoundVariableManager(VariableManager, BaseBoundManager[Variable]):
    def __init__(self, source: Node, /) -> None:
        super().__init__(source)

    def store(self, variable: Variable, /) -> None:
        return self._node.store(variable)

    def assign(self, name: str, value: Any) -> Variable:
        from ceres.event import VariableAssignedEvent

        variable = Variable(
            address=self._node.address,
            name=name,
            value=value,
        )

        self.store(variable)
        self._node.events.emit(VariableAssignedEvent, variable=variable)
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
        variable = await self.get(address=address or self._node.address, name=name)
        if variable is None:
            return default

        if parse is not None:
            try:
                return get_type_adapter(parse).validate_python(variable.value)
            except ValidationError:
                return default

        return variable.value

    def follow(
        self,
        filter: VariableFilter | None = None,
        **kwargs: Unpack[VariableFilterArgs],
    ) -> Stream[Variable]:
        from ceres.event import VariableAssignedEvent

        filter = self._apply_default_filter(filter, kwargs)
        return (
            self._node.events.follow()
            .every(VariableAssignedEvent)
            .map(lambda event: event.variable)
            .filter(filter.matches)
        )
