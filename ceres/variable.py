from __future__ import annotations

from typing import (
    Any,
    ClassVar,
    Iterable,
    Literal,
    Sequence,
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
from ceres._internal.entity import BaseEntityManager, BaseEntityQuery, EntityQuery
from ceres._internal.item import (
    BaseItem,
    BaseItemCreate,
    BaseItemField,
    BaseItemFilter,
    BaseItemFilterArgs,
    BaseItemOrder,
    BaseItemRow,
)
from ceres._internal.manager import BaseNodeManager
from ceres._internal.protocols import DatabaseSource, NodeSource
from ceres._internal.util import MatchMode, get_type_adapter
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
        "name:asc",
        "name:desc",
        "value",
        "value:asc",
        "value:desc",
    ]
)


class VariableFilterArgs(BaseItemFilterArgs[VariableField, VariableOrder], total=False):
    name: MaybeSequence[str] | None
    name_contains: MaybeSequence[str] | None
    name_prefix: MaybeSequence[str] | None
    name_suffix: MaybeSequence[str] | None


class VariableFilter(BaseItemFilter["Variable", VariableField, VariableOrder]):
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
    start with an end with two underscores. For example: `__enabled__`. If `None`, both internal and
    non-internal variables will be matched.
    """

    @override
    def matches(self, obj: Variable) -> bool:
        if not super().matches(obj):
            return False

        if not util.match_value(obj.name, self.name):
            return False
        if not util.match_string(obj.name, self.name_contains, MatchMode.CONTAINS):
            return False
        if not util.match_string(obj.name, self.name_prefix, MatchMode.PREFIX):
            return False
        if not util.match_string(obj.name, self.name_suffix, MatchMode.SUFFIX):
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
            yield util.sql_match_value(columns.name, self.name)
        if self.name_contains is not None:
            yield util.sql_match_string(columns.name, self.name_contains, MatchMode.CONTAINS)
        if self.name_prefix is not None:
            yield util.sql_match_string(columns.name, self.name_prefix, MatchMode.PREFIX)
        if self.name_suffix is not None:
            yield util.sql_match_string(columns.name, self.name_suffix, MatchMode.SUFFIX)

        if self.internal is not None:
            internal = util.sql_match_string(columns.name, "__", MatchMode.PREFIX)
            internal &= util.sql_match_string(columns.name, "__", MatchMode.SUFFIX)
            yield internal if self.internal else ~internal

    @override
    def _get_default_order(self) -> Sequence[VariableOrder]:
        return ("address", "name")


class VariableCreate(BaseItemCreate):
    name: str
    value: FromYaml[JSONSerializable]


class VariableUpdate(TypedDict, total=False):
    name: str
    value: FromYaml[JSONSerializable]


class _BaseVariableQuery(
    BaseEntityQuery[
        "Variable",
        VariableFilter,
        VariableUpdate,
        "VariableQuery",
    ]
):
    @override
    def _get_query_class(self) -> type[VariableQuery]:
        return VariableQuery

    @override
    def where(
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
    pass


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
    def __init__(self, source: DatabaseSource, /) -> None:
        super().__init__(source, Variable)

    async def get(self, address: Address, name: str, /) -> Variable | None:
        return await self.where(address=address, name=name).first()


class BoundVariableManager(VariableManager, BaseNodeManager):
    def __init__(self, source: NodeSource, /) -> None:
        super().__init__(source)

    def assign(self, name: str, value: Any) -> Variable:
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
        address = address or self.__node__.address
        variable = await self.where(address=address, name=name, limit=1).first()
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

        filter = self._get_resolved_filter_args(filter, kwargs)
        return (
            self.__node__.events.follow()
            .every(VariableAssignedEvent)
            .map(lambda event: event.variable)
            .filter(filter.matches)
        )


class Variable(BaseItem, VariableCreate):
    Manager: ClassVar[type[VariableManager]] = VariableManager
    BoundManager: ClassVar[type[BoundVariableManager]] = BoundVariableManager
    Row: ClassVar[type[VariableRow]] = VariableRow
    Create: ClassVar[type[VariableCreate]] = VariableCreate
    Update: ClassVar[type[VariableUpdate]] = VariableUpdate
    Filter: ClassVar[type[VariableFilter]] = VariableFilter
    FilterArgs: ClassVar[type[VariableFilterArgs]] = VariableFilterArgs
    Field = VariableField
    Order = VariableOrder
