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
from uuid import UUID

from pydantic import Field
from sqlalchemy import Uuid

from ceres._internal.cli.plumbing import CLIOption
from ceres._internal.entity import (
    BaseEntity,
    BaseEntityCreate,
    BaseEntityFilter,
    BaseEntityRow,
    BaseItemField,
    BaseItemFilterArgs,
    BaseItemOrder,
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


class SettingRow(BaseEntityRow, kw_only=True):
    __tablename__: ClassVar[str] = "settings"

    user_id: Mapped[UUID] = mapped_column(Uuid)
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
            PrimaryKeyConstraint("user_id", "name", name=f"pk_{cls.__tablename__}"),
        )


SettingField = (
    BaseItemField
    | Literal[
        "user_id",
        "name",
        "value",
    ]
)
SettingOrder = (
    BaseItemOrder
    | Literal[
        "name",
        "-name",
        "value",
        "-value",
    ]
)


class SettingFilterArgs(BaseItemFilterArgs[SettingField, SettingOrder], total=False):
    user_id: UUID | Sequence[UUID] | None
    name: str | Sequence[str] | None


class SettingFilter(BaseEntityFilter["Setting", SettingField, SettingOrder]):
    user_id: Annotated[UUID | Sequence[UUID] | None, CLIOption(list[UUID] | None)] = Field(
        default=None,
        description="Filter by user ID(s).",
    )
    name: Annotated[str | Sequence[str] | None, CLIOption(list[str] | None)] = Field(
        default=None,
        description="Filter by name(s).",
    )

    @override
    def matches(self, obj: Setting) -> bool:
        if not super().matches(obj):
            return False

        if self.user_id is not None:
            if obj.user_id not in util.as_sequence(self.user_id):
                return False
        if self.name is not None:
            if obj.name not in util.as_sequence(self.name):
                return False

        return True

    @classmethod
    @override
    def _get_row_cls(cls) -> type[SettingRow]:
        return SettingRow

    @override
    def _get_search_content(self, obj: Setting) -> Mapping[str, str]:
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

        if self.user_id is not None:
            yield columns.user_id.in_(util.as_sequence(self.user_id))
        if self.name is not None:
            yield columns.name.in_(util.as_sequence(self.name))

    @override
    def _get_default_order(self) -> SettingOrder:
        return "name"


class SettingCreate(BaseEntityCreate):
    user_id: UUID
    name: Annotated[str, CLIOption(str)]
    value: Annotated[FromYAML[JSONValue], CLIOption(str)]


class SettingUpdate(TypedDict, total=False):
    name: str
    value: FromYAML[JSONValue]


class Setting(BaseEntity, SettingCreate):
    Row: ClassVar[type[SettingRow]] = SettingRow
    Create: ClassVar[type[SettingCreate]] = SettingCreate
    Update: ClassVar[type[SettingUpdate]] = SettingUpdate
    Filter: ClassVar[type[SettingFilter]] = SettingFilter
    FilterArgs: ClassVar[type[SettingFilterArgs]] = SettingFilterArgs
    Field = SettingField
    Order = SettingOrder
