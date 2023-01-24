from abc import abstractmethod
from datetime import datetime
from typing import Sequence

from pydantic import Field

from .component import Component
from .data import ImmutableDataObject
from .datetime import utc


class Notification(ImmutableDataObject):
    timestamp: datetime = Field(default_factory=utc)
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
