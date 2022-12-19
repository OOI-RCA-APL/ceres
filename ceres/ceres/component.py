import asyncio
import inspect
import traceback
from asyncio import Queue as AsyncQueue
from dataclasses import field
from inspect import Parameter
from logging import ERROR, INFO, WARNING, Logger
from string import ascii_lowercase
from types import MappingProxyType
from typing import (
    Any,
    AsyncIterable,
    Awaitable,
    Callable,
    FrozenSet,
    Mapping,
    Sequence,
    TypeVar,
    cast,
    final,
    get_type_hints,
)
from uuid import UUID, uuid4
from weakref import WeakValueDictionary

from pydantic import Field, ValidationError, validate_arguments
from typing_extensions import dataclass_transform

from .address import ComponentAddress, caddr
from .alert import Alert, AlertLevel
from .config import ComponentConfig, Config, UnitConfig
from .data import (
    VALIDATED_DATACLASS_FIELD_SPECIFIERS,
    ImmutableDataObject,
    ValidatedDataclass,
    jsonify,
)
from .errors import (
    ProcedureDoesNotExistError,
    ProcedureError,
    ProcedureExceptionError,
    ProcedureInvalidInputError,
)
from .events import AlertEmittedEvent, Event, MessageReceivedEvent, MessageSentEvent
from .exceptions import ComponentClassInvalidException
from .internal import logs
from .internal.binding import get_bindings
from .internal.database import Database
from .internal.database.buffer import WriteBuffer
from .internal.database.entity import AlertEntity, MessageEntity
from .internal.tasklet import Tasklet
from .internal.utilities import (
    UNSET_UUID,
    awaitify,
    cached,
    get_type_annotations,
    lenient_isinstance,
    lenient_issubclass,
    object_has_field,
    pre_validate_arguments,
    randstr,
)
from .listener import ListenerBinding
from .message import MessageDirection
from .procedure import (
    ActionBinding,
    BaseProcedureBinding,
    CallableProcedureKind,
    DisplayBinding,
    JobBinding,
    ProcedureKind,
    QueryBinding,
    SubscribableProcedureKind,
    SubscriptionBinding,
    subscription,
)
from .result import Fail, Ok, Result
from .scheduler import Scheduler
from .stream import Stream, StreamView
from .validation import ValidationProblem

_ComponentT = TypeVar("_ComponentT", bound="Component")
_EventT = TypeVar("_EventT", bound=Event)


