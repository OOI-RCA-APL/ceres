import dataclasses
import inspect
import traceback
from dataclasses import dataclass, field
from inspect import Parameter
from logging import Logger
from typing import Any, Sequence, TypeVar, get_type_hints
from uuid import UUID, uuid4

from typing_extensions import dataclass_transform

from .address import ComponentAddress
from .alert import Alert, AlertLevel, RawAlertLevel
from .config import ComponentConfig, Config, UnitConfig
from .events import AlertEmittedEvent, Event, EventBinding, get_event_bindings
from .exceptions import ComponentClassInvalidException
from .internal import logs
from .internal.database.entity import EntityManager
from .internal.database.manager import DatabaseManager
from .internal.tasklet import Tasklet
from .internal.utilities import get_type_annotations, loose_isinstance, object_has_field
from .scheduler import Scheduler
from .stream import Stream, StreamView
from .utilities import (
    VALIDATED_DATACLASS_FIELD_SPECIFIERS,
    ValidatedDataclassMeta,
    awaitify,
    utc,
)


@dataclass(kw_only=True)
class ComponentInteral:
    incoming_event_stream: Stream[Event] = field(default_factory=Stream)
    outgoing_event_stream: Stream[Event] = field(default_factory=Stream)
    scheduler: Scheduler = field(default_factory=Scheduler)


ComponentT = TypeVar("ComponentT", bound="Component")
EventT = TypeVar("EventT", bound=Event)


@dataclass_transform(
    kw_only_default=True,
    field_specifiers=VALIDATED_DATACLASS_FIELD_SPECIFIERS,
)
class ComponentMeta(ValidatedDataclassMeta):
    def __new__(
        metacls,  # type: ignore
        name: str,
        bases: tuple[type[Any], ...],
        namespace: dict[str, Any],
        **kwargs: Any,
    ) -> type[Any]:
        cls: type["Component"] = super().__new__(metacls, name, bases, namespace, **kwargs)  # type: ignore
        if cls.__module__ == __name__ and cls.__name__ == "Component":
            return cls

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
            or not is_subclass_or_typevar(parameters_hint, Component.Parameters)
            or not is_subclass_or_typevar(context_hint, Component.Context)
            or not is_subclass_or_typevar(references_hint, Component.References)
        ):
            raise ComponentClassInvalidException(
                f"signature of {__init__} must be compatible with {inspect.signature(Component.__init__)}, got {signature}"
            )

        if isinstance(references_hint, type) and issubclass(references_hint, Component.References):
            for binding in cls.get_event_bindings():
                if not object_has_field(references_hint, binding.address.name):
                    raise ComponentClassInvalidException(
                        f"event listener {binding.function} refers to component '{binding.address.name}' which is not defined in {references_hint.__init__} with signature {inspect.signature(references_hint.__init__)}"
                    )

        return cls


class Component(Tasklet, metaclass=ComponentMeta):
    class Context(metaclass=ValidatedDataclassMeta, frozen=True):
        id: UUID = field(default_factory=uuid4)
        address: ComponentAddress

        def __post_init__(self) -> None:
            extra: list[tuple[str, Any]] = []

            for current in dataclasses.fields(self):
                if not object_has_field(CompleteComponentContext, current.name, current.type):
                    extra.append((current.name, current.type))

            if extra:
                raise ValueError(f"invalid context class, cannot provide fields: {extra}")

    class Parameters(metaclass=ValidatedDataclassMeta, frozen=True):
        pass

    class References(metaclass=ValidatedDataclassMeta, frozen=True):
        pass

    parameters: Parameters = field(default_factory=Parameters)
    context: Context
    references: References = field(default_factory=References)

    def __post_init__(self) -> None:
        self.__component_internal__ = ComponentInteral()

    @classmethod
    def get_parameters_type(cls) -> type[Parameters]:
        return get_type_annotations(cls)["parameters"]  # type: ignore

    @classmethod
    def get_context_type(cls) -> type[Context]:
        return get_type_annotations(cls)["context"]  # type: ignore

    @classmethod
    def get_references_type(cls) -> type[References]:
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
        return self.__component_internal__.outgoing_event_stream.view()

    def emit_event(self, event: EventT) -> EventT:
        self.__component_internal__.outgoing_event_stream.put(event)
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

        self.emit_event(
            AlertEmittedEvent(
                address=self.address,
                alert=alert,
            )
        )

        return alert

    def handle_event(self, event: Event) -> None:
        self.__component_internal__.incoming_event_stream.put(event)

    async def __run__(self) -> None:
        self.scheduler.start()
        await self._process_incoming_events()

    async def _process_incoming_events(self) -> None:
        async for event in self.__component_internal__.incoming_event_stream:
            await self._process_incoming_event(event)

    async def _process_incoming_event(self, event: Event) -> None:
        for binding in self.get_event_bindings():
            if not loose_isinstance(event, binding.cls):
                continue
            target = getattr(self.references, binding.address.name, None)
            if not isinstance(target, Component):
                continue
            if target.context.address != event.address:
                continue

            if method := getattr(self, binding.function.__name__, None):
                try:
                    if len(inspect.signature(method).parameters) == 0:
                        await awaitify(method())
                    else:
                        await awaitify(method(event))
                except Exception:
                    self.logger.error(
                        f"An exception occurred while processing event {event}: {traceback.format_exc()}"
                    )

    async def __stop__(self) -> None:
        self.scheduler.stop()


class CompleteComponentContext(Component.Context):
    id: UUID
    root_config: Config
    unit_config: UnitConfig
    component_config: ComponentConfig
    database: DatabaseManager
    entities: EntityManager
