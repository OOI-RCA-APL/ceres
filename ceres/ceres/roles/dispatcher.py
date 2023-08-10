import traceback
from abc import abstractmethod
from dataclasses import field
from typing import Sequence

from ceres.alert import Alert
from ceres.component import Component, action
from ceres.data import ImmutableDataObject, NonBlankStr
from ceres.filter import AlertFilter, AlertOrder
from ceres.loaded import Loaded
from ceres.reference import Ref
from ceres.roles.notifier import Notification, Notifier


class Dispatch(ImmutableDataObject):
    subject: NonBlankStr
    description: NonBlankStr | None = None
    signature: NonBlankStr | None = None
    alerts: AlertFilter
    recipients: Sequence[str]


class DispatchWriter:
    @abstractmethod
    async def write(
        self,
        dispatch: Dispatch,
        alerts: Sequence[Alert],
    ) -> Notification:
        ...


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
            alerts = await self.root.get_alerts(query)
        except Exception:
            self.log.error(
                f"An exception occurred while reading alerts for dispatch '{dispatch.subject}': "
                f"{traceback.format_exc()}"
            )
            return

        if not alerts:
            self.log.info(
                "No alerts were found that match the current filter. No notification will be "
                "sent."
            )
            return

        try:
            notification = await self.writer.write(dispatch, alerts)
            self.log.info(
                f"Sending notification '{notification.subject}' to {len(dispatch.recipients)} "
                f"recipients referring to {len(alerts)} alerts..."
            )
        except Exception:
            self.log.error(
                f"An exception occurred while writing notification for dispatch "
                f"'{dispatch.subject}': {traceback.format_exc()}"
            )
            return

        try:
            await self.notifier.notify(notification, dispatch.recipients)
        except Exception:
            self.log.error(
                f"An exception occurred while sending notification to dispatch "
                f"'{dispatch.subject}': {traceback.format_exc()}"
            )
