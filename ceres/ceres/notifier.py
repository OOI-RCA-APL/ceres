from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from typing import Any

from .alert import Alert
from .component import Component, ComponentContext, ContextT
from .config import UserConfig
from .path import LocalNotifierPath, NotifierPath
from .protocols import ReferencedConnectionHandle, ReferencedNotifierHandle
from .reference import Reference, SelfT


@dataclass(kw_only=True, frozen=True)
class NotifierContext(ComponentContext):
    path: NotifierPath


class Notifier(Component[NotifierContext], ABC):
    async def send(self, users: list[UserConfig], alerts: list[Alert]) -> None:
        raise NotImplementedError()


class NotifierReference(Reference[ReferencedConnectionHandle]):
    @property
    def path(self) -> LocalNotifierPath:
        return LocalNotifierPath.create(self.name)

    def __get__(  # type: ignore
        self: SelfT,
        component: Component[ContextT] | None,
        owner: Any,
    ) -> SelfT | ReferencedNotifierHandle:
        if component is None:
            return self

        if not (real_name := component.context.references.notifiers.get(self.name)):
            raise ValueError(f"notifier '{self.name}' is not defined in notifier references")

        if notifier := component.context.unit.get_notifier(real_name):
            return notifier

        raise ValueError(f"no notifier '{real_name}' in current unit")
