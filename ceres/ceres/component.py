from __future__ import annotations

import inspect
import traceback
from abc import ABC
from dataclasses import dataclass
from logging import Logger
from typing import Generic, Sequence, TypeVar, cast
from uuid import UUID

from .config import ComponentReferencesConfig
from .events import Event, EventBinding, get_event_bindings
from .exceptions import ComponentNotSetupException
from .internal import logs
from .internal.utilities import awaitify
from .path import ComponentPath
from .protocols import GlobalUnitProtocol
from .reference import ReferenceBinding, get_reference_bindings


@dataclass(kw_only=True, frozen=True)
class ComponentContext:
    id: UUID
    path: ComponentPath
    unit: GlobalUnitProtocol
    references: ComponentReferencesConfig


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
    def logger(self) -> Logger:
        return logs.get(str(self.context.path))

    @classmethod
    def get_event_bindings(cls) -> Sequence[EventBinding]:
        return get_event_bindings(cls)

    @classmethod
    def get_reference_bindings(cls) -> Sequence[ReferenceBinding]:
        return get_reference_bindings(cls)

    async def handle(self, event: Event) -> None:
        for binding in self.get_event_bindings():
            if not isinstance(event, cast(type, binding.cls)):
                continue
            if self.context.references.remap(binding.path) != event.path:
                continue

            if method := getattr(self, binding.method, None):
                try:
                    if len(inspect.signature(method).parameters) == 0:
                        await awaitify(method())
                    else:
                        await awaitify(method(event))
                except Exception:
                    traceback.print_exc()
