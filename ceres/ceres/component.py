from __future__ import annotations

import inspect
import traceback
from abc import ABC
from dataclasses import dataclass
from logging import Logger
from typing import Any, Generic, Sequence, TypeVar, cast
from uuid import UUID

from .alert import Alert, AlertLevel, RawAlertLevel
from .config import ComponentConfig, Config
from .events import Event, EventBinding, get_event_bindings
from .exceptions import ComponentNotSetupException
from .internal import logs
from .internal.utilities import awaitify, get_now
from .path import ComponentPath
from .protocols import GlobalUnitProtocol
from .reference import ReferenceBinding, get_reference_bindings


@dataclass(kw_only=True, frozen=True)
class ComponentContext:
    id: UUID
    path: ComponentPath
    config: Config
    unit: GlobalUnitProtocol

    def __post_init__(self) -> None:
        if not self.config.get_component(self.path):
            raise ValueError(f"Component {self.path} is not defined in configuration.")


ComponentContextT = TypeVar("ComponentContextT", bound=ComponentContext)


class Component(Generic[ComponentContextT], ABC):
    def __init__(self) -> None:
        self.__context__: ComponentContextT | None = None

    def setup(self, context: ComponentContextT) -> None:
        self.__context__ = context

    @property
    def context(self) -> ComponentContextT:
        if not self.__context__:
            raise ComponentNotSetupException(
                "Attempted to access component context before setup() is called."
            )

        return self.__context__

    @property
    def config(self) -> ComponentConfig | None:
        if self.__context__:
            return self.__context__.config.get_component(self.context.path)

        return None

    @property
    def logger(self) -> Logger:
        return logs.get(str(self.context.path))

    @classmethod
    def get_event_bindings(cls) -> Sequence[EventBinding]:
        return get_event_bindings(cls)

    @classmethod
    def get_reference_bindings(cls) -> Sequence[ReferenceBinding]:
        return get_reference_bindings(cls)

    async def handle(self, event: Event) -> None:
        if not self.config:
            return

        for binding in self.get_event_bindings():
            if not isinstance(event, cast(type, binding.cls)):
                continue
            if self.config.references.remap(binding.path) != event.path:
                continue

            if method := getattr(self, binding.method, None):
                try:
                    if len(inspect.signature(method).parameters) == 0:
                        await awaitify(method())
                    else:
                        await awaitify(method(event))
                except Exception:
                    traceback.print_exc()

    async def alert(
        self,
        level: AlertLevel | RawAlertLevel,
        kind: str,
        info: dict[str, Any] | None = None,
    ) -> Alert:
        alert = Alert(
            origin_id=self.context.id,
            timestamp=get_now(),
            level=AlertLevel.create_from(level),
            kind=kind,
            info=info or {},
        )

        await self.context.unit.alert(alert)
        return alert
