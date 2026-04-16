from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Unpack, override

from pydantic import Field
from sqlalchemy import JSON, Index, SQLColumnExpression, Text, cast
from sqlalchemy.orm import Mapped, mapped_column

from ceres.__internal__.database.types import EnumConstraint, EnumMapper
from ceres.__internal__.entity import (
    BaseEntityManager,
    BaseEntityQuery,
    ConcreteEntity,
    EntityNaming,
    EntityOutputChannel,
    EntityQuery,
)
from ceres.__internal__.manager import BaseNodeManager
from ceres.__internal__.record import (
    BaseRecord,
    BaseRecordCreate,
    BaseRecordField,
    BaseRecordFilter,
    BaseRecordFilterArgs,
    BaseRecordOrder,
    BaseRecordRow,
    BaseRecordUpdate,
)
from ceres.data import FromYAML, JSONSerializableDict, MaybeSequence, to_json
from ceres.level import Level
from ceres.timing import utc

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.schema import SchemaItem

    from ceres.__internal__.protocols import DatabaseSource, NodeSource
    from ceres.database import DatabaseType

__all__ = [
    "Alert",
]


class AlertRow(BaseRecordRow, kw_only=True):
    """SQLAlchemy row type backing the `Alert` entity."""

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
            EnumConstraint(cls.level, Level, f"ck_{cls.__tablename__}__level"),
            # GIN trigram index supports substring search on the alert type on PostgreSQL.
            Index(
                f"ix_{cls.__tablename__}__type",
                cls.type,
                postgresql_ops={"type": "gin_trgm_ops"},
                postgresql_using="gin",
            ),
        )


type AlertField = (
    BaseRecordField
    | Literal[
        "level",
        "type",
        "data",
    ]
)
"""Field names selectable in `Alert` queries."""

type AlertOrder = (
    BaseRecordOrder
    | Literal[
        "level",
        "level:asc",
        "level:desc",
        "type",
        "type:asc",
        "type:desc",
    ]
)
"""Ordering keys accepted by `Alert` queries."""


class AlertFilterArgs(BaseRecordFilterArgs[AlertField, AlertOrder], total=False):
    """Keyword-argument form of `AlertFilter` for ergonomic call sites."""

    level: MaybeSequence[Level] | None
    min_level: Level | None
    max_level: Level | None
    type: MaybeSequence[str] | None
    type_contains: MaybeSequence[str] | None
    type_prefix: MaybeSequence[str] | None
    type_suffix: MaybeSequence[str] | None
    data_contains: MaybeSequence[str] | None
    data_prefix: MaybeSequence[str] | None
    data_suffix: MaybeSequence[str] | None


class AlertFilter(BaseRecordFilter["Alert", AlertField, AlertOrder]):
    """Filter for selecting `Alert` records by level, type, or data contents."""

    level: MaybeSequence[Level] | None = None
    """Filter by `level` being equal to one or more given levels."""
    min_level: Level | None = None
    """Filter by `level` being greater than or equal to the given level value."""
    max_level: Level | None = None
    """Filter by `level` being less than or equal to the given level value."""
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
    def _matches(self, obj: Alert, *, now: datetime | None = None) -> bool:
        now = utc(now)
        if not super()._matches(obj, now=now):
            return False

        if not self._match_value(obj.level, self.level):
            return False

        if self.min_level is not None:
            if obj.level < self.min_level:
                return False
        if self.max_level is not None:
            if obj.level > self.max_level:
                return False

        if not self._match_value(obj.type, self.type):
            return False
        if not self._match_string_contains(obj.type, self.type_contains):
            return False
        if not self._match_string_prefix(obj.type, self.type_prefix):
            return False
        if not self._match_string_suffix(obj.type, self.type_suffix):
            return False

        # Only serialize the data dict when at least one substring match is requested,
        # serialization is not free.
        if (
            self.data_contains is not None
            or self.data_prefix is not None
            or self.data_suffix is not None
        ):
            data_json = to_json(obj.data)
            if not self._match_string_contains(data_json, self.data_contains):
                return False
            if not self._match_string_prefix(data_json, self.data_prefix):
                return False
            if not self._match_string_suffix(data_json, self.data_suffix):
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
            yield self._sql_match_value(columns.level, self.level)
        if self.min_level is not None:
            # Expand the inequality into an `IN` clause over the enum values, this lets
            # databases without native enum ordering still benefit from the existing index.
            yield columns.level.in_(current for current in Level if current >= self.min_level)
        if self.max_level is not None:
            yield columns.level.in_(current for current in Level if current <= self.max_level)

        if self.type is not None:
            yield self._sql_match_string_equals(columns.type, self.type)
        if self.type_contains is not None:
            yield self._sql_match_string_contains(columns.type, self.type_contains)
        if self.type_prefix is not None:
            yield self._sql_match_string_prefix(columns.type, self.type_prefix)
        if self.type_suffix is not None:
            yield self._sql_match_string_suffix(columns.type, self.type_suffix)

        # `data` is JSON, cast it to text so substring matching applies against its
        # serialized form rather than failing at the SQL layer.
        if self.data_contains is not None:
            yield self._sql_match_string_contains(cast(columns.data, Text), self.data_contains)
        if self.data_prefix is not None:
            yield self._sql_match_string_prefix(cast(columns.data, Text), self.data_prefix)
        if self.data_suffix is not None:
            yield self._sql_match_string_suffix(cast(columns.data, Text), self.data_suffix)


class AlertCreate(BaseRecordCreate, slots=True):
    """Payload for creating a new `Alert` record."""

    level: Level
    """Severity level of the alert."""
    type: str
    """Discriminator string identifying the kind of alert."""
    data: FromYAML[JSONSerializableDict] = Field(default_factory=dict)
    """Optional structured payload providing additional context for the alert."""


