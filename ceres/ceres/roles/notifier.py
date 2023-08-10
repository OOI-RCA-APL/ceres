from abc import abstractmethod
from typing import Iterable

from ceres.component import Component, action
from ceres.data import ImmutableDataObject, NonBlankStr


class Notification(ImmutableDataObject):
    subject: NonBlankStr
    content: str | None = None
    content_type: NonBlankStr = "text/plain"


class Notifier(Component):
    @abstractmethod
    @action
    async def notify(
        self,
        notification: Notification,
        recipients: Iterable[NonBlankStr],
    ) -> None:
        ...
