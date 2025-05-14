from __future__ import annotations

from abc import abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, ClassVar, Iterable, Literal, Self, TypeAlias, override

from pydantic import Field, NonNegativeInt, PositiveInt
from pydantic.functional_validators import model_validator
from sqlalchemy import cast, func, literal, select
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import Index, SchemaItem
from sqlalchemy.sql import SQLColumnExpression
from sqlalchemy.types import Integer

from ceres._internal import util
from ceres._internal.database.types import DateTimeMapper
from ceres._internal.entity import (
    BaseUUIDEntity,
    BaseUUIDEntityField,
    BaseUUIDEntityFilter,
    BaseUUIDEntityFilterArgs,
    BaseUUIDEntityOrder,
    BaseUUIDEntityRow,
    BaseUUIDEntityUpdate,
)
from ceres._internal.item import (
    BaseItem,
    BaseItemField,
    BaseItemFilter,
    BaseItemFilterArgs,
    BaseItemOrder,
    BaseItemRow,
    BaseItemUpdate,
)
from ceres.data import DateTime, MaybeSequence, NonNegativeTimeDelta, PositiveTimeDelta, StrEnum
from ceres.database import DatabaseType
from ceres.timing import utc


class BaseRecordRow(BaseItemRow, BaseUUIDEntityRow, kw_only=True):
    __abstract__: ClassVar[bool] = True

    timestamp: Mapped[datetime] = mapped_column(DateTimeMapper, sort_order=-1000)

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            Index(f"ix_{cls.__tablename__}__timestamp", "timestamp"),
        )


BaseRecordField: TypeAlias = BaseUUIDEntityField | BaseItemField | Literal["timestamp"]
BaseRecordOrder: TypeAlias = (
    BaseUUIDEntityOrder
    | BaseItemOrder
    | Literal[
        "timestamp",
        "timestamp:asc",
        "timestamp:desc",
    ]
)


class SubsampleSelect(StrEnum):
    """
    Specifies which sample to choose per subsampled time bucket.
    """

    FIRST = "first"
    """Choose the first sample in each time bucket."""
    LAST = "last"
    """Choose the last sample in each time bucket."""


class BaseRecordFilterArgs[
    FieldT: str,
    OrderT: str,
](
    BaseItemFilterArgs[FieldT, OrderT],
    BaseUUIDEntityFilterArgs[FieldT, OrderT],
    total=False,
):
    timestamp: MaybeSequence[DateTime] | None
    before: DateTime | None
    after: DateTime | None
    timespan: NonNegativeTimeDelta | None
    max_age: NonNegativeTimeDelta | None
    min_age: NonNegativeTimeDelta | None
    subsample_every: PositiveTimeDelta | None
    subsample: PositiveInt | None
    subsample_select: SubsampleSelect | None
    after_hour: NonNegativeInt | None
    before_hour: NonNegativeInt | None
    after_minute: NonNegativeInt | None
    before_minute: NonNegativeInt | None


