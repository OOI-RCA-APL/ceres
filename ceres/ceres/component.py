import dataclasses
import inspect
import traceback
from abc import ABC
from dataclasses import dataclass, field
from logging import Logger
from typing import Any, Generic, Sequence, TypeVar, cast, get_type_hints
from uuid import UUID, uuid4
from asyncio import Queue as AsyncQueue

from .alert import Alert, AlertLevel, RawAlertLevel
from .config import (
    ComponentConfig,
    ComponentReferencesConfig,
    Config,
    UnitConfig,
    UserConfig,
)
from .events import Event, EventBinding, get_event_bindings
from .internal import logs
from .internal.utilities import awaitify, frozenlist, get_now, object_has_field
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

    def __post_init__(self) -> None:
        extra: list[tuple[str, Any]] = []
        for current in dataclasses.fields(self):
            if current.name in ["path"]:
                if not object_has_field(FullComponentContext, current.name):
                    extra.append((current.name, current.type))
            else:
                if not object_has_field(FullComponentContext, current.name, current.type):
                    extra.append((current.name, current.type))

        if extra:
            raise ValueError(f"invalid context class, cannot provide fields: {extra}")


@dataclass(kw_only=True, frozen=True)
class FullComponentContext(ComponentContext):
    id: UUID
    root_config: Config
    unit_config: UnitConfig
    component_config: ComponentConfig
    users: frozenlist[UserConfig]
    units: frozenlist[UnitConfig]


ComponentContextT = TypeVar("ComponentContextT", bound=ComponentContext)


@dataclass(kw_only=True)
class ComponentInteral:
    event_queue: AsyncQueue[Event] = AsyncQueue()
    alert_queue: AsyncQueue[Alert] = AsyncQueue()


class Component(Generic[ComponentParametersT, ComponentContextT], ABC):
    def __init__(
        self,
        parameters: ComponentParametersT,
        context: ComponentContextT,
    ) -> None:
        self.__component_parameters__ = parameters
        self.__component_context__ = context
        self.__component_internal__ = ComponentInteral()

    @classmethod
    def get_parameters_type(cls) -> type[ComponentParameters]:
        return tuple(get_type_hints(cls.__init__).values())[0]  # type: ignore

    @classmethod
    def get_context_type(cls) -> type[ComponentContext]:
        return tuple(get_type_hints(cls.__init__).values())[1]  # type: ignore

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
