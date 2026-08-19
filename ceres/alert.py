from collections.abc import Callable
from typing import TYPE_CHECKING, Any, ClassVar, Unpack, override

from ceres.__internal__.entity import (
    BaseEntityManager,
    BaseEntityQuery,
    ConcreteEntity,
    EntityNaming,
    EntityOutputChannel,
    EntityQuery,
)
from ceres.__internal__.manager import BaseNodeManager
from ceres.__internal__.models.alerts import (
    AlertCreate,
    AlertField,
    AlertFilter,
    AlertFilterArgs,
    AlertOrder,
    AlertUpdate,
)
from ceres.__internal__.record import BaseRecord
from ceres.level import Level

if TYPE_CHECKING:
    from uuid import UUID

    from ceres.__internal__.protocols import DatabaseSource, NodeSource

__all__ = [
    "Alert",
]


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

    Use `emit()` (or the level-named shortcuts like `info()` and `error()`) to raise alerts from a
    component or engine. Each emitted alert is stored and broadcast as an `AlertEvent`.
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

        The alert is stored in the database and broadcast as an `AlertEvent` so listeners receive
        it immediately.

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
        """Return a new channel that only yields alerts matching the given filter.

        Args:
            filter: An `AlertFilter`, a callable predicate, or `None` to filter by keyword
                arguments only.
            **kwargs: Additional filter fields forwarded to `AlertFilter`.

        Returns:
            A filtered `AlertOutputChannel`.
        """
        return super().where(filter, **kwargs)


class Alert(
    BaseRecord,
    AlertCreate,
    ConcreteEntity,
    slots=True,
):
    """Severity-tagged event raised by a component or engine and persisted as a record.

    Alerts are how components and the engine surface notable conditions to operators, ranging from
    routine status updates to critical failures. Each alert carries a severity `level`, a
    discriminator `type`, and optional structured `data`.
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
