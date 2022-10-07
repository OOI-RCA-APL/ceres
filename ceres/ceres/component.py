from __future__ import annotations

import inspect
import traceback
from abc import ABC
from functools import cached_property
from logging import Logger
from typing import Generic, Literal, Sequence, TypeVar, cast
from uuid import UUID

from pydantic import BaseModel

from .config import ComponentReferencesConfig
from .events import Event, EventBinding, get_event_bindings
from .exceptions import ComponentNotSetupException
from .internal import logs
from .internal.utilities import awaitify
from .path import ComponentPath
from .protocols import GlobalUnitProtocol


class ComponentContext(BaseModel, ABC):
    class Config:
        arbitrary_types_allowed = True

    id: UUID
    path: ComponentPath
    unit: GlobalUnitProtocol
    references: ComponentReferencesConfig


ContextT = TypeVar("ContextT", bound=ComponentContext)


ComponentKind = Literal["connection", "driver"]


class Component(Generic[ContextT], ABC):
    def __init__(self) -> None:
        self.__context__: ContextT | None = None

    def setup(self, context: ContextT) -> None:
        self.__context__ = context

    @property
    def context(self) -> ContextT:
        if not self.__context__:
            raise ComponentNotSetupException(
                "Attempted to access component context before setup() is called."
            )

        return self.__context__

    @property
    def logger(self) -> Logger:
        return logs.get(str(self.context.path))

    @cached_property
    def bindings(self) -> Sequence[EventBinding]:
        return tuple(get_event_bindings(self))

    async def handle(self, event: Event) -> None:
        for binding in self.bindings:
            if not isinstance(event, cast(type, binding.cls)):
                continue

            if event.path.kind == binding.path.kind:
                if binding.path.kind == "connection":
                    references = self.context.references.connections
                elif binding.path.kind == "driver":
                    references = self.context.references.drivers
                else:
                    continue

                if references.get(binding.path.name) != event.path.name:
                    continue

                if method := getattr(self, binding.method, None):
                    try:
                        if len(inspect.signature(method).parameters) == 0:
                            await awaitify(method())
                        else:
                            await awaitify(method(event))
                    except Exception:
                        traceback.print_exc()
