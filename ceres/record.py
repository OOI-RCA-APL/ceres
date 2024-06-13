from __future__ import annotations

from abc import abstractmethod
from datetime import datetime
from typing import Annotated, Any, ClassVar, Iterable, Literal, override

from pydantic import Field

from ceres._internal.cli.plumbing import CLIOption
from ceres._internal.database.types import DateTimeMapper
from ceres._internal.lazy import lazy_imports
from ceres.data import DateTime, PositiveTimeDelta
from ceres.database.enums import DatabaseType
from ceres.item import BaseItem, BaseItemFilter, BaseItemFilterArgs, BaseItemRow, BaseItemUpdate
from ceres.timing import utc

with lazy_imports(__name__):
    from sqlalchemy.orm import Mapped, mapped_column
    from sqlalchemy.schema import Index, SchemaItem
    from sqlalchemy.sql import SQLColumnExpression

    from ceres._internal import util


class BaseRecordRow(BaseItemRow, kw_only=True):
    __abstract__: ClassVar[bool] = True

    timestamp: Mapped[datetime] = mapped_column(DateTimeMapper, sort_order=-1000)

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            Index(f"ix_{cls.__tablename__}__timestamp", "timestamp", postgresql_using="brin"),
        )


_RecordOrderInput = Literal["old-to-new", "new-to-old"]


class BaseRecordFilterArgs(BaseItemFilterArgs, total=False):
    within: PositiveTimeDelta | None
    after: DateTime | None
    before: DateTime | None
    order: _RecordOrderInput | None


class BaseRecordFilter[RecordT: BaseRecord](BaseItemFilter[RecordT]):
    within: Annotated[PositiveTimeDelta | None, CLIOption(str | None, metavar="DURATION")] = Field(
        default=None,
        description="Filter by age.",
    )
    after: Annotated[DateTime | None, CLIOption(datetime)] = Field(
        default=None,
        description="Filter by minimum timestamp.",
    )
    before: Annotated[DateTime | None, CLIOption(datetime)] = Field(
        default=None,
        description="Filter by maximum timestamp.",
    )
    order: Annotated[_RecordOrderInput | None, CLIOption(_RecordOrderInput | None)] = Field(
        default=None,
        description="Specify result order.",
    )

    @override
    def matches(self, obj: RecordT) -> bool:  # type: ignore
        if not super().matches(obj):
            return False

        if self.within is not None:
            if obj.timestamp < utc() - self.within:
                return False
        if self.after is not None:
            if obj.timestamp < self.after:
                return False
        if self.before is not None:
            if obj.timestamp >= self.before:
                return False

        return True

    @abstractmethod
    @override
    def _get_row_cls(self) -> type[BaseRecordRow]: ...

    @override
    def _get_search_content(self, obj: RecordT) -> dict[str, str]:
        return {
            **super()._get_search_content(obj),
            "timestamp": util.format_timestamp(obj.timestamp),
        }

    @override
    def _get_database_search_content(
        self,
        dialect: DatabaseType,
    ) -> dict[str, SQLColumnExpression[Any]]:
        columns = self._get_row_cls()

        return {
            **super()._get_database_search_content(dialect),
            "timestamp": util.format_sql_timestamp(columns.timestamp, dialect),
        }

    @override
    def _get_where(self, dialect: DatabaseType) -> Iterable[SQLColumnExpression[bool]]:
        yield from super()._get_where(dialect)
        columns = self._get_row_cls()

        if self.id is not None:
            yield columns.id.in_(util.as_sequence(self.id))
        if self.address is not None:
            yield self.address.matches_expression(columns.address, self.root)
        if self.within is not None:
            yield columns.timestamp >= utc() - self.within
        if self.after is not None:
            yield columns.timestamp >= self.after
        if self.before is not None:
            yield columns.timestamp < self.before

    @override
    def _get_order_by(self) -> SQLColumnExpression[Any]:
        columns = self._get_row_cls()

        match self.order:
            case None | "old-to-new":
                return columns.timestamp
            case "new-to-old":
                return columns.timestamp.desc()

        raise ValueError("invalid order type")


class BaseRecordCreate(BaseItem):
    timestamp: Annotated[DateTime, CLIOption(datetime)] = Field(default_factory=utc)


class BaseRecordUpdate(BaseItemUpdate, total=False):
    timestamp: DateTime


class BaseRecord(BaseRecordCreate):
    Row: ClassVar[type[BaseRecordRow]] = BaseRecordRow
    Create: ClassVar[type[BaseRecordCreate]] = BaseRecordCreate
    Update: ClassVar[type[BaseRecordUpdate]] = BaseRecordUpdate
    Filter: ClassVar[type[BaseRecordFilter[BaseRecord]]] = BaseRecordFilter
    FilterArgs: ClassVar[type[BaseRecordFilterArgs]] = BaseRecordFilterArgs
