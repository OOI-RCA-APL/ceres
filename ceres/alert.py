from __future__ import annotations

from datetime import datetime
from typing import (
    Annotated,
    ClassVar,
    Iterable,
    Literal,
    Sequence,
    TypeAlias,
    TypedDict,
    override,
)

from pydantic import Field
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import JSON, Text

from ceres._internal.cli.plumbing import CLIOption
from ceres._internal.database.types import EnumConstraint, EnumMapper
from ceres._internal.entity import (
    BaseRecord,
    BaseRecordCreate,
    BaseRecordField,
    BaseRecordFilter,
    BaseRecordFilterArgs,
    BaseRecordOrder,
    BaseRecordRow,
)
from ceres._internal.lazy import lazy_imports
from ceres.address import Address
from ceres.data import DateTime, JSONDict, jsonify
from ceres.database.enums import DatabaseType
from ceres.level import Level
from ceres.timing import utc

with lazy_imports(__name__):
    from sqlalchemy.schema import Index, SchemaItem
    from sqlalchemy.sql import SQLColumnExpression, cast, or_

    from ceres._internal import util


class AlertRow(BaseRecordRow, kw_only=True):
    __tablename__: ClassVar[str] = "alerts"

    level: Mapped[Level] = mapped_column(EnumMapper(Level))
    type: Mapped[str] = mapped_column(Text)
    data: Mapped[JSONDict] = mapped_column(
        JSON,
        default_factory=dict,
        server_default="{}",
    )

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            EnumConstraint("level", Level, f"ck_{cls.__tablename__}__level"),
            Index(
                f"ix_{cls.__tablename__}__type",
                cls.type,
                postgresql_ops={"type": "gin_trgm_ops"},
                postgresql_using="gin",
            ),
        )


AlertField: TypeAlias = (
    BaseRecordField
    | Literal[
        "level",
        "type",
        "data",
    ]
)
AlertOrder: TypeAlias = (
    BaseRecordOrder
    | Literal[
        "level",
        "-level",
        "type",
        "-type",
    ]
)


class AlertFilterArgs(BaseRecordFilterArgs[AlertField, AlertOrder], total=False):
    level: Level | Sequence[Level] | None
    type: str | Sequence[str] | None
    type_contains: str | Sequence[str] | None
    type_prefix: str | Sequence[str] | None
    type_suffix: str | Sequence[str] | None
    data_contains: str | Sequence[str] | None
    data_prefix: str | Sequence[str] | None
    data_suffix: str | Sequence[str] | None


