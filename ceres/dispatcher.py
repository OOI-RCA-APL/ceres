import traceback
from abc import abstractmethod
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import field
from typing import TYPE_CHECKING, Any, final, override

from ceres.__internal__.templates import templates
from ceres.__internal__.utilities.collections import group_by
from ceres.address import Address
from ceres.alert import Alert, AlertFilter, Level
from ceres.component import Component, action, routine
from ceres.config import JobConfig
from ceres.data import DataObject, NonBlankStr, to_json
from ceres.loaded import Loaded
from ceres.notifier import Notification, Notifier
from ceres.reference import Ref
from ceres.schedule import ScheduleExpr

if TYPE_CHECKING:
    from datetime import datetime

__all__ = [
    "Dispatch",
    "DispatchWriter",
    "Dispatcher",
    "HTMLDispatchWriter",
]


class Dispatch(DataObject):
    """Configuration for a single notification dispatch driven by alert activity.

    A dispatch describes which alerts to summarize, who to notify, and optionally
    when to send the notification. The owning `Dispatcher` component runs each
    dispatch on its schedule, gathers matching alerts, renders a notification, and
    delivers it through the configured `Notifier`.
    """

    subject: NonBlankStr
    """Subject line used as both the notification title and the dispatch identifier."""

    description: NonBlankStr | None = None
    """Optional human-readable description rendered in the notification body."""

    signature: NonBlankStr | None = None
    """Optional signature appended to the notification body."""

    alerts: AlertFilter
    """Filter selecting which alerts contribute to this dispatch."""

    recipients: list[str]
    """Recipient identifiers passed through to the configured `Notifier`."""

    schedule: ScheduleExpr | None = None
    """Schedule controlling automatic dispatching, omit to dispatch only on demand."""


class DispatchWriter:
    """Render a `Dispatch` and a list of matching alerts into a `Notification`.

    Implementations format alerts into the notification body and content type best
    suited to the delivery channel (for example HTML email or plaintext SMS).
    """

    @abstractmethod
    async def write(
        self,
        dispatch: Dispatch,
        alerts: Sequence[Alert],
    ) -> Notification:
        """Render `alerts` for `dispatch` into a `Notification`.

        Args:
            dispatch: The dispatch configuration being rendered.
            alerts: Alerts that matched the dispatch's filter, in arbitrary order.

        Returns:
            A `Notification` ready to hand to a `Notifier` for delivery.
        """
        ...


# Three-level grouping used by `HTMLDispatchWriter`, alerts grouped by severity, then by
# `(address, type, data)` so identical alerts collapse into a single row.
_Index = dict[Level, dict[tuple[Address, str, str], list[Alert]]]


