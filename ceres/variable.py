from __future__ import annotations

from typing import (
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

from pydantic import Field

from ceres._internal.cli.plumbing import CLIOption
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
from ceres.data import FromYAML, JSONValue, jsonify
from ceres.database.enums import DatabaseType

with lazy_imports(__name__):
    from sqlalchemy import Index, PrimaryKeyConstraint
    from sqlalchemy.orm import Mapped, mapped_column
    from sqlalchemy.schema import SchemaItem
    from sqlalchemy.sql import SQLColumnExpression, cast
    from sqlalchemy.sql.sqltypes import JSON, Text

    from ceres._internal import util


class VariableRow(BaseItemRow, kw_only=True):
    __tablename__: ClassVar[str] = "variables"

    name: Mapped[str] = mapped_column(Text)
    value: Mapped[JSONValue] = mapped_column(JSON)

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


VariableField = (
    BaseItemField
    | Literal[
        "name",
        "value",
    ]
)
VariableOrder = (
    BaseItemOrder
    | Literal[
        "name",
        "-name",
        "value",
        "-value",
    ]
)


class VariableFilterArgs(BaseItemFilterArgs[VariableField, VariableOrder], total=False):
    name: str | Sequence[str] | None


class VariableFilter(BaseItemFilter["Variable", VariableField, VariableOrder]):
    name: Annotated[str | Sequence[str] | None, CLIOption(list[str] | None)] = Field(
        default=None,
        description="Filter by name(s).",
    )
    internal: Annotated[bool | None, CLIOption(bool | None)] = Field(
        default=None,
        description=(
            "Include or exclude internal variables from results. Internal variables both start "
            "with an end with two underscores. For example: `__enabled__`."
        ),
    )

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
    def _get_search_content(self, obj: Variable) -> Mapping[str, str]:
        return {
            **super()._get_search_content(obj),
            "name": obj.name,
            "value": jsonify(obj.value),
        }

    @override
    def _get_database_search_content(
        self,
        dialect: DatabaseType,
    ) -> Mapping[str, SQLColumnExpression[Any]]:
        columns = self._get_row_cls()

        match dialect:
            case DatabaseType.POSTGRES:
                value = cast(columns.value, Text)
            case DatabaseType.SQLITE:
                value = columns.value

        return {
            **super()._get_database_search_content(dialect),
            "name": columns.name,
            "value": value,
        }

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
    name: Annotated[str, CLIOption(str)]
    value: Annotated[FromYAML[JSONValue], CLIOption(str)]


class VariableUpdate(TypedDict, total=False):
    name: str
    value: FromYAML[JSONValue]


class Variable(BaseItem, VariableCreate):
    Row: ClassVar[type[VariableRow]] = VariableRow
    Create: ClassVar[type[VariableCreate]] = VariableCreate
    Update: ClassVar[type[VariableUpdate]] = VariableUpdate
    Filter: ClassVar[type[VariableFilter]] = VariableFilter
    FilterArgs: ClassVar[type[VariableFilterArgs]] = VariableFilterArgs
    Field = VariableField
    Order = VariableOrder
