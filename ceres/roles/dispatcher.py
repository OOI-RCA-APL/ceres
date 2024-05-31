from __future__ import annotations

import traceback
from abc import abstractmethod
from collections import defaultdict
from dataclasses import field
from datetime import datetime
from typing import Any, Iterable, Sequence, final

from pydantic import Field
from typing_extensions import override

from ceres._internal.templates import templates
from ceres._internal.utilities import group_by
from ceres.address import Address
from ceres.alert import Alert, AlertFilter, AlertOrder, Level
from ceres.component import Component, action, routine
from ceres.data import ImmutableDataObject, NonBlankStr, jsonify
from ceres.loaded import Loaded
from ceres.reference import Ref
from ceres.roles.notifier import Notification, Notifier
from ceres.schedule import Schedule


class Dispatch(ImmutableDataObject):
    subject: NonBlankStr
    description: NonBlankStr | None = None
    signature: NonBlankStr | None = None
    alerts: AlertFilter
    recipients: Sequence[str]
    schedule: Schedule | None = Field(None, discriminator="type")


class DispatchWriter:
    @abstractmethod
    async def write(
        self,
        dispatch: Dispatch,
        alerts: Sequence[Alert],
    ) -> Notification: ...


_Index = dict[Level, dict[tuple[Address, str, str], list[Alert]]]


class Dispatcher(Component):
    notifier: Ref[Notifier]
    writer: Loaded[DispatchWriter]
    dispatches: Sequence[Dispatch] = field(default_factory=list)

    @action
    async def dispatch(self, dispatch: Dispatch) -> None:
        query = dispatch.alerts.with_defaults(
            AlertFilter(
                order=AlertOrder.NEW_TO_OLD,
                limit=1000,
            )
        )

        try:
            alerts = await self.system.alerts.get_all(query)
        except Exception:
            self.system.log.error(
                f"An exception occurred while reading alerts for dispatch '{dispatch.subject}': "
                f"{traceback.format_exc()}"
            )
            return

        if not alerts:
            self.system.log.info(
                "No alerts were found that match the current filter. No notification will be "
                "sent."
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
        for dispatch in self.dispatches:
            if dispatch.schedule is None:
                continue

            self.system.add_job(
                f"dispatch-{dispatch.subject.lower().replace(' ', '-')}",
                dispatch.schedule,
                self.dispatch,
                arguments={"dispatch": dispatch},
            )


@final
class HTMLDispatchWriter(DispatchWriter):
    @override
    async def write(
        self,
        dispatch: Dispatch,
        alerts: Sequence[Alert],
    ) -> Notification:
        def get_size(index: dict[str, Any] | list[Any]) -> int:
            if isinstance(index, dict):
                values = index.values()
            elif isinstance(index, list):
                values = index
            else:
                return 1

            count = 0

            for value in values:
                if isinstance(value, (dict, list)):
                    count += get_size(value)
                else:
                    count += 1

            return count

        def get_latest_alert_timestamp(alerts: Iterable[Alert]) -> datetime:
            return max([alert.timestamp for alert in alerts])

        def create_index() -> _Index:
            return defaultdict(create_index)  # type: ignore

        index = create_index()

        for level, by_level in group_by(
            sorted(alerts, key=lambda alert: alert.level, reverse=True),
            key=lambda alert: alert.level,
        ):
            for key, by_key in group_by(
                sorted(by_level, key=lambda alert: -alert.timestamp.timestamp()),
                lambda alert: (alert.address, alert.code, jsonify(alert.info)),
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