@dataclass_transform(
    kw_only_default=True,
    field_specifiers=VALIDATED_DATACLASS_FIELD_SPECIFIERS,
)
class Component(ValidatedDataclass, Tasklet):
    def __init_subclass__(cls, **kwargs: Any) -> type[Any]:
        super().__init_subclass__(**kwargs)

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

        if lenient_issubclass(references_hint, Component.References):
            for binding in cls.get_listener_bindings():
                for source in binding.sources:
                    if source == "self":
                        continue

                    if not object_has_field(references_hint, source):
                        raise ComponentClassInvalidException(
                            f"event listener {binding.function} refers to component '{source}' which is not defined as an attribute in {references_hint}"
                        )

        return cls

    @final
    class __EventProcessor:
        __slots__ = (
            "__binding",
            "__handler",
            "__handler_arity",
            "__logger",
            "__queue",
        )

        def __init__(
            self,
            *,
            binding: ListenerBinding,
            handler: Callable[[Event], None | Awaitable[None]]
            | Callable[[], None | Awaitable[None]],
            logger: Logger,
        ) -> None:
            self.__binding = binding
            self.__handler = handler
            self.__handler_arity = len(inspect.signature(self.__handler).parameters)
            self.__logger = logger
            self.__queue: AsyncQueue[Event] = AsyncQueue()

        @property
        def binding(self) -> ListenerBinding:
            return self.__binding

        @property
        def idle(self) -> bool:
            return self.__queue._finished.is_set()  # type: ignore

        def put(self, event: Event) -> None:
            self.__queue.put_nowait(event)

        def clear(self) -> None:
            while not self.__queue.empty():
                self.__queue.get_nowait()
                self.__queue.task_done()

        async def run(self) -> None:
            while True:
                event = await self.__queue.get()

                try:
                    if self.__handler_arity == 0:
                        await awaitify(self.__handler())  # type: ignore
                    else:
                        await awaitify(self.__handler(event))  # type: ignore
                except Exception:
                    self.__logger.error(
                        f"An exception occurred while processing event {event}: {traceback.format_exc()}"
                    )
                finally:
                    self.__queue.task_done()

        async def join(self) -> None:
            await self.__queue.join()

    class Parameters(ImmutableDataObject):
        pass

    class Context(ImmutableDataObject):
        id: UUID = Field(default_factory=uuid4)
        address: ComponentAddress = Field(
            default_factory=lambda: caddr(randstr(ascii_lowercase, 8))
        )
        database: Database = Field(default_factory=Database)

        def __init_subclass__(cls) -> None:
            if cls.__module__ == __name__:
                return

            extra: list[tuple[str, Any]] = []

            for current in cls.__fields__.values():
                if not object_has_field(CompleteContext, current.name, current.type_):
                    extra.append((current.name, current.type_))

            if extra:
                raise ValueError(f"invalid context class, cannot provide fields: {extra}")

    class References(ImmutableDataObject):
        pass

    parameters: Parameters = field(default_factory=Parameters)
    context: Context = field(default_factory=Context)
    references: References = field(default_factory=References)

    def __post_init__(self) -> None:
        self.__events: Stream[Event] = Stream()
        self.__scheduler = Scheduler()
        self.__message_write_buffer: WriteBuffer[MessageEntity]
        self.__alert_write_buffer: WriteBuffer[AlertEntity]
        self.__referencers: WeakValueDictionary[UUID, Component] = WeakValueDictionary()

    def __post_init_post_parse__(self) -> None:
        self.__message_write_buffer = WriteBuffer(
            MessageEntity,
            self.context.database,
            self.logger,
        )
        self.__alert_write_buffer = WriteBuffer(
            AlertEntity,
            self.context.database,
            self.logger,
        )
        self.__event_processors = [
            self.__EventProcessor(
                binding=binding,
                handler=getattr(self, binding.function),
                logger=self.logger,
            )
            for binding in self.get_listener_bindings()
        ]

        for component in self.references.dict().values():
            if isinstance(component, Component):
                component.__add_referencer(self)

    @final
    @classmethod
    def get_parameters_type(cls) -> type[Parameters]:
        return get_type_annotations(cls)["parameters"]  # type: ignore

    @final
    @classmethod
    def get_context_type(cls) -> type[Context]:
        return get_type_annotations(cls)["context"]  # type: ignore

    @final
    @classmethod
    def get_references_type(cls) -> type[References]:
        return get_type_annotations(cls)["references"]  # type: ignore

    @final
    @classmethod
    def get_listener_bindings(cls) -> Sequence[ListenerBinding]:
        return _get_listener_bindings(cls)

    @final
    @classmethod
    def get_query_bindings(cls) -> Mapping[str, QueryBinding]:
        return _get_procedure_bindings(cls, QueryBinding)

    @final
    @classmethod
    def get_action_bindings(cls) -> Mapping[str, ActionBinding]:
        return _get_procedure_bindings(cls, ActionBinding)

    @final
    @classmethod
    def get_job_bindings(cls) -> Mapping[str, JobBinding]:
        return _get_procedure_bindings(cls, JobBinding)

    @final
    @classmethod
    def get_subscription_bindings(cls) -> Mapping[str, SubscriptionBinding]:
        return _get_procedure_bindings(cls, SubscriptionBinding)

    @final
    @classmethod
    def get_display_bindings(cls) -> Mapping[str, DisplayBinding]:
        return _get_procedure_bindings(cls, DisplayBinding)

    @final
    @classmethod
    def get_procedure_bindings(cls, kind: "ProcedureKind") -> Mapping[str, BaseProcedureBinding]:
        match kind:
            case ProcedureKind.QUERY:
                return cls.get_query_bindings()
            case ProcedureKind.ACTION:
                return cls.get_action_bindings()
            case ProcedureKind.JOB:
                return cls.get_job_bindings()
            case ProcedureKind.SUBSCRIPTION:
                return cls.get_subscription_bindings()
            case ProcedureKind.DISPLAY:
                return cls.get_display_bindings()

    @property
    def id(self) -> UUID:
        return self.context.id

    @property
    def address(self) -> ComponentAddress:
        return self.context.address

    @property
    def database(self) -> Database:
        return self.context.database

    @property
    def scheduler(self) -> Scheduler:
        return self.__scheduler

    @property
    def logger(self) -> Logger:
        return logs.get(str(self.address))

    @property
    def events(self) -> StreamView[Event]:
        return self.__events.view()

    @property
    def __has_exclusive_temporary_database(self) -> bool:
        return "database" not in self.context.__fields_set__

    @property
    def settled(self) -> bool:
        return not self.running or (
            all(processor.idle for processor in self.__event_processors)
            and len(self.__message_write_buffer) == 0
            and len(self.__alert_write_buffer) == 0
        )

    async def settle(self) -> None:
        while not self.settled:
            await asyncio.gather(
                *(processor.join() for processor in self.__event_processors),
                self.__message_write_buffer.join(),
                self.__alert_write_buffer.join(),
            )

    def __add_referencer(self, referencer: "Component") -> None:
        assert referencer is not self
        self.__referencers[referencer.id] = referencer

    def __set_emitted_event_component_id(self, event: Event) -> None:
        if event.component_id == UNSET_UUID:
            object.__setattr__(event, "component_id", self.id)

        if isinstance(event, AlertEmittedEvent):
            self.__set_emitted_alert_component_id(event.alert)

    def __set_emitted_alert_component_id(self, alert: Alert) -> None:
        if alert.component_id == UNSET_UUID:
            object.__setattr__(alert, "component_id", self.id)

    def emit_event(self, event: _EventT) -> _EventT:
        self.__set_emitted_event_component_id(event)
        # Handle "self" events.
        self.handle_event(event)
        # Send the event to all components have a reference to this one.
        for referencer in self.__referencers.values():
            referencer.handle_event(event)
        # Add the event to the outgoing event stream.
        self.__events.put(event)

        match event:
            case MessageSentEvent() | MessageReceivedEvent():
                self.__message_write_buffer.add(
                    MessageEntity(
                        id=event.message.id,
                        component_id=event.message.component_id,
                        timestamp=event.message.timestamp,
                        direction=MessageDirection.RECEIVE,
                        content=event.message.content,
                    )
                )
            case AlertEmittedEvent():
                self.__alert_write_buffer.add(
                    AlertEntity(
                        id=event.alert.id,
                        component_id=event.alert.component_id,
                        timestamp=event.alert.timestamp,
                        level=event.alert.level,
                        code=event.alert.code,
                        info=dict(event.alert.info),
                    )
                )
            case _:
                pass

        return event

    def handle_event(self, event: Event) -> None:
        if not self.running or self.stopping:
            return

        for processor in self.__event_processors:
            if not lenient_isinstance(event, processor.binding.event_cls):
                continue

            for source in processor.binding.sources:
                if source == "self":
                    component = self
                else:
                    component = getattr(self.references, source, None)

                if component is not None and component.id == event.component_id:
                    processor.put(event)
                    break

    def emit_alert(self, alert: Alert) -> Alert:
        self.__set_emitted_alert_component_id(alert)

        match alert.level:
            case AlertLevel.INFO:
                log_level = INFO
            case AlertLevel.WARNING:
                log_level = WARNING
            case AlertLevel.ERROR:
                log_level = ERROR

        self.emit_event(AlertEmittedEvent(alert=alert))
        self.logger.log(log_level, f"Alert: {jsonify(alert)}")
        return alert

    async def __run__(self) -> None:
        if self.__has_exclusive_temporary_database:
            await self.database.init()

        self.__scheduler.start()

        for job in self.get_job_bindings().values():
            if job.default_schedule is None:
                continue

            if (method := getattr(self, job.function, None)) is None:
                continue

            async def run_job() -> None:
                if method is None:
                    return

                try:
                    if job.default_input is ...:
                        await awaitify(method())
                    else:
                        await awaitify(method(job.default_input))
                except Exception:
                    self.logger.error(
                        f"An exception occurred while running job '{job.name}': {traceback.format_exc()}"
                    )

            self.logger.info(f"Scheduling job '{job.name}' as: {job.default_schedule}")
            self.scheduler.add_job(run_job, job.default_schedule, name=job.name)

        await asyncio.gather(
            self.__process_event_processors(),
            self.__process_message_buffer(),
            self.__process_alert_buffer(),
        )

    async def __process_event_processors(self) -> None:
        await asyncio.gather(*(processor.run() for processor in self.__event_processors))

    async def __process_message_buffer(self) -> None:
        while True:
            if not self.__message_write_buffer.flushing:
                await self.__message_write_buffer.flush()
            await asyncio.sleep(0.1)

    async def __process_alert_buffer(self) -> None:
        while True:
            if not self.__alert_write_buffer.flushing:
                await self.__alert_write_buffer.flush()
            await asyncio.sleep(0.1)

    async def __stop__(self) -> None:
        self.__scheduler.stop()
        self.__scheduler = Scheduler()
        await asyncio.gather(
            self.__message_write_buffer.flush(),
            self.__alert_write_buffer.flush(),
        )

    class SubscribeEventsInput(ImmutableDataObject):
        kinds: str | FrozenSet[str] | None = None

    @subscription("events")
    async def subscribe_events(
        self,
        input: SubscribeEventsInput = SubscribeEventsInput(),
    ) -> AsyncIterable[Event]:
        match input.kinds:
            case None:
                kinds = None
            case str():
                kinds = {input.kinds}
            case _:
                kinds = input.kinds

        async for event in self.events:
            if kinds is None or event.kind in kinds:
                yield event

    async def _invoke(
        self,
        kind: "ProcedureKind",
        procedure: str,
        input: object | None = None,
    ) -> Result[object | None, ProcedureError]:
        if (
            (binding := self.get_procedure_bindings(kind).get(procedure)) is None
            or (method := getattr(self, binding.function, None)) is None
            or not inspect.ismethod(method)
        ):
            return Fail(ProcedureDoesNotExistError())

        arguments: list[object] = []
        if input is not None:
            arguments.append(input)

        try:
            pre_validate_arguments(method, *arguments)
        except ValidationError as error:
            return Fail(ProcedureInvalidInputError(problems=ValidationProblem.extract(error)))

        try:
            return Ok(await awaitify(validate_arguments(method)(*arguments)))
        except Exception:
            return Fail(ProcedureExceptionError(traceback=traceback.format_exc()))

    async def call(
        self,
        kind: CallableProcedureKind,
        procedure: str,
        input: object | None = None,
    ) -> Result[object | None, ProcedureError]:
        return await self._invoke(kind.upcast(), procedure, input)

    async def subscribe(
        self,
        kind: SubscribableProcedureKind,
        procedure: str,
        input: object | None = None,
    ) -> Result[AsyncIterable[object | None], ProcedureError]:
        return cast(
            Result[AsyncIterable[object | None], ProcedureError],
            await self._invoke(kind.upcast(), procedure, input),
        )


class CompleteContext(Component.Context):
    id: UUID
    address: ComponentAddress
    root_config: Config
    unit_config: UnitConfig
    component_config: ComponentConfig
    database: Database


@cached
def _get_listener_bindings(component_cls: type[Component]) -> Sequence[ListenerBinding]:
    return tuple(get_bindings(component_cls, ListenerBinding))


_ProcedureBindingT = TypeVar("_ProcedureBindingT", bound=BaseProcedureBinding)


@cached
def _get_procedure_bindings(
    component_cls: type[_ComponentT],
    binding_cls: type[_ProcedureBindingT],
) -> Mapping[str, _ProcedureBindingT]:
    return MappingProxyType(
        {binding.name: binding for binding in get_bindings(component_cls, binding_cls)}
    )
