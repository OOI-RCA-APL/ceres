from typing import Self

from pydantic import Field, NonNegativeInt, PositiveInt, model_validator

from ceres.__internal__.entity import (
    BaseAddressEntity,
    BaseAddressEntityCreate,
    BaseAddressEntityField,
    BaseAddressEntityFilter,
    BaseAddressEntityFilterArgs,
    BaseAddressEntityOrder,
    BaseAddressEntityUpdate,
    BaseEntity,
    BaseTimestampEntity,
    BaseTimestampEntityCreate,
    BaseTimestampEntityField,
    BaseTimestampEntityFilter,
    BaseTimestampEntityFilterArgs,
    BaseTimestampEntityOrder,
    BaseTimestampEntityUpdate,
    BaseUUIDEntity,
    BaseUUIDEntityCreate,
    BaseUUIDEntityField,
    BaseUUIDEntityFilter,
    BaseUUIDEntityFilterArgs,
    BaseUUIDEntityOrder,
    BaseUUIDEntityUpdate,
)
from ceres.data import DateTime, MaybeSequence, NonNegativeTimeDelta, PositiveTimeDelta, StrEnum
from ceres.timing import utc

type BaseRecordField = BaseUUIDEntityField | BaseAddressEntityField | BaseTimestampEntityField
type BaseRecordOrder = BaseUUIDEntityOrder | BaseAddressEntityOrder | BaseTimestampEntityOrder


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
