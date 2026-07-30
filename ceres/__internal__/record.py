from abc import abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar, Self, override

from pydantic import Field, NonNegativeInt, PositiveInt, PrivateAttr, model_validator
from sqlalchemy import Delete, Select, Update, select, text, tuple_

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
from ceres.data import DateTime, MaybeSequence, NonNegativeTimeDelta, PositiveTimeDelta, StrEnum
from ceres.timing import utc

if TYPE_CHECKING:
    from ceres.database import DatabaseType


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

    _native_cache: Any = PrivateAttr(default=None)

    def _native_dump(self) -> str:
        """Serialize this filter for the native compiler, in its wire JSON form."""
        return self.model_dump_json(by_alias=True, exclude_none=True)

    def _native_filter(self) -> Any:
        """The native compiler's parsed form of this filter, built once and reused.

        The compiler is the single authority on filter semantics. Statements execute
        through the Python session, but their `WHERE` and `ORDER BY` come from here,
        and in-memory matching reads records through the same parsed filter.
        """
        if self._native_cache is None:
            from ceres_core import RecordTable, record_filter_from_json

            tables = {
                "messages": RecordTable.MESSAGES,
                "particles": RecordTable.PARTICLES,
                "alerts": RecordTable.ALERTS,
                "logs": RecordTable.LOGS,
            }
            table = tables[self._get_row_cls().__tablename__]
            self._native_cache = record_filter_from_json(table, self._native_dump())

        return self._native_cache

    @override
    def matches(self, obj: RecordT) -> bool:  # type: ignore[override]
        from ceres.data import to_json

        return self._native_filter().matches(to_json(obj), utc())

    @classmethod
    @abstractmethod
    @override
    def _get_row_cls(cls) -> type[BaseRecordRow]: ...

    @override
    def apply[StatementT: Select[tuple[Any, ...]] | Update | Delete](
        self,
        statement: StatementT,
        dialect: DatabaseType,
        *,
        always_use_subquery: bool = False,
        ignore_where: bool = False,
        ignore_order: bool = False,
    ) -> StatementT:
        """Apply the natively compiled filter criteria to `statement`.

        The shape mirrors the base `apply`, `UPDATE` and `DELETE` statements that
        carry pagination or `RETURNING` filter through a primary-key subquery, but the
        `WHERE` and `ORDER BY` arrive as SQL the native compiler rendered.
        """
        native = self._native_filter()
        name = dialect.value

        # A colon in a rendered literal would read as a bind parameter marker inside
        # `text()`, so every colon escapes to stay literal.
        where_sql = None if ignore_where else native.where_sql(name, utc())
        where = () if where_sql is None else (text(where_sql.replace(":", "\\:")),)
        order_sql = None if ignore_order else native.order_sql(name)
        order_by = () if order_sql is None else (text(order_sql.replace(":", "\\:")),)
        limit = native.limit
        offset = native.offset

        if not always_use_subquery:
            if isinstance(statement, Select):
                return statement.where(*where).order_by(*order_by).limit(limit).offset(offset)

            if limit is None and offset is None and not statement._returning:
                return statement.where(*where)

        pk = self._get_row_cls().__table__.primary_key.columns
        pks = select(*pk).where(*where).order_by(*order_by).limit(limit).offset(offset)

        pk = pk[0] if len(pk) == 1 else tuple_(*pk)

        if isinstance(statement, Update | Delete):
            return statement.where(pk.in_(pks))

        return statement.where(pk.in_(pks)).order_by(*order_by)

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
