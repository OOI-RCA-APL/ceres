import dataclasses
import inspect
import traceback
from abc import ABCMeta
from dataclasses import dataclass, field
from inspect import Parameter
from logging import Logger
from typing import Any, Generic, Sequence, TypeVar, cast, get_type_hints
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
    ValidateByType,
    awaitify,
    frozendict,
    frozenlist,
    get_now,
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


class ComponentMeta(ABCMeta):
    def __new__(
        metacls,
        name: str,
        bases: tuple[type, ...],
        namespace: Any,
        **kwargs: dict[str, Any],
    ) -> Any:
        cls = super().__new__(metacls, name, bases, namespace, **kwargs)
        __init__ = cls.__init__  # type: ignore
        signature = inspect.signature(__init__)
        parameters: tuple[Parameter, ...] = tuple(signature.parameters.values())

        if len(parameters) != 4 or any(
            parameter.kind == Parameter.KEYWORD_ONLY for parameter in parameters
        ):
            required = "def __init__(parameters: ComponentParametersT, context: ComponentContextT, references: ComponentReferencesT) -> None"
            raise ComponentClassInvalidException(f"{__init__} must match match {required}")

        hints = tuple(get_type_hints(__init__).values())
        parameters_type = hints[0]
        context_type = hints[1]
        references_type = hints[2]

        if not isinstance(parameters_type, TypeVar) and (
            not isinstance(parameters_type, type)
            or not issubclass(parameters_type, ComponentParameters)
        ):
            raise ComponentClassInvalidException(
                f"first positional parameter of {__init__} must be a subclass of {ComponentParameters}"
            )

        if not isinstance(context_type, TypeVar) and (
            not isinstance(context_type, type) or not issubclass(context_type, ComponentContext)
        ):
            raise ComponentClassInvalidException(
                f"second positional parameter of {__init__} must be a subclass of {ComponentContext}"
            )

        if not isinstance(references_type, TypeVar) and (
            not isinstance(references_type, type)
            or not issubclass(references_type, ComponentReferences)
        ):
            raise ComponentClassInvalidException(
                f"third positional parameter of {__init__} must be a subclass of {ComponentReferences}"
            )

        if not isinstance(references_type, TypeVar):
            for binding in get_event_bindings(cls):
                if not object_has_field(references_type, binding.address.name):
                    raise ComponentClassInvalidException(
                        f"event listener {binding.function} refers to component '{binding.address.name}' which is not defined in {references_type}"
                    )

        return cls


class Component(
    Generic[ComponentParametersT, ComponentContextT, ComponentReferencesT],
    Tasklet,
    ValidateByType,
    metaclass=ComponentMeta,
):
    def __init__(
        self,
        parameters: ComponentParametersT,
        context: ComponentContextT,
        references: ComponentReferencesT,
    ) -> None:
        self.__component_parameters__ = parameters
        self.__component_context__ = context
        self.__component_references__ = references
        self.__component_internal__ = ComponentInteral()

    @classmethod
    def get_parameters_type(cls) -> type[ComponentParameters]:
        return tuple(get_type_hints(cls.__init__).values())[0]  # type: ignore

    @classmethod
    def get_context_type(cls) -> type[ComponentContext]:
        return tuple(get_type_hints(cls.__init__).values())[1]  # type: ignore

    @classmethod
    def get_references_type(cls) -> type[ComponentReferences]:
        return tuple(get_type_hints(cls.__init__).values())[2]  # type: ignore

    @classmethod
    def get_event_bindings(cls) -> Sequence[EventBinding]:
        return get_event_bindings(cls)

    @property
    def id(self) -> UUID:
        return self.__component_context__.id

    @property
    def address(self) -> ComponentAddress:
        return self.__component_context__.address

    @property
    def parameters(self) -> ComponentParametersT:
        return self.__component_parameters__

    @property
    def context(self) -> ComponentContextT:
        return self.__component_context__

    @property
    def references(self) -> ComponentReferencesT:
        return self.__component_references__

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


ComponentInterface = Component[ComponentParameters, ComponentContext, ComponentReferences]


class WithParameters(Generic[ComponentParametersT]):
    @property
    def parameters(self) -> ComponentParametersT:
        return self.__component_parameters__  # type: ignore


class WithContext(Generic[ComponentContextT]):
    @property
    def context(self) -> ComponentContextT:
        return self.__component_context__  # type: ignore


class WithReferences(Generic[ComponentReferencesT]):
    @property
    def references(self) -> ComponentReferencesT:
        return self.__component_references__  # type: ignore
