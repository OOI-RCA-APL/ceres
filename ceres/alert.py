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

from pydantic import Field, field_validator
from sqlalchemy.dialects.postgresql import JSONB

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

with lazy_imports(__name__):
    from sqlalchemy.orm import Mapped, mapped_column
    from sqlalchemy.schema import Index, SchemaItem
    from sqlalchemy.sql import SQLColumnExpression, cast
    from sqlalchemy.sql.sqltypes import JSON, Text

    from ceres._internal import util


class AlertRow(BaseRecordRow, kw_only=True):
    __tablename__: ClassVar[str] = "alerts"

    level: Mapped[Level] = mapped_column(EnumMapper(Level))
    code: Mapped[str] = mapped_column(Text)
    info: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
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
                f"ix_{cls.__tablename__}__code",
                "code",
                postgresql_ops={"code": "gin_trgm_ops"},
                postgresql_using="gin",
            ),
        )


AlertField = (
    BaseRecordField
    | Literal[
        "level",
        "code",
        "info",
    ]
)
AlertOrder = (
    BaseRecordOrder
    | Literal[
        "level",
        "-level",
        "code",
        "-code",
    ]
)


class AlertFilterArgs(BaseRecordFilterArgs[AlertField, AlertOrder], total=False):
    level: Level | Sequence[Level] | None
    code: str | Sequence[str] | None
    code_contains: str | None
    code_prefix: str | None
    code_suffix: str | None


class AlertFilter(BaseRecordFilter["Alert", AlertField, AlertOrder]):
    level: Annotated[Level | Sequence[Level] | None, CLIOption(list[Level] | None)] = Field(
        default=None,
        description="Filter by alert level(s).",
    )
    code: Annotated[str | Sequence[str] | None, CLIOption(list[str] | None)] = Field(
        default=None,
        description="Filter by alert code(s).",
    )
    code_contains: Annotated[str | None, CLIOption(str | None)] = Field(
        default=None,
        description="Filter, keeping only alerts with codes that contain the given string.",
    )
    code_prefix: Annotated[str | None, CLIOption(str | None)] = Field(
        default=None,
        description="Filter, keeping only alerts with codes that start with the given string.",
    )
    code_suffix: Annotated[str | None, CLIOption(str | None)] = Field(
        default=None,
        description="Filter, keeping only alerts with codes that end with the given string.",
    )

    @override
    def matches(self, obj: Alert) -> bool:
        if not super().matches(obj):
            return False

        if self.level is not None:
            if obj.level not in util.as_sequence(self.level):
                return False
        if self.code is not None:
            if obj.code not in util.as_sequence(self.code):
                return False
        if self.code_contains is not None:
            if self.code_contains not in obj.code:
                return False
        if self.code_prefix is not None:
            if not obj.code.startswith(self.code_prefix):
                return False
        if self.code_suffix is not None:
            if not obj.code.endswith(self.code_suffix):
                return False

        return True

    @classmethod
    @override
    def _get_row_cls(cls) -> type[AlertRow]:
        return AlertRow

    @override
    def _get_search_content(self, obj: Alert) -> Mapping[str, str]:
        return {
            **super()._get_search_content(obj),
            "level": obj.level,
            "code": obj.code,
            "info": jsonify(obj.info),
        }

    @override
    def _get_database_search_content(
        self,
        dialect: DatabaseType,
    ) -> Mapping[str, SQLColumnExpression[Any]]:
        columns = self._get_row_cls()

        match dialect:
            case DatabaseType.POSTGRES:
                info = cast(columns.info, Text)
            case DatabaseType.SQLITE:
                info = columns.info

        return {
            **super()._get_database_search_content(dialect),
            "level": columns.level,
            "code": columns.code,
            "info": info,
        }

    @override
    def _get_where(self, dialect: DatabaseType) -> Iterable[SQLColumnExpression[bool]]:
        yield from super()._get_where(dialect)
        columns = self._get_row_cls()

        if self.level is not None:
            yield columns.level.in_(util.as_sequence(self.level))
        if self.code is not None:
            yield columns.code.in_(util.as_sequence(self.code))
        if self.code_contains is not None:
            yield columns.code.like("%" + util.escape_like_expression(self.code_contains) + "%")
        if self.code_prefix is not None:
            yield columns.code.like(util.escape_like_expression(self.code_prefix) + "%")
        if self.code_suffix is not None:
            yield columns.code.like("%" + util.escape_like_expression(self.code_suffix))


class AlertCreate(BaseRecordCreate):
    level: Annotated[Level, CLIOption(Level)]
    code: Annotated[str, CLIOption(str)]
    info: Annotated[JSONDict, CLIOption(str)] = Field(default_factory=dict)

    @field_validator("info")
    def _validate_info(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            jsonify(value)
        except Exception:
            raise ValueError("info must be a JSON serializable mapping")

        return value


class AlertUpdate(TypedDict, total=False):
    address: Address
    timestamp: DateTime
    level: Level
    code: str
    info: JSONDict


class Alert(BaseRecord, AlertCreate):
    Row: ClassVar[type[AlertRow]] = AlertRow
    Create: ClassVar[type[AlertCreate]] = AlertCreate
    Update: ClassVar[type[AlertUpdate]] = AlertUpdate
    Filter: ClassVar[type[AlertFilter]] = AlertFilter
    FilterArgs: ClassVar[type[AlertFilterArgs]] = AlertFilterArgs
    Field = AlertField
    Order = AlertOrder
