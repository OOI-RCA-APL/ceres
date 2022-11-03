import dataclasses
import inspect
import traceback
from abc import ABC
from dataclasses import dataclass, field
from inspect import Parameter
from logging import Logger
from typing import Any, Sequence, TypeVar, cast, get_type_hints
from uuid import UUID, uuid4

from pydantic.dataclasses import dataclass as validated_dataclass

from .address import ComponentAddress
from .alert import Alert, AlertLevel, RawAlertLevel
from .config import ComponentConfig, Config, UnitConfig, UserConfig
from .events import Event, EventBinding, get_event_bindings
from .exceptions import ComponentClassInvalidException
from .internal import logs
from .internal.database.manager import DatabaseManager
from .internal.tasks import Tasklet
from .internal.utilities import (
    awaitify,
    frozendict,
    frozenlist,
    get_now,
    get_type_annotations,
    object_has_field,
)
from .scheduler import Scheduler
from .stream import Stream, StreamView


@validated_dataclass(kw_only=True, frozen=True)
class ComponentParameters:
    pass


ComponentParametersT = TypeVar("ComponentParametersT", bound=ComponentParameters)


@validated_dataclass(kw_only=True, frozen=True)
class ComponentContext:
    id: UUID = field(default_factory=uuid4)
    address: ComponentAddress
    references: frozendict[str, str] = field(default_factory=frozendict)
    database: DatabaseManager

    def __post_init__(self) -> None:
        extra: list[tuple[str, Any]] = []
        for current in dataclasses.fields(self):
            if current.name in ["address"]:
                if not object_has_field(CompleteComponentContext, current.name):
                    extra.append((current.name, current.type))
            else:
                if not object_has_field(CompleteComponentContext, current.name, current.type):
                    extra.append((current.name, current.type))

        if extra:
            raise ValueError(f"invalid context class, cannot provide fields: {extra}")


@validated_dataclass(kw_only=True, frozen=True)
class CompleteComponentContext(ComponentContext):
    id: UUID
    root_config: Config
    unit_config: UnitConfig
    component_config: ComponentConfig
    users: frozenlist[UserConfig]
    units: frozenlist[UnitConfig]
    database: DatabaseManager


ComponentContextT = TypeVar("ComponentContextT", bound=ComponentContext)


@validated_dataclass(kw_only=True, frozen=True)
class ComponentReferences:
    pass


ComponentReferencesT = TypeVar("ComponentReferencesT", bound=ComponentReferences)


@dataclass(kw_only=True)
class ComponentInteral:
    event_stream: Stream[Event] = field(default_factory=Stream)
    alert_stream: Stream[Alert] = field(default_factory=Stream)
    scheduler: Scheduler = field(default_factory=Scheduler)


ComponentT = TypeVar("ComponentT", bound="Component")


@validated_dataclass
class Component(Tasklet, ABC):
    parameters: ComponentParameters
    context: ComponentContext
    references: ComponentReferences

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        _validate_component_cls(cls)

    def __post_init__(self) -> None:
        self.__component_internal__ = ComponentInteral()

    @classmethod
    def get_parameters_type(cls) -> type[ComponentParameters]:
        return get_type_annotations(cls)["parameters"]  # type: ignore

    @classmethod
    def get_context_type(cls) -> type[ComponentContext]:
        return get_type_annotations(cls)["context"]  # type: ignore

    @classmethod
    def get_references_type(cls) -> type[ComponentReferences]:
        return get_type_annotations(cls)["references"]  # type: ignore

    @classmethod
    def get_event_bindings(cls) -> Sequence[EventBinding]:
        return get_event_bindings(cls)

    @property
    def id(self) -> UUID:
        return self.context.id

    @property
    def address(self) -> ComponentAddress:
        return self.context.address

    @property
    def scheduler(self) -> Scheduler:
        return self.__component_internal__.scheduler

    @property
    def logger(self) -> Logger:
        return logs.get(str(self.context.address))

    @property
    def event_stream(self) -> StreamView[Event]:
        return self.__component_internal__.event_stream.view()

    @property
    def alert_stream(self) -> StreamView[Alert]:
        return self.__component_internal__.alert_stream.view()

    def emit_event(self, event: Event) -> Event:
        self.__component_internal__.event_stream.put(event)
        return event

    def emit_alert(
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

        self.__component_internal__.alert_stream.put(alert)
        return alert

    async def handle_event(self, event: Event) -> None:
        for binding in self.get_event_bindings():
            if not isinstance(event, cast(type, binding.cls)):
                continue
            if self.context.references.get(binding.address.name) != event.address.name:
                continue

            if method := getattr(self, binding.function.__name__, None):
                try:
                    if len(inspect.signature(method).parameters) == 0:
                        await awaitify(method())
                    else:
                        await awaitify(method(event))
                except Exception:
                    traceback.print_exc()

    async def _tasklet_run(self) -> None:
        self.scheduler.start()

    async def _tasklet_stop(self) -> None:
        self.scheduler.stop()


def _validate_component_cls(cls: type[Component]) -> None:
    __init__ = dataclass(cls).__init__
    hints = tuple(get_type_hints(__init__).values())
    signature = inspect.signature(__init__)
    parameters: tuple[Parameter, ...] = tuple(signature.parameters.values())

    def is_subclass_or_typevar(subcls: type, cls: type) -> bool:
        if isinstance(subcls, TypeVar):
            return True

        return isinstance(cls, type) and isinstance(subcls, type) and issubclass(subcls, cls)

    if (
        len(parameters) != 4
        or any(parameter.kind == Parameter.KEYWORD_ONLY for parameter in parameters)
        or not is_subclass_or_typevar(hints[0], ComponentParameters)
        or not is_subclass_or_typevar(hints[1], ComponentContext)
        or not is_subclass_or_typevar(hints[2], ComponentReferences)
    ):
        raise ComponentClassInvalidException(
            f"signature of {__init__} must match {inspect.signature(Component.__init__)}, got {signature}"
        )

    references_type = hints[3]

    if isinstance(references_type, type) and issubclass(references_type, ComponentReferences):
        for binding in get_event_bindings(cls):
            if not object_has_field(references_type, binding.address.name):
                raise ComponentClassInvalidException(
                    f"event listener {binding.function} refers to component '{binding.address.name}' which is not defined in {references_type}"
                )
