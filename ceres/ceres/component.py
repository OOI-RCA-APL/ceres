import dataclasses
import inspect
import traceback
from abc import ABCMeta
from dataclasses import dataclass, field
from inspect import Parameter
from logging import Logger
from typing import Any, Callable, Sequence, TypeVar, cast, get_type_hints
from uuid import UUID, uuid4

from pydantic import Field
from pydantic.fields import FieldInfo
from typing_extensions import dataclass_transform

from .address import ComponentAddress
from .alert import Alert, AlertLevel, RawAlertLevel
from .config import ComponentConfig, Config, UnitConfig, UserConfig
from .events import Event, EventBinding, get_event_bindings
from .exceptions import ComponentClassInvalidException
from .internal import logs
from .internal.database.manager import DatabaseManager
from .internal.tasks import Tasklet
from .internal.utilities import (
    frozendict,
    frozenlist,
    get_type_annotations,
    object_has_field,
    sleep_forever,
)
from .scheduler import Scheduler
from .stream import Stream, StreamView
from .utilities import awaitify, utc, vdc


@vdc(frozen=True)
class ComponentParameters:
    pass


ComponentParametersT = TypeVar("ComponentParametersT", bound=ComponentParameters)


@vdc(frozen=True)
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


@vdc(frozen=True)
class CompleteComponentContext(ComponentContext):
    id: UUID
    root_config: Config
    unit_config: UnitConfig
    component_config: ComponentConfig
    users: frozenlist[UserConfig]
    units: frozenlist[UnitConfig]
    database: DatabaseManager


ComponentContextT = TypeVar("ComponentContextT", bound=ComponentContext)


@vdc(frozen=True)
class ComponentReferences:
    pass


ComponentReferencesT = TypeVar("ComponentReferencesT", bound=ComponentReferences)


@dataclass(kw_only=True)
class ComponentInteral:
    event_stream: Stream[Event] = field(default_factory=Stream)
    alert_stream: Stream[Alert] = field(default_factory=Stream)
    scheduler: Scheduler = field(default_factory=Scheduler)


ComponentT = TypeVar("ComponentT", bound="Component")

_COMPONENT_FIELD_SPECIFIERS: tuple[Callable[..., Any], type[FieldInfo]] = (Field, FieldInfo)


@dataclass_transform(kw_only_default=True, field_specifiers=_COMPONENT_FIELD_SPECIFIERS)
class ComponentMeta(ABCMeta):
    def __new__(
        cls,
        name: str,
        bases: tuple[type[Any], ...],
        namespace: dict[str, Any],
        **kwargs: Any,
    ) -> type[Any]:
        cls = super().__new__(cls, name, bases, namespace, **kwargs)
        cls = vdc(cls)  # type: ignore

        __init__ = cls.__init__
        hints = get_type_hints(__init__)
        signature = inspect.signature(__init__)

        def is_subclass_or_typevar(subcls: type, cls: type) -> bool:
            if isinstance(subcls, TypeVar):
                return True

            return isinstance(cls, type) and isinstance(subcls, type) and issubclass(subcls, cls)

        parameters_hint = hints.get("parameters")
        context_hint = hints.get("context")
        references_hint = hints.get("references")

        if (
            not all(
                i == 0
                or (
                    parameter.kind == Parameter.KEYWORD_ONLY
                    and (
                        parameter.name in ("parameters", "context", "references")
                        or parameter.default != Parameter.empty
                    )
                )
                for i, parameter in enumerate(signature.parameters.values())
            )
            or not parameters_hint
            or not context_hint
            or not references_hint
            or not is_subclass_or_typevar(parameters_hint, ComponentParameters)
            or not is_subclass_or_typevar(context_hint, ComponentContext)
            or not is_subclass_or_typevar(references_hint, ComponentReferences)
        ):
            raise ComponentClassInvalidException(
                f"signature of {__init__} must be compatible with {inspect.signature(Component.__init__)}, got {signature}"
            )

        if isinstance(references_hint, type) and issubclass(references_hint, ComponentReferences):
            for binding in cls.get_event_bindings():
                if not object_has_field(references_hint, binding.address.name):
                    raise ComponentClassInvalidException(
                        f"event listener {binding.function} refers to component '{binding.address.name}' which is not defined in {references_hint.__init__} with signature {inspect.signature(references_hint.__init__)}"
                    )

        return cls


class Component(Tasklet, metaclass=ComponentMeta):
    parameters: ComponentParameters
    context: ComponentContext
    references: ComponentReferences

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
            timestamp=utc(),
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
        await sleep_forever()

    async def _tasklet_stop(self) -> None:
        self.scheduler.stop()
