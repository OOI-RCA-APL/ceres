import asyncio
import dataclasses
import inspect
import traceback
from asyncio import Queue as AsyncQueue
from dataclasses import field
from inspect import Parameter
from logging import CRITICAL, DEBUG, ERROR, INFO, WARNING, Logger
from string import ascii_lowercase
from types import MappingProxyType
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterable,
    Awaitable,
    Callable,
    FrozenSet,
    Mapping,
    Sequence,
    TypeVar,
    final,
    get_type_hints,
)
from uuid import UUID, uuid4
from weakref import WeakValueDictionary, ref

from pydantic import Field, ValidationError, validate_arguments, validator
from typing_extensions import dataclass_transform

from .address import ComponentAddress
from .alert import Alert, AlertLevel
from .config import JobConfig
from .data import (
    VALIDATED_DATACLASS_FIELD_SPECIFIERS,
    ImmutableDataObject,
    ValidatedDataclass,
    jsonify,
)
from .database.entity import AlertEntity, MessageEntity
from .directory import Directory
from .environment import Environment
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
from .internal.database.buffer import WriteBuffer
from .internal.scheduler import Scheduler
from .internal.tasklet import Tasklet
from .internal.utilities import (
    awaitify,
    cached,
    get_type_annotations,
    has_field,
    lenient_isinstance,
    lenient_issubclass,
    pre_validate_arguments,
    randstr,
    sleep_forever,
    strify,
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
from .routine import RoutineBinding, routine
from .schedule import Schedule
from .stream import Stream, StreamView
from .types import Name
from .validation import ValidationProblem

if TYPE_CHECKING:
    from .engine import Engine
    from .unit import Unit
else:
    Engine = "Engine"
    Unit = "Unit"

_ComponentT = TypeVar("_ComponentT", bound="Component")
_EventT = TypeVar("_EventT", bound=Event)


class ComponentPaths(ImmutableDataObject):
    unit: Directory = Field(default_factory=Directory)
    component: Directory = Field(default_factory=Directory)
    data: Directory = Field(default_factory=Directory)


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
        references_hint = hints.get("references")
        component_field_names = {field.name for field in dataclasses.fields(Component)}

        if (
            not all(
                i == 0
                or (
                    parameter.kind == Parameter.KEYWORD_ONLY
                    and (
                        parameter.name in component_field_names
                        or parameter.default is not Parameter.empty
                    )
                )
                for i, parameter in enumerate(signature.parameters.values())
            )
            or parameters_hint is None
            or references_hint is None
            or not is_subclass_or_typevar(parameters_hint, Component.Parameters)
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

                    if not has_field(references_hint, source):
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
                    result = self.__handler(*[event][: self.__handler_arity])
                    if inspect.iscoroutine(result):
                        await result
                except Exception:
                    self.__logger.error(
                        f"An exception occurred while processing event {event}: {traceback.format_exc()}"
                    )
                finally:
                    self.__queue.task_done()

        async def wait_until_empty(self) -> None:
            if self.__queue.empty():
                return

            await self.__queue.join()

    class Parameters(ImmutableDataObject):
        pass

    class References(ImmutableDataObject):
        def get_components(self, alias: str | None = None) -> Sequence["Component"]:
            components = []

            if alias is None:
                for alias in self.dict().keys():
                    components.extend(self.get_components(alias))

                return components

            reference = getattr(self, alias, None)
            if isinstance(reference, Component):
                components.append(reference)
            elif isinstance(reference, Sequence):
                for component in reference:
                    if isinstance(component, Component):
                        components.append(component)

            return components

    id: UUID = field(default_factory=uuid4)
    address: ComponentAddress = field(
        default_factory=lambda: ComponentAddress.create("default", randstr(ascii_lowercase, 8))
    )
    if TYPE_CHECKING:
        environment: Environment = field(default_factory=Environment)
    else:
        environment: Environment | None = field(default=None)

    paths: ComponentPaths = field(default_factory=ComponentPaths)

    parameters: Parameters = field(default_factory=Parameters)
    references: References = field(default_factory=References)
    jobs: Mapping[Name, JobConfig] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.__unit: ref[Unit] | None = None
        self.__events: Stream[Event] = Stream()
        self.__scheduler = Scheduler()
        self.__referencers: WeakValueDictionary[UUID, Component] = WeakValueDictionary()

    def __post_init_post_parse__(self) -> None:
        self.__has_exclusive_temporary_environment = self.environment is None
        if self.__has_exclusive_temporary_environment:
            self.environment = Environment()

        self.__message_write_buffer = WriteBuffer(
            MessageEntity,
            self.environment.database,
            self.logger,
        )
        self.__alert_write_buffer = WriteBuffer(
            AlertEntity,
            self.environment.database,
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

        for component in self.references.get_components():
            component.__add_referencer(self)

    @validator("jobs")
    def _validate_jobs(cls, jobs: Mapping[Name, JobConfig]) -> Mapping[Name, JobConfig]:
        for job_name in jobs.keys():
            if job_name not in cls.get_job_bindings():
                defined = sorted(cls.get_job_bindings().keys())
                raise ValueError(
                    f"{strify(cls)} has no job named '{job_name}', defined jobs are {defined}"
                )

        for job in cls.get_job_bindings().values():
            job_config = jobs.get(job.name)
            if job_config is None or job_config.input is None:
                if job.input is not None and job.input.required:
                    raise ValueError(
                        f"missing required input for job '{job.name}', set 'jobs.{job.name}.input' to a non-none value"
                    )

                # TODO: Validate job input is correct type.

        return jobs

    @final
    @classmethod
    def get_parameters_type(cls) -> type[Parameters]:
        return get_type_annotations(cls)["parameters"]  # type: ignore

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
    def get_routine_bindings(cls) -> Sequence[RoutineBinding]:
        return _get_routine_bindings(cls)

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
    def name(self) -> str:
        return self.address.name

    @property
    def engine(self) -> "Engine | None":
        if self.unit is None:
            return None

        return self.unit.engine

    @property
    def unit(self) -> "Unit | None":
        if self.__unit is None:
            return None

        return self.__unit()

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
    def settled(self) -> bool:
        return not self.running or (
            all(processor.idle for processor in self.__event_processors)
            and len(self.__message_write_buffer) == 0
            and len(self.__alert_write_buffer) == 0
        )

    async def settle(self) -> None:
        while not self.settled:
            await asyncio.gather(
                *(processor.wait_until_empty() for processor in self.__event_processors),
                self.__message_write_buffer.wait_until_empty(),
                self.__alert_write_buffer.wait_until_empty(),
            )

    def __add_referencer(self, referencer: "Component") -> None:
        assert referencer is not self
        self.__referencers[referencer.id] = referencer

    def __set_emitted_event_source(self, event: Event) -> None:
        if event.source is None:
            object.__setattr__(event, "source", self.address)

        if isinstance(event, AlertEmittedEvent):
            self.__set_emitted_alert_source(event.alert)

    def __set_emitted_alert_source(self, alert: Alert) -> None:
        if alert.source is None:
            object.__setattr__(alert, "source", self.address)

    def attach_to_unit(self, unit: Unit) -> None:
        if unit.get_component(self.name) is not self:
            raise ValueError("attached unit does not contain this component")

        self.__unit = ref(unit)

    def detach_from_unit(self) -> None:
        self.__unit = None

    def emit_event(self, event: _EventT) -> _EventT:
        self.__set_emitted_event_source(event)
        # Handle "self" events.
        self.handle_event(event)
        # Send the event to all components have a reference to this one.
        for referencer in self.__referencers.values():
            referencer.handle_event(event)
        # Add the event to the outgoing event stream.
        self.__events.put(event)
        # Pass the event up to the containing unit if it exists.
        if self.unit is not None:
            self.unit.emit_event(event)

        match event:
            case MessageSentEvent() | MessageReceivedEvent():
                self.__message_write_buffer.add(
                    MessageEntity(
                        id=event.message.id,
                        component_id=self.id,  # TODO: Actually use the passed ID.
                        timestamp=event.message.timestamp,
                        direction=MessageDirection.RECEIVE,
                        content=event.message.content,
                    )
                )
            case AlertEmittedEvent():
                self.__alert_write_buffer.add(
                    AlertEntity(
                        id=event.alert.id,
                        component_id=self.id,  # TODO: Actually use the passed ID.
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

            for alias in processor.binding.sources:
                if (alias == "self" and self.address == event.source) or any(
                    component.address == event.source
                    for component in self.references.get_components(alias)
                ):
                    processor.put(event)
                    break

    def emit_alert(self, alert: Alert) -> Alert:
        self.__set_emitted_alert_source(alert)

        match alert.level:
            case AlertLevel.DEBUG:
                log_level = DEBUG
            case AlertLevel.INFO:
                log_level = INFO
            case AlertLevel.WARNING:
                log_level = WARNING
            case AlertLevel.ERROR:
                log_level = ERROR
            case AlertLevel.CRITICAL:
                log_level = CRITICAL

        self.emit_event(AlertEmittedEvent(alert=alert))
        self.logger.log(log_level, f"Alert: {jsonify(alert)}")
        return alert

    def add_job(
        self,
        function: Callable[[], Any],
        schedule: Schedule,
        name: str | None = None,
    ) -> None:
        self.__scheduler.add_job(function, schedule, name=name)

    def remove_job(self, name: str | Callable[[], Any]) -> None:
        self.__scheduler.remove_job(name)

    def __start_scheduler(self) -> None:
        self.__scheduler.start()

        for job in self.get_job_bindings().values():
            job_config = self.jobs.get(job.name)

            if job_config is not None and job_config.input is not None:
                input = job_config.input
            else:
                if job.input is not None:
                    input = job.input.default
                else:
                    input = None

            if job_config is not None and job_config.schedule is not None:
                schedule = job_config.schedule
            else:
                schedule = job.default_schedule

            if schedule is None:
                continue

            async def run_job() -> None:
                self.logger.info(f"Running job '{job.name}'...")
                match await self.call(CallableProcedureKind.JOB, job.name, input):
                    case Ok():
                        self.logger.info(f"Job '{job.name}' finished.")
                        pass
                    case Fail(error):
                        self.logger.error(
                            f"An error occurred while running job '{job.name}': {strify(error)}"
                        )

            self.logger.info(f"Scheduling job '{job.name}' on {schedule}.")
            self.scheduler.add_job(run_job, schedule, name=job.name)

    async def __run__(self) -> None:
        if self.__has_exclusive_temporary_environment:
            await self.environment.database.init()
            await self.environment.get_component_id(self.address, self.id)

        self.__start_scheduler()

        await asyncio.gather(
            sleep_forever(),
            *(self.__process_routine(binding) for binding in self.get_routine_bindings()),
        )

    async def __process_routine(self, binding: RoutineBinding) -> None:
        routine = getattr(self, binding.function, None)
        if routine is None:
            return

        try:
            await routine()
        except Exception:
            self.logger.error(
                f"An exception occurred while running routine '{strify(binding.function)}': {strify(traceback.format_exc())}"
            )

    @routine
    async def __run_event_processors(self) -> None:
        await asyncio.gather(*(processor.run() for processor in self.__event_processors))

    @routine
    async def __flush_message_buffer(self) -> None:
        while True:
            if not self.__message_write_buffer.flushing:
                await self.__message_write_buffer.flush()
            await asyncio.sleep(0.1)

    @routine
    async def __flush_alert_buffer(self) -> None:
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
        if self.__has_exclusive_temporary_environment:
            await self.environment.database.dispose()

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

    async def __invoke(
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
        return await self.__invoke(kind.upcast(), procedure, input)

    async def subscribe(
        self,
        kind: SubscribableProcedureKind,
        procedure: str,
        input: object | None = None,
    ) -> Result[AsyncIterable[object | None], ProcedureError]:
        values: AsyncIterable[object | None]

        match await self.__invoke(kind.upcast(), procedure, input):
            case Ok(values):  # type: ignore
                pass
            case fail:
                return fail

        async def iterate() -> AsyncIterable[object | None]:
            try:
                async for value in values:
                    yield value
            except Exception:
                self.logger.error(
                    f"An exception occurred in {kind.value} '{procedure}': {traceback.format_exc()}"
                )
                raise

        return Ok(iterate())


@cached
def _get_listener_bindings(component_cls: type[Component]) -> Sequence[ListenerBinding]:
    return tuple(get_bindings(component_cls, ListenerBinding))


@cached
def _get_routine_bindings(component_cls: type[Component]) -> Sequence[RoutineBinding]:
    return tuple(get_bindings(component_cls, RoutineBinding))


_ProcedureBindingT = TypeVar("_ProcedureBindingT", bound=BaseProcedureBinding)


@cached
def _get_procedure_bindings(
    component_cls: type[_ComponentT],
    binding_cls: type[_ProcedureBindingT],
) -> Mapping[str, _ProcedureBindingT]:
    return MappingProxyType(
        {binding.name: binding for binding in get_bindings(component_cls, binding_cls)}
    )
