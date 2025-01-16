from __future__ import annotations

from typing import (
    ClassVar,
    Iterable,
    Literal,
    Sequence,
    TypeAlias,
    TypedDict,
    override,
)
from uuid import UUID

from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import JSON, Text

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
from ceres.data import FromYAML, JSONValue
from ceres.database.enums import DatabaseType

with lazy_imports(__name__):
    from sqlalchemy import PrimaryKeyConstraint
    from sqlalchemy.schema import SchemaItem
    from sqlalchemy.sql import SQLColumnExpression

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
            *super().__get_table_args__(),
            PrimaryKeyConstraint("user_id", "name", name=f"pk_{cls.__tablename__}"),
        )


SettingField: TypeAlias = (
    BaseItemField
    | Literal[
        "user_id",
        "name",
        "value",
    ]
)
SettingOrder: TypeAlias = (
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
    user_id: UUID | Sequence[UUID] | None = None
    """Filter by `user_id` being equal to one or more given UUIDs."""
    name: str | Sequence[str] | None = None
    """Filter by `name` being equal to one or more given names."""

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
    name: str
    value: FromYAML[JSONValue]


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
