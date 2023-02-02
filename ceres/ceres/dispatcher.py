import traceback
from abc import abstractmethod
from typing import Sequence

from pydantic import Field

from .alert import Alert
from .component import Component
from .data import ImmutableDataObject
from .environment import AlertOrder, AlertQuery
from .loaded import Loaded
from .notifier import Notification, Notifier


class Dispatch(ImmutableDataObject):
    subject: str
    description: str | None = None
    signature: str | None = None
    alerts: AlertQuery
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
    class Parameters(Component.Parameters):
        dispatches: Sequence[Dispatch] = Field(default_factory=list)
        writer: Loaded[DispatchWriter]

    class References(Component.References):
        notifier: Notifier

    parameters: Parameters
    references: References

    async def dispatch(self, dispatch: Dispatch) -> None:
        query = dispatch.alerts.with_defaults(
            AlertQuery(
                order=AlertOrder.NEW_TO_OLD,
                limit=1000,
            )
        )

        try:
            alerts = await self.environment.get_alerts(query)
        except Exception:
            self.logger.error(
                f"An exception occurred while reading alerts for dispatch '{dispatch.subject}': {traceback.format_exc()}"
            )
            return

        if not alerts:
            self.logger.info(
                "An no alerts were found that match the current filter. No notification will be sent."
            )
            return

        try:
            notification = await self.parameters.writer.write(dispatch, alerts)
            self.logger.info(
                f"Sending notification '{notification.subject}' to {len(dispatch.recipients)} recipients referring to {len(alerts)} alerts..."
            )
        except Exception:
            self.logger.error(
                f"An exception occurred while writing notification for distribution '{dispatch.subject}': {traceback.format_exc()}"
            )
            return

        try:
            await self.references.notifier.notify(notification, dispatch.recipients)
        except Exception:
            self.logger.error(
                f"An exception occurred while sending notification to distribution '{dispatch.subject}': {traceback.format_exc()}"
            )
