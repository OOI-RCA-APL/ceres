from __future__ import annotations

from datetime import datetime
from typing import (
    ClassVar,
    Iterable,
    Literal,
    TypeAlias,
    TypedDict,
    override,
)

from pydantic import Field
from sqlalchemy import JSON, SQLColumnExpression, Text, cast
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import Index, SchemaItem

from ceres._internal import util
from ceres._internal.database.types import EnumConstraint, EnumMapper
from ceres._internal.record import (
    BaseRecord,
    BaseRecordCreate,
    BaseRecordField,
    BaseRecordFilter,
    BaseRecordFilterArgs,
    BaseRecordOrder,
    BaseRecordRow,
)
from ceres.address import Address
from ceres.data import DateTime, FromYaml, JSONSerializableDict, MaybeSequence, jsonify
from ceres.database import DatabaseType
from ceres.level import Level
from ceres.timing import utc


class AlertRow(BaseRecordRow, kw_only=True):
    __tablename__: ClassVar[str] = "alerts"

    level: Mapped[Level] = mapped_column(EnumMapper(Level))
    type: Mapped[str] = mapped_column(Text)
    data: Mapped[JSONSerializableDict] = mapped_column(
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
    level: MaybeSequence[Level] | None
    type: MaybeSequence[str] | None
    type_contains: MaybeSequence[str] | None
    type_prefix: MaybeSequence[str] | None
    type_suffix: MaybeSequence[str] | None
    data_contains: MaybeSequence[str] | None
    data_prefix: MaybeSequence[str] | None
    data_suffix: MaybeSequence[str] | None


class AlertFilter(BaseRecordFilter["Alert", AlertField, AlertOrder]):
    level: MaybeSequence[Level] | None = None
    """Filter by `level` being equal to one or more given levels."""
    type: MaybeSequence[str] | None = None
    """Filter by `type` being equal to one or more given types."""
    type_contains: MaybeSequence[str] | None = None
    """Filter by `type` containing one or more given substrings."""
    type_prefix: MaybeSequence[str] | None = None
    """Filter by `type` starting with one or more given prefixes."""
    type_suffix: MaybeSequence[str] | None = None
    """Filter by `type` ending with one or more given suffixes."""
    data_contains: MaybeSequence[str] | None = None
    """Filter by whether or not the JSON text of `data` contains one or more given substrings."""
    data_prefix: MaybeSequence[str] | None = None
    """Filter by whether or not the JSON text of `data` starts with one or more given prefixes."""
    data_suffix: MaybeSequence[str] | None = None
    """Filter by whether or not the JSON text of `data` ends with one or more given suffixes."""

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
            if not any(substring in obj.type for substring in util.as_sequence(self.type_contains)):
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
            yield util.sqlorf(
                columns.type.contains(type) for type in util.as_sequence(self.type_contains)
            )
        if self.type_prefix is not None:
            yield util.sqlorf(
                columns.type.startswith(prefix) for prefix in util.as_sequence(self.type_prefix)
            )
        if self.type_suffix is not None:
            yield util.sqlorf(
                columns.type.endswith(suffix) for suffix in util.as_sequence(self.type_suffix)
            )

        if self.data_contains is not None:
            yield util.sqlorf(
                cast(columns.data, Text).contains(substring)
                for substring in util.as_sequence(self.data_contains)
            )
        if self.data_prefix is not None:
            yield util.sqlorf(
                cast(columns.data, Text).startswith(prefix)
                for prefix in util.as_sequence(self.data_prefix)
            )
        if self.data_suffix is not None:
            yield util.sqlorf(
                cast(columns.data, Text).endswith(suffix)
                for suffix in util.as_sequence(self.data_suffix)
            )


class AlertCreate(BaseRecordCreate):
    level: Level
    type: str
    data: FromYaml[JSONSerializableDict] = Field(default_factory=dict)


class AlertUpdate(TypedDict, total=False):
    address: Address
    timestamp: DateTime
    level: Level
    type: str
    data: FromYaml[JSONSerializableDict]


class Alert(BaseRecord, AlertCreate):
    Row: ClassVar[type[AlertRow]] = AlertRow
    Create: ClassVar[type[AlertCreate]] = AlertCreate
    Update: ClassVar[type[AlertUpdate]] = AlertUpdate
    Filter: ClassVar[type[AlertFilter]] = AlertFilter
    FilterArgs: ClassVar[type[AlertFilterArgs]] = AlertFilterArgs
    Field = AlertField
    Order = AlertOrder
