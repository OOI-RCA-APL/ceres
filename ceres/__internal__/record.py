from abc import abstractmethod
from collections.abc import Iterable
from datetime import timedelta
from typing import TYPE_CHECKING, Any, ClassVar, Self, override

from pydantic import Field, NonNegativeInt, PositiveInt, model_validator
from sqlalchemy import Integer, cast, func, literal, select

from ceres.__internal__.entity import (
    BaseAddressEntity,
    BaseAddressEntityCreate,
    BaseAddressEntityField,
    BaseAddressEntityFilter,
    BaseAddressEntityFilterArgs,
    BaseAddressEntityOrder,
    BaseAddressEntityRow,
    BaseAddressEntityUpdate,
    BaseEntity,
    BaseTimestampEntity,
    BaseTimestampEntityCreate,
    BaseTimestampEntityField,
    BaseTimestampEntityFilter,
    BaseTimestampEntityFilterArgs,
    BaseTimestampEntityOrder,
    BaseTimestampEntityRow,
    BaseTimestampEntityUpdate,
    BaseUUIDEntity,
    BaseUUIDEntityCreate,
    BaseUUIDEntityField,
    BaseUUIDEntityFilter,
    BaseUUIDEntityFilterArgs,
    BaseUUIDEntityOrder,
    BaseUUIDEntityRow,
    BaseUUIDEntityUpdate,
)
from ceres.__internal__.utilities.collections import seq
from ceres.data import DateTime, MaybeSequence, NonNegativeTimeDelta, PositiveTimeDelta, StrEnum
from ceres.database import DatabaseType
from ceres.timing import utc

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy import SQLColumnExpression


class BaseRecordRow(
    BaseTimestampEntityRow,
    BaseAddressEntityRow,
    BaseUUIDEntityRow,
    kw_only=True,
):
    """Abstract SQLAlchemy row combining UUID, address, and timestamp columns for records."""

    __abstract__: ClassVar[bool] = True


type BaseRecordField = BaseUUIDEntityField | BaseAddressEntityField | BaseTimestampEntityField
type BaseRecordOrder = BaseUUIDEntityOrder | BaseAddressEntityOrder | BaseTimestampEntityOrder


def _microseconds_of(value: Any) -> SQLColumnExpression[Any]:
    """Pull the microsecond part out of a stored timestamp.

    SQLite and Turso read a timestamp's fraction only as far as milliseconds, so the value has to
    be taken from the text itself to keep the last three digits. The date and time occupy a fixed
    nineteen characters, leaving the fraction from the twentieth on, and padding covers a value
    written without one, which is what SQLite's own `CURRENT_TIMESTAMP` default produces.
    """
    fraction = func.substr(value, 20).concat(".000000")
    return cast(func.substr(fraction, 2, 6), Integer)


def _date_bin(
    dialect: DatabaseType,
    interval: timedelta,
    timestamp: Any,
    origin: Any,
) -> SQLColumnExpression[Any]:
    """Group timestamps into buckets `interval` wide, measured from `origin`.

    PostgreSQL has `date_bin` built in. The SQLite family does not, and Turso cannot be taught it,
    because it has no way to register a function. The bucket is only ever grouped by and never
    selected, so any value that stays constant across a bucket does the job, and an integer index
    is the cheapest one to compute.

    Whole seconds and microseconds are kept apart and combined as integers so the arithmetic is
    exact. Doing it in floating point loses enough precision to drop a timestamp sitting exactly on
    a bucket boundary into the bucket below, and records aligned to the origin are the ordinary
    case.

    Args:
        dialect: The backend the expression is being built for.
        interval: Bucket width.
        timestamp: The column holding the timestamp to bin.
        origin: The instant buckets are measured from.

    Returns:
        A SQL expression identifying which bucket a row falls in.
    """
    if dialect is DatabaseType.POSTGRES:
        return func.date_bin(interval, timestamp, origin)

    # A bucket narrower than the resolution timestamps are stored at would put every row in its
    # own, so one microsecond is the floor.
    width = max(interval // timedelta(microseconds=1), 1)
    seconds = func.unixepoch(timestamp) - func.unixepoch(origin)
    microseconds = seconds * 1_000_000 + (_microseconds_of(timestamp) - _microseconds_of(origin))

    return cast(func.floor(microseconds / width), Integer)


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
    BaseTimestampEntityFilterArgs[FieldT, OrderT],
    BaseAddressEntityFilterArgs[FieldT, OrderT],
    BaseUUIDEntityFilterArgs[FieldT, OrderT],
    total=False,
):
    """TypedDict combining UUID, address, timestamp, and subsample filter keyword arguments."""

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
    BaseTimestampEntityFilter[RecordT, FieldT, OrderT],
    BaseAddressEntityFilter[RecordT, FieldT, OrderT],
    BaseUUIDEntityFilter[RecordT, FieldT, OrderT],
):
    """Filter for record queries, adding time-based subsampling on top of the standard filters."""

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
    def _matches(self, obj: RecordT, *, now: datetime | None = None) -> bool:
        if not super()._matches(obj):
            return False

        if self.timestamp is not None:
            if obj.timestamp not in seq(self.timestamp):
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

        now = utc(now)
        if self.subsample_every is not None or self.subsample is not None:
            start, end = self._get_time_bounds(now)

            match self.subsample_select:
                case SubsampleSelect.FIRST | None:
                    subsample_selector = func.min
                case SubsampleSelect.LAST:
                    subsample_selector = func.max

            if self.subsample_every is not None:
                interval = self.subsample_every

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
                        bin := _date_bin(
                            dialect,
                            interval,
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

                interval = (end - start) / max(self.subsample, 1)

                matches = (
                    select(
                        bin := _date_bin(
                            dialect,
                            interval,
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
                case DatabaseType.SQLITE | DatabaseType.TURSO:
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
                case DatabaseType.SQLITE | DatabaseType.TURSO:
                    minute = cast(func.strftime("%M", columns.timestamp), Integer)

            within_min = minute >= min_minute
            within_max = minute < max_minute
            if min_minute <= max_minute:
                yield within_min & within_max
            else:
                yield within_min | within_max

    @override
    def _get_default_order(self) -> MaybeSequence[OrderT]:
        return "timestamp"  # type: ignore


class BaseRecordCreate(
    BaseTimestampEntityCreate,
    BaseAddressEntityCreate,
    BaseUUIDEntityCreate,
    abstract=True,
    slots=True,
):
    """Base creation data for records, defaulting `timestamp` to the current UTC time."""

    timestamp: DateTime = Field(default_factory=utc)


class BaseRecordUpdate(
    BaseTimestampEntityUpdate,
    BaseAddressEntityUpdate,
    BaseUUIDEntityUpdate,
    total=False,
):
    """TypedDict of mutable record fields available for update operations."""

    timestamp: DateTime


class BaseRecord(
    BaseTimestampEntity,
    BaseAddressEntity,
    BaseUUIDEntity,
    BaseEntity,
    BaseRecordCreate,
    abstract=True,
    slots=True,
):
    """Abstract base for record entities that combine a UUID, address, and timestamp."""

    pass