class Dispatcher(Component):
    """Component that summarizes alerts and delivers notifications on a schedule.

    The dispatcher owns a list of `Dispatch` configurations, registers a job for each
    one with a schedule, and renders matching alerts via a `DispatchWriter` before
    handing the result to a `Notifier`. Dispatches without a schedule can still be
    triggered on demand by calling the `dispatch` action directly.
    """

    notifier: Ref[Notifier]
    """Reference to the `Notifier` component that delivers rendered notifications."""

    writer: Loaded[DispatchWriter]
    """Writer responsible for rendering a `Dispatch` and its alerts into a `Notification`."""

    dispatches: Sequence[Dispatch] = field(default_factory=list)
    """Dispatches managed by this component."""

    @action
    async def dispatch(self, dispatch: Dispatch) -> None:
        """Run a dispatch end-to-end, gather alerts, render, then notify.

        Args:
            dispatch: The dispatch to execute.
        """
        # Apply sensible defaults on top of the configured filter, an unbounded query is
        # capped at the most recent 1000 alerts across the whole engine.
        query = dispatch.alerts.with_defaults(
            AlertFilter(
                address=Address.ENGINE.all(),
                order="timestamp:desc",
                limit=1000,
            )
        )

        try:
            alerts = await self.system.alerts.where(query)
        except Exception:
            self.system.log.error(
                f"An exception occurred while reading alerts for dispatch '{dispatch.subject}': "
                f"{traceback.format_exc()}"
            )
            return

        if not alerts:
            self.system.log.info(
                "No alerts were found that match the current filter. No notification will be sent."
            )
            return

        try:
            notification = await self.writer.write(dispatch, alerts)
            self.system.log.info(
                f"Sending notification '{notification.subject}' to {len(dispatch.recipients)} "
                f"recipients referring to {len(alerts)} alerts..."
            )
        except Exception:
            self.system.log.error(
                f"An exception occurred while writing notification for dispatch "
                f"'{dispatch.subject}': {traceback.format_exc()}"
            )
            return

        try:
            await self.notifier.notify(notification, dispatch.recipients)
        except Exception:
            self.system.log.error(
                f"An exception occurred while sending notification to dispatch "
                f"'{dispatch.subject}': {traceback.format_exc()}"
            )

    @routine
    async def routine__schedule_dispatches(self) -> None:
        """Register a scheduled job for each dispatch that defines a schedule."""
        for dispatch in self.dispatches:
            if dispatch.schedule is None:
                continue

            # Job names must be filesystem and URL friendly, lowercase the subject and
            # replace spaces with hyphens to derive a stable identifier.
            self.system.jobs.add(
                JobConfig(
                    name=f"dispatch-{dispatch.subject.lower().replace(' ', '-')}",
                    schedule=dispatch.schedule,
                    action=self.dispatch.__name__,
                    arguments={"dispatch": dispatch},
                )
            )


@final
class HTMLDispatchWriter(DispatchWriter):
    """`DispatchWriter` that renders alerts as an HTML email via a Jinja template.

    Alerts are grouped first by severity level (highest first), then by the combination
    of source address, alert type, and serialized data, this collapses repeated alerts
    into a single row while preserving full timestamp history for each group.
    """

    @override
    async def write(
        self,
        dispatch: Dispatch,
        alerts: Sequence[Alert],
    ) -> Notification:
        def get_size(index: dict[str, Any] | list[Any]) -> int:
            # Recursively count leaf entries in the nested grouping so the template can
            # show totals without duplicating the iteration logic in Jinja.
            if isinstance(index, dict):
                values = index.values()
            elif isinstance(index, list):
                values = index
            else:
                return 1

            count = 0

            for value in values:
                if isinstance(value, dict | list):
                    count += get_size(value)
                else:
                    count += 1

            return count

        def get_latest_alert_timestamp(alerts: Iterable[Alert]) -> datetime:
            return max([alert.timestamp for alert in alerts])

        def create_index() -> _Index:
            return defaultdict(create_index)  # type: ignore

        index = create_index()

        # Sort by level descending so the most severe alerts appear first in the rendered
        # output, then sort each group by timestamp descending for the same reason.
        for level, by_level in group_by(
            sorted(alerts, key=lambda alert: alert.level, reverse=True),
            key=lambda alert: alert.level,
        ):
            for key, by_key in group_by(
                sorted(by_level, key=lambda alert: -alert.timestamp.timestamp()),
                lambda alert: (alert.address, alert.type, to_json(alert.data)),
            ):
                group = index[level]
                if key not in group:
                    group[key] = []

                group[key].extend(by_key)
                group[key].sort(key=lambda alert: -alert.timestamp.timestamp())

        template = templates.get_template("html-email-dispatch.jinja")

        from mistune import create_markdown

        markdown = create_markdown()
        content = template.render(
            dispatch=dispatch,
            index=index,
            markdown=markdown,
            get_size=get_size,
            get_latest_alert_timestamp=get_latest_alert_timestamp,
        )

        return Notification(
            subject=dispatch.subject,
            content=content,
            content_type="text/html",
        )
