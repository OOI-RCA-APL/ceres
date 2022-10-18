from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

from .alert import Alert
from .component import Component, ComponentContext
from .config import UserConfig
from .path import LocalNotifierPath, NotifierPath
from .protocols import ReferencedConnectionHandle
from .reference import Reference


@dataclass(kw_only=True, frozen=True)
class NotifierContext(ComponentContext):
    path: NotifierPath


class Notifier(Component[NotifierContext], ABC):
    async def send(self, users: list[UserConfig], alerts: list[Alert]) -> None:
        raise NotImplementedError()


class NotifierReference(Reference[ReferencedConnectionHandle]):
    @property
    def path(self) -> LocalNotifierPath:
        return LocalNotifierPath(self.name)
