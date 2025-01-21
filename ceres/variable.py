from __future__ import annotations

from typing import (
    Any,
    ClassVar,
    Iterable,
    Literal,
    TypeAlias,
    TypedDict,
    override,
)

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import JSON, Text

from ceres._internal.entity import (
    BaseItem,
    BaseItemCreate,
    BaseItemField,
    BaseItemFilter,
    BaseItemFilterArgs,
    BaseItemOrder,
    BaseItemRow,
)
from ceres._internal.lazy import lazy_imports
from ceres._internal.types import MaybeSequence
from ceres.data import FromYaml, Jsonable, JsonValue
from ceres.database.enums import DatabaseType

with lazy_imports(__name__):
    from sqlalchemy.schema import Index, PrimaryKeyConstraint, SchemaItem
    from sqlalchemy.sql import SQLColumnExpression

    from ceres._internal import util


class VariableRow(BaseItemRow, kw_only=True):
    __tablename__: ClassVar[str] = "variables"

    name: Mapped[str] = mapped_column(Text)
    value: Mapped[JsonValue] = mapped_column(JSON)

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
    value: FromYaml[Jsonable[Any]]


class VariableUpdate(TypedDict, total=False):
    name: str
    value: FromYaml[Jsonable[Any]]


class Variable(BaseItem, VariableCreate):
    Row: ClassVar[type[VariableRow]] = VariableRow
    Create: ClassVar[type[VariableCreate]] = VariableCreate
    Update: ClassVar[type[VariableUpdate]] = VariableUpdate
    Filter: ClassVar[type[VariableFilter]] = VariableFilter
    FilterArgs: ClassVar[type[VariableFilterArgs]] = VariableFilterArgs
    Field = VariableField
    Order = VariableOrder
