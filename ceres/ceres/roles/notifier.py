from abc import abstractmethod
from typing import Iterable

from ceres.component import Component
from ceres.data import ImmutableDataObject, NonBlankStr
from ceres.procedure import action


class Notification(ImmutableDataObject):
    subject: NonBlankStr
    content: str | None = None
    content_type: NonBlankStr = "text/plain"


class Notifier(Component):
    @action
    @abstractmethod
    async def notify(
        self,
        notification: Notification,
        recipients: Iterable[NonBlankStr],
    ) -> None:
        ...