class AlertFilter(BaseRecordFilter["Alert", AlertField, AlertOrder]):
    level: Annotated[Level | Sequence[Level] | None, CLIOption(list[Level] | None)] = Field(
        default=None,
        description="Filter by alert level(s).",
    )
    type: Annotated[str | Sequence[str] | None, CLIOption(list[str] | None)] = Field(
        default=None,
        description="Filter by alert types(s).",
    )
    type_contains: Annotated[str | Sequence[str] | None, CLIOption(str | None)] = Field(
        default=None,
        description="Filter by alert type(s) containing a given substring.",
    )
    type_prefix: Annotated[str | Sequence[str] | None, CLIOption(str | None)] = Field(
        default=None,
        description="Filter by alert type(s) with a common prefix.",
    )
    type_suffix: Annotated[str | Sequence[str] | None, CLIOption(str | None)] = Field(
        default=None,
        description="Filter by alert type(s) with a common suffix.",
    )
    data_contains: Annotated[str | Sequence[str] | None, CLIOption(str)] = Field(
        default=None,
        description="Filter alert data containing a given substring.",
    )
    data_prefix: Annotated[str | Sequence[str] | None, CLIOption(str)] = Field(
        default=None,
        description="Filter alert data with a common prefix.",
    )
    data_suffix: Annotated[str | Sequence[str] | None, CLIOption(str)] = Field(
        default=None,
        description="Filter alert data with a common suffix.",
    )

    @override
    def matches(self, obj: Alert, *, now: datetime | None = None) -> bool:
        now = utc(now)
        if not super().matches(obj, now=now):
            return False

        if self.level is not None:
            if obj.level not in util.as_sequence(self.level):
                return False

        if self.type is not None:
            if obj.type not in util.as_sequence(self.type):
                return False
        if self.type_contains is not None:
            if not any(obj.type in substring for substring in util.as_sequence(self.type_contains)):
                return False
        if self.type_prefix is not None:
            if not any(
                obj.type.startswith(prefix) for prefix in util.as_sequence(self.type_prefix)
            ):
                return False
        if self.type_suffix is not None:
            if not any(
                obj.type.startswith(suffix) for suffix in util.as_sequence(self.type_suffix)
            ):
                return False

        if (
            self.data_contains is not None
            or self.data_prefix is not None
            or self.data_suffix is not None
        ):
            data_json = jsonify(obj.data)
            if self.data_contains is not None:
                if not any(
                    substring in data_json for substring in util.as_sequence(self.data_contains)
                ):
                    return False
            if self.data_prefix is not None:
                if not any(
                    data_json.startswith(prefix) for prefix in util.as_sequence(self.data_prefix)
                ):
                    return False
            if self.data_suffix is not None:
                if not any(
                    data_json.startswith(suffix) for suffix in util.as_sequence(self.data_suffix)
                ):
                    return False

        return True

    @classmethod
    @override
    def _get_row_cls(cls) -> type[AlertRow]:
        return AlertRow

    @override
    def _get_where(
        self,
        dialect: DatabaseType,
        *,
        now: datetime | None = None,
    ) -> Iterable[SQLColumnExpression[bool]]:
        now = utc(now)
        yield from super()._get_where(dialect, now=now)
        columns = self._get_row_cls()

        if self.level is not None:
            yield columns.level.in_(util.as_sequence(self.level))

        if self.type is not None:
            yield columns.type.in_(util.as_sequence(self.type))
        if self.type_contains is not None:
            yield or_(
                False,
                *(columns.type.contains(type) for type in util.as_sequence(self.type_contains)),
            )
        if self.type_prefix is not None:
            yield or_(
                False,
                *(columns.type.startswith(prefix) for prefix in util.as_sequence(self.type_prefix)),
            )
        if self.type_suffix is not None:
            yield or_(
                False,
                *(columns.type.endswith(suffix) for suffix in util.as_sequence(self.type_suffix)),
            )

        if self.data_contains is not None:
            yield or_(
                False,
                *(
                    cast(columns.data, Text).contains(substring)
                    for substring in util.as_sequence(self.data_contains)
                ),
            )
        if self.data_prefix is not None:
            yield or_(
                False,
                *(
                    cast(columns.data, Text).startswith(prefix)
                    for prefix in util.as_sequence(self.data_prefix)
                ),
            )
        if self.data_suffix is not None:
            yield or_(
                False,
                *(
                    cast(columns.data, Text).endswith(suffix)
                    for suffix in util.as_sequence(self.data_suffix)
                ),
            )


class AlertCreate(BaseRecordCreate):
    level: Annotated[Level, CLIOption(Level)]
    type: Annotated[str, CLIOption(str)]
    data: Annotated[JSONDict, CLIOption(str)] = Field(default_factory=dict)


class AlertUpdate(TypedDict, total=False):
    address: Address
    timestamp: DateTime
    level: Level
    type: str
    data: JSONDict


class Alert(BaseRecord, AlertCreate):
    Row: ClassVar[type[AlertRow]] = AlertRow
    Create: ClassVar[type[AlertCreate]] = AlertCreate
    Update: ClassVar[type[AlertUpdate]] = AlertUpdate
    Filter: ClassVar[type[AlertFilter]] = AlertFilter
    FilterArgs: ClassVar[type[AlertFilterArgs]] = AlertFilterArgs
    Field = AlertField
    Order = AlertOrder