class AlertUpdate(BaseRecordUpdate, total=False):
    """Partial update for an existing `Alert` record."""

    level: Level
    type: str
    data: FromYAML[JSONSerializableDict]


class _BaseAlertQuery(
    BaseEntityQuery[
        "Alert",
        AlertFilter,
        AlertUpdate,
        "AlertQuery",
    ]
):
    __slots__ = ()

    @override
    def _get_query_class(self) -> type[AlertQuery]:
        return AlertQuery

    @override
    def where(  # type: ignore
        self,
        filter: AlertFilter | None = None,
        **kwargs: Unpack[AlertFilterArgs],
    ) -> AlertQuery:
        return super().where(filter, **kwargs)


class AlertQuery(
    EntityQuery[
        "Alert",
        AlertFilter,
        AlertUpdate,
    ],
    _BaseAlertQuery,
):
    """Query builder for `Alert` records."""

    __slots__ = ()


class AlertManager(
    BaseEntityManager[
        "Alert",
        AlertRow,
        AlertCreate,
        AlertUpdate,
        AlertFilter,
        AlertFilterArgs,
    ],
    _BaseAlertQuery,
):
    """Database-bound manager for `Alert` records."""

    __slots__ = ()

    def __init__(self, source: DatabaseSource, /) -> None:
        super().__init__(source, Alert)

    async def get(self, id: UUID, /) -> Alert | None:
        """Fetch a single alert by its identifier.

        Args:
            id: UUID of the alert to fetch.

        Returns:
            The matching alert, or `None` if no alert with that id exists.
        """
        return await self.where(id=id).first()


class BoundAlertManager(AlertManager, BaseNodeManager):
    """Component-bound alert manager that exposes the live alert event stream and emit helpers.

    Use `emit()` (or the level-named shortcuts like `info()` and `error()`) to raise alerts
    from a component or engine. Each emitted alert is stored and broadcast as an `AlertEvent`.
    """

    __slots__ = ()

    def __init__(self, source: NodeSource, /) -> None:
        super().__init__(source)

    @property
    def stream(self) -> AlertOutputChannel:
        """Return an output channel that yields alerts from `AlertEvent` events."""
        from ceres.event import AlertEvent

        return AlertOutputChannel(
            self.__node__.events.stream.every(AlertEvent)
            .map(lambda event: event.alert)
            .where(lambda alert: self._get_resolved_filter().matches(alert))
        )

    def emit(
        self,
        level: Level,
        code: str,
        data: dict[str, Any] | None = None,
    ) -> Alert:
        """Raise a new alert from the bound component or engine.

        The alert is stored in the database and broadcast as an `AlertEvent` so listeners
        receive it immediately.

        Args:
            level: Severity level of the alert.
            code: Discriminator string identifying the kind of alert.
            data: Optional structured payload to attach to the alert.

        Returns:
            The newly created `Alert` instance.
        """
        from ceres.event import AlertEvent

        alert = Alert(
            address=self.__node__.address,
            level=level,
            type=code,
            data=data if data is not None else {},
        )

        self.__node__.store(alert)
        self.__node__.events.emit(AlertEvent, alert=alert)
        return alert

    def debug(self, type: str, data: dict[str, Any] | None = None) -> Alert:
        """Emit an alert at `Level.DEBUG`. See `emit()` for details."""
        return self.emit(Level.DEBUG, type, data)

    def info(self, type: str, data: dict[str, Any] | None = None) -> Alert:
        """Emit an alert at `Level.INFO`. See `emit()` for details."""
        return self.emit(Level.INFO, type, data)

    def warning(self, type: str, data: dict[str, Any] | None = None) -> Alert:
        """Emit an alert at `Level.WARNING`. See `emit()` for details."""
        return self.emit(Level.WARNING, type, data)

    def error(self, type: str, data: dict[str, Any] | None = None) -> Alert:
        """Emit an alert at `Level.ERROR`. See `emit()` for details."""
        return self.emit(Level.ERROR, type, data)

    def critical(self, type: str, data: dict[str, Any] | None = None) -> Alert:
        """Emit an alert at `Level.CRITICAL`. See `emit()` for details."""
        return self.emit(Level.CRITICAL, type, data)


class AlertOutputChannel(
    EntityOutputChannel[
        "Alert",
        AlertFilter,
        AlertFilterArgs,
    ]
):
    """Output channel for streaming `Alert` instances with filtering helpers."""

    __slots__ = ()

    @override
    def _get_filter_class(self) -> type[AlertFilter]:
        return AlertFilter

    @override
    def where(  # type: ignore
        self,
        filter: AlertFilter | Callable[[Alert], bool] | None = None,
        /,
        **kwargs: Unpack[AlertFilterArgs],
    ) -> AlertOutputChannel:
        return super().where(filter, **kwargs)


class Alert(
    BaseRecord,
    AlertCreate,
    ConcreteEntity[AlertRow],
    slots=True,
):
    """Severity-tagged event raised by a component or engine and persisted as a record.

    Alerts are how components and the engine surface notable conditions to operators, ranging
    from routine status updates to critical failures. Each alert carries a severity `level`,
    a discriminator `type`, and optional structured `data`.
    """

    Manager = AlertManager
    BoundManager = BoundAlertManager
    Create = AlertCreate
    Update = AlertUpdate
    Filter = AlertFilter
    FilterArgs = AlertFilterArgs
    Field = AlertField
    Order = AlertOrder
    Level = Level

    __entity_naming__: ClassVar[EntityNaming] = EntityNaming("alert")
