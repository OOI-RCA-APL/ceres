import inspect
import traceback
from abc import ABC
from dataclasses import dataclass, field
from logging import Logger
from typing import Any, Generic, Sequence, TypeVar, cast
from uuid import UUID, uuid4

from .alert import Alert, AlertLevel, RawAlertLevel
from .config import ComponentReferencesConfig
from .events import Event, EventBinding, get_event_bindings
from .internal import logs
from .internal.utilities import awaitify, get_now
from .path import ComponentPath
from .reference import ReferenceBinding, get_reference_bindings


@dataclass(kw_only=True, frozen=True)
class ComponentParameters:
    pass


ComponentParametersT = TypeVar("ComponentParametersT", bound=ComponentParameters)


@dataclass(kw_only=True, frozen=True)
class ComponentContext:
    id: UUID = field(default_factory=uuid4)
    path: ComponentPath
    references: ComponentReferencesConfig = field(default_factory=ComponentReferencesConfig)


ComponentContextT = TypeVar("ComponentContextT", bound=ComponentContext)


class Component(Generic[ComponentParametersT, ComponentContextT], ABC):
    def __init__(
        self,
        parameters: ComponentParametersT,
        context: ComponentContextT,
    ) -> None:
        self.__component_parameters__ = parameters
        self.__component_context__ = context

    @property
    def parameters(self) -> ComponentParametersT:
        return self.__component_parameters__

    @property
    def context(self) -> ComponentContextT:
        return self.__component_context__

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

        # await self.context.unit.alert(alert)
        return alert


ComponentInterface = Component[ComponentParameters, ComponentContext]


class WithParameters(Generic[ComponentParametersT]):
    @property
    def parameters(self) -> ComponentParametersT:
        return self.__component_parameters__  # type: ignore


class WithContext(Generic[ComponentContextT]):
    @property
    def context(self) -> ComponentContextT:
        return self.__component_context__  # type: ignore