class BaseRecordFilter[
    RecordT: BaseRecord,
    FieldT: str,
    OrderT: str,
](
    BaseItemFilter[RecordT, FieldT, OrderT],
    BaseUUIDEntityFilter[RecordT, FieldT, OrderT],
):
    timestamp: MaybeSequence[DateTime] | None = None
    """Filter by `timestamp` being exactly equal to one or more given datetimes."""
    after: DateTime | None = None
    """Filter by `timestamp` being greater than or equal to a given datetime."""
    before: DateTime | None = None
    """Filter by `timestamp` being less than a given datetime."""

    timespan: PositiveTimeDelta | None = None
    """
    Filter by maximum age relative to `after`, or minimum age relative to `before` if `after` is
    `None`. If both `after` and `before` are `None`, filter by maximum age relative to the current
    time.
    """

    min_age: NonNegativeTimeDelta | None = None
    """
    Filter by the age of `timestamp`, relative to the current time, being greater than or equal to a
    given threshold.
    """

    max_age: NonNegativeTimeDelta | None = None
    """
    Filter by the age of `timestamp`, relative to the current time, being less than a given
    threshold.
    """

    subsample_every: PositiveTimeDelta | None = None
    """
    Subsample results, selecting at most one record per this interval of time.

    For example, setting `timespan` to 1 hour and `subsample_every` to 1 minute will select one
    record per minute for the last hour, with the total number of time buckets, meaning possible
    samples, being equal 60.
    """

    subsample: PositiveInt | None = None
    """
    Subsample results, selecting at most one record per `subsample` divisions of the total time
    range specified by this filter.

    To use `subsample`, a clear start and end to the filtered time range must be specified using
    some combination of time range filter fields, including: `after`, `before`, `timespan`,
    `min_age`, and/or `max_age`.

    For example, setting `timespan` to 1 hour and `subsample` to 60 will select one record per
    minute for the last hour, with the total number of time buckets, meaning possible samples, being
    equal to 60.
    """

    subsample_select: SubsampleSelect | None = None
    """
    Specify which record to choose per subsampled time bucket specified by `subsample_every` and
    `subsample`. If unspecified or `None`, this will default to `SubsampleSelect.FIRST`.
    """

    after_hour: NonNegativeInt | None = Field(default=None, le=24)
    """Filter by the hour value of `timestamp` being greater than or equal to a given value."""
    before_hour: NonNegativeInt | None = Field(default=None, le=24)
    """Filter by the hour value of `timestamp` being less than a given value."""
    after_minute: NonNegativeInt | None = Field(default=None, le=60)
    """Filter by the minute value of `timestamp` being greater than or equal to a given value."""
    before_minute: NonNegativeInt | None = Field(default=None, le=60)
    """Filter by the minute of `timestamp` being less than a given value."""

    @model_validator(mode="after")
    def _validate_subsample(self) -> Self:
        if self.subsample is None:
            return self

        start, end = self._get_time_bounds(utc())
        if start is None or end is None:
            if start is None and end is None:
                subject = "Start and end time"
            elif start is None:
                subject = "Start time"
            else:
                subject = "End time"

            message = (
                "for `subsample` time range could not be determined. "
                "`timespan` requires a clear start and end to the filtered time range to be "
                "specified using some combination of time range filter fields, including: `after`, "
                "`before`, `timespan`, `min_age` and/or `max_age`."
            )

            raise ValueError(f"{subject} {message}")

        return self

    @override
    def matches(self, obj: RecordT, *, now: datetime | None = None) -> bool:
        if not super().matches(obj):
            return False

        if self.timestamp is not None:
            if obj.timestamp not in util.as_sequence(self.timestamp):
                return False
        if self.after is not None:
            if obj.timestamp < self.after:
                return False
        if self.before is not None:
            if obj.timestamp >= self.before:
                return False

        now = utc(now)
        if self.timespan is not None:
            if self.after is not None:
                if obj.timestamp >= (self.after + self.timespan):
                    return False
            elif self.before is not None:
                if obj.timestamp < ((self.before or now) - self.timespan):
                    return False
            else:
                if obj.timestamp < now - self.timespan:
                    return False
                if obj.timestamp >= now:
                    return False

        if self.max_age is not None:
            if obj.timestamp <= now - self.max_age:
                return False
        if self.min_age is not None:
            if obj.timestamp > now - self.min_age:
                return False

        if self.after_hour is not None or self.before_hour is not None:
            min_hour = self.after_hour if self.after_hour is not None else 0
            max_hour = self.before_hour if self.before_hour is not None else 24
            within_min = obj.timestamp.hour >= min_hour
            within_max = obj.timestamp.hour < max_hour
            if min_hour <= max_hour:
                if not within_min or not within_max:
                    return False
            else:
                if not within_min and not within_max:
                    return False

        if self.after_minute is not None or self.before_minute is not None:
            min_minute = self.after_minute if self.after_minute is not None else 0
            max_minute = self.before_minute if self.before_minute is not None else 60
            within_min = obj.timestamp.minute >= min_minute
            within_max = obj.timestamp.minute < max_minute
            if min_minute <= max_minute:
                if not within_min or not within_max:
                    return False
            else:
                if not within_min and not within_max:
                    return False

        return True

    @classmethod
    @abstractmethod
    @override
    def _get_row_cls(cls) -> type[BaseRecordRow]: ...

    @override
    def _get_where(
        self,
        dialect: DatabaseType,
        *,
        now: datetime | None = None,
    ) -> Iterable[SQLColumnExpression[bool]]:
        yield from super()._get_where(dialect)
        columns = self._get_row_cls()

        if self.timestamp is not None:
            yield util.sql_match_value(columns.timestamp, self.timestamp)
        if self.after is not None:
            yield columns.timestamp >= self.after
        if self.before is not None:
            yield columns.timestamp < self.before

        now = utc(now)
        if self.timespan is not None:
            if self.after is not None:
                yield columns.timestamp < self.after + self.timespan
            elif self.before is not None:
                yield columns.timestamp >= self.before - self.timespan
            else:
                yield columns.timestamp >= now - self.timespan
                yield columns.timestamp < now

        if self.max_age is not None:
            yield columns.timestamp > now - self.max_age
        if self.min_age is not None:
            yield columns.timestamp <= now - self.min_age

        if self.subsample_every is not None or self.subsample is not None:
            start, end = self._get_time_bounds(now)

            match self.subsample_select:
                case SubsampleSelect.FIRST | None:
                    subsample_selector = func.min
                case SubsampleSelect.LAST:
                    subsample_selector = func.max

            if self.subsample_every is not None:
                seed = (
                    start
                    if start is not None
                    # If there's no start time, use beginning of current hour.
                    else now.replace(
                        hour=0,
                        minute=0,
                        second=0,
                        microsecond=0,
                    )
                )

                matches = (
                    select(
                        bin := func.date_bin(
                            self.subsample_every,
                            columns.timestamp,
                            seed,
                        ).label("bin"),
                        subsample_selector(columns.timestamp).label("timestamp"),
                    )
                    .where(
                        *([columns.timestamp >= start] if start is not None else ()),
                        *([columns.timestamp < end] if end is not None else ()),
                    )
                    .group_by(bin)
                ).cte("matches")

                yield columns.timestamp.in_(select(matches.columns.timestamp).select_from(matches))

            if self.subsample is not None:
                # These should have already been validated.
                assert start is not None
                assert end is not None

                matches = (
                    select(
                        bin := func.date_bin(
                            (end - start) / max(self.subsample, 1),
                            columns.timestamp,
                            start,
                        ).label("bin"),
                        subsample_selector(columns.timestamp).label("timestamp"),
                    )
                    .where(columns.timestamp >= start)
                    .where(columns.timestamp < end)
                    .group_by(bin)
                ).cte("matches")

                yield columns.timestamp.in_(select(matches.columns.timestamp).select_from(matches))

        if self.after_hour is not None or self.before_hour is not None:
            min_hour = self.after_hour if self.after_hour is not None else 0
            max_hour = self.before_hour if self.before_hour is not None else 24
            match dialect:
                case DatabaseType.POSTGRES:
                    hour = func.date_part(
                        literal("hour", literal_execute=True),
                        columns.timestamp.op("AT TIME ZONE")(literal("UTC", literal_execute=True)),
                    )
                case DatabaseType.SQLITE:
                    hour = cast(func.strftime("%H", columns.timestamp), Integer)

            within_min = hour >= min_hour
            within_max = hour < max_hour
            if min_hour <= max_hour:
                yield within_min & within_max
            else:
                yield within_min | within_max

        if self.after_minute is not None or self.before_minute is not None:
            min_minute = self.after_minute if self.after_minute is not None else 0
            max_minute = self.before_minute if self.before_minute is not None else 60
            match dialect:
                case DatabaseType.POSTGRES:
                    minute = func.date_part(
                        literal("minute", literal_execute=True),
                        columns.timestamp.op("AT TIME ZONE")(literal("UTC", literal_execute=True)),
                    )
                case DatabaseType.SQLITE:
                    minute = cast(func.strftime("%M", columns.timestamp), Integer)

            within_min = minute >= min_minute
            within_max = minute < max_minute
            if min_minute <= max_minute:
                yield within_min & within_max
            else:
                yield within_min | within_max

    @override
    def _get_default_order(self) -> OrderT:
        return "timestamp"  # type: ignore

    def _get_time_bounds(self, now: datetime) -> tuple[datetime | None, datetime | None]:
        starts: list[datetime] = []
        ends: list[datetime] = []

        if self.after is not None:
            starts.append(self.after)
        if self.before is not None:
            ends.append(self.before)

        if self.timespan is not None:
            if self.after is not None:
                ends.append(self.after + self.timespan)
            elif self.before is not None:
                starts.append(self.before - self.timespan)
            else:
                starts.append(now - self.timespan)
                ends.append(now)

        if self.max_age is not None:
            starts.append(now - self.max_age)
        if self.min_age is not None:
            ends.append(now - self.min_age)

        start = max(starts) if starts else None
        end = min(ends) if ends else None

        return start, end


class BaseRecordCreate(BaseItem, BaseUUIDEntity):
    timestamp: DateTime = Field(default_factory=utc)


class BaseRecordUpdate(BaseItemUpdate, BaseUUIDEntityUpdate, total=False):
    timestamp: DateTime


class BaseRecord(BaseRecordCreate):
    Row: ClassVar[type[BaseRecordRow]] = BaseRecordRow
    Create: ClassVar[type[BaseRecordCreate]] = BaseRecordCreate
    Update: ClassVar[type[BaseRecordUpdate]] = BaseRecordUpdate

    if TYPE_CHECKING:
        Filter: ClassVar = BaseRecordFilter
        FilterArgs: ClassVar = BaseRecordFilterArgs
        Field: ClassVar = BaseRecordField
        Order: ClassVar = BaseRecordOrder
    else:
        Filter: ClassVar[type[BaseRecordFilter]] = BaseRecordFilter
        FilterArgs: ClassVar[type[BaseRecordFilterArgs]] = BaseRecordFilterArgs
        Field: ClassVar[type[BaseRecordField]] = BaseRecordField
        Order: ClassVar[type[BaseRecordOrder]] = BaseRecordOrder
