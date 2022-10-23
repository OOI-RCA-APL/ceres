from __future__ import annotations

import asyncio
from abc import ABC
from dataclasses import dataclass
from typing import Sequence

from .alert import Alert
from .component import Component, ComponentContext
from .config import NotifierConfig, UserConfig
from .path import LocalNotifierPath, NotifierPath
from .protocols import ReferencedNotifierHandle
from .reference import Reference


@dataclass(kw_only=True, frozen=True)
class NotifierContext(ComponentContext):
    path: NotifierPath


class Notifier(Component[NotifierContext], ABC):
    @property
    def config(self) -> NotifierConfig | None:
        return super().config  # type: ignore

    async def send(self, users: Sequence[UserConfig], alerts: Sequence[Alert]) -> None:
        raise NotImplementedError()

    async def update(self) -> None:
        await asyncio.sleep(1)


class NotifierReference(Reference[ReferencedNotifierHandle]):
    @property
    def path(self) -> LocalNotifierPath:
        return LocalNotifierPath(self.name)
