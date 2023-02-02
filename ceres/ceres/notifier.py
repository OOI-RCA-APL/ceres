from abc import abstractmethod
from typing import Sequence

from pydantic import Field

from .component import Component
from .data import DateTime, ImmutableDataObject
from .timing import utc


class Notification(ImmutableDataObject):
    timestamp: DateTime = Field(default_factory=utc)
    subject: str
    content: str
    content_type: str


class Notifier(Component):
    @abstractmethod
    async def notify(
        self,
        notification: Notification,
        recipients: Sequence[str],
    ) -> None:
        ...
