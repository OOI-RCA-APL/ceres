import asyncio
from abc import ABC
from dataclasses import dataclass, field
from typing import Sequence

from .alert import Alert
from .component import Component, ComponentContext, ComponentParameters
from .config import UserConfig
from .internal.utilities import frozenlist
from .path import LocalNotifierPath, NotifierPath
from .protocols import ReferencedNotifierHandle
from .reference import Reference


@dataclass(kw_only=True, frozen=True)
class NotifierParameters(ComponentParameters):
    pass


@dataclass(kw_only=True, frozen=True)
class NotifierContext(ComponentContext):
    path: NotifierPath
    users: frozenlist[UserConfig] = field(default_factory=frozenlist)


class Notifier(Component[NotifierParameters, NotifierContext], ABC):
    async def send(self, users: Sequence[UserConfig], alerts: Sequence[Alert]) -> None:
        raise NotImplementedError()

    async def update(self) -> None:
        await asyncio.sleep(1)


class NotifierReference(Reference[ReferencedNotifierHandle]):
    @property
    def path(self) -> LocalNotifierPath:
        return LocalNotifierPath(self.name)
