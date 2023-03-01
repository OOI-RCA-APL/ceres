import asyncio
import dataclasses
import inspect
import logging
import traceback
from asyncio import Queue as AsyncQueue
from dataclasses import field
from functools import partial
from inspect import Parameter
from logging import Logger
from string import ascii_lowercase
from types import MappingProxyType
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterable,
    Awaitable,
    ByteString,
    Callable,
    Collection,
    FrozenSet,
    Mapping,
    Sequence,
    TypeVar,
    cast,
    final,
    get_args,
    get_type_hints,
)
from weakref import WeakValueDictionary, ref

from pydantic import Field, ValidationError, parse_obj_as, validate_arguments, validator
from typing_extensions import Self, dataclass_transform, override

from .address import Address
from .alert import Alert, AlertLevel
from .config import JobConfig
from .data import (
    VALIDATED_DATACLASS_FIELD_SPECIFIERS,
    ImmutableDataObject,
    Name,
    ValidatedDataclass,
    jsonify,
)
from .directory import Directory
from .environment import Environment
from .errors import (
    ComponentReferenceInvalidError,
    ProcedureDoesNotExistError,
    ProcedureInternalError,
    ProcedureInvalidInputError,
    ProcedureNotSubscribableError,
)
from .events import AlertEmittedEvent, Event, MessageReceivedEvent, MessageSentEvent
from .exceptions import ComponentClassInvalidException, ProcedureException
from .internal import logs
from .internal.binding import get_all_bindings
from .internal.database.buffer import WriteBuffer
from .internal.database.entities import AlertEntity, MessageEntity
from .internal.scheduler import Scheduler
from .internal.tasklet import Tasklet
from .internal.utilities import (
    awaitify,
    cached,
    dictify,
    get_type_annotations,
    has_field,
    is_optional,
    lenient_isinstance,
    lenient_issubclass,
    pre_validate_arguments,
    randstr,
    sleep_forever,
    strify,
)
from .layout import Layout
from .listener import ListenerBinding
from .message import Message
from .procedure import (
    ActionBinding,
    BaseProcedureBinding,
    ProcedureBinding,
    QueryBinding,
    query,
)
from .ref import Ref, RefInfo
from .result import Fail, Ok, Result
from .routine import RoutineBinding, routine
from .schedule import Schedule
from .stream import Stream, StreamView
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
    data: Directory = Field(default_factory=Directory)
    local: Directory = Field(default_factory=Directory)


@dataclass_transform(
    kw_only_default=True,
    field_specifiers=VALIDATED_DATACLASS_FIELD_SPECIFIERS,
)
class Component(ValidatedDataclass, Tasklet):
    def __init_subclass__(cls, **kwargs: Any) -> type[Any]:
        super().__init_subclass__(**kwargs)

        __init__ = cls.__init__  # type: ignore
        hints = get_type_hints(__init__)
        signature = inspect.signature(__init__)

        def is_subclass_or_typevar(subcls: type, cls: type) -> bool:
            if isinstance(subcls, TypeVar):
                return True

            return isinstance(cls, type) and isinstance(subcls, type) and issubclass(subcls, cls)

        parameters_hint = hints.get("parameters")
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
            or not is_subclass_or_typevar(parameters_hint, Component.Parameters)
        ):
            raise ComponentClassInvalidException(
                f"signature of {__init__} must be compatible with {inspect.signature(Component.__init__)}, got {signature}"
            )

        if lenient_issubclass(parameters_hint, Component.Parameters):
            for binding in cls.get_listener_bindings():
                for source in binding.sources:
                    if source == "self":
                        continue

                    if not has_field(parameters_hint, source):
                        raise ComponentClassInvalidException(
                            f"event listener '{binding.function}' refers to reference '{source}' which is not defined as an attribute in {strify(parameters_hint)}"
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
        def assign_references(
            self,
            siblings: Mapping[Name, "Component"],
        ) -> "Result[Self, ComponentReferenceInvalidError]":
            output: dict[str, Any] = dictify(self)

            def _create_reference_invalid_error(
                reference: Any,
                info: "RefInfo[Component]",
            ) -> ComponentReferenceInvalidError:
                return ComponentReferenceInvalidError(
                    message=f"reference to component '{reference}' of type {strify(info.cls)} is required and specified by {strify(type(self))}, but it hasn't loaded yet or failed to load"
                )

            for name, field in self.__fields__.items():
                field_value: Any = getattr(self, name)
                if issubclass(field.type_, Ref):
                    if isinstance(field_value, str):
                        component = siblings.get(field_value)
                    else:
                        component = field_value

                    info = cast(RefInfo[Component], field.type_)
                    if (
                        component is None
                        and not is_optional(field.type_)
                        and not is_optional(info.cls)
                    ):
                        return Fail(_create_reference_invalid_error(field_value, info))

                    output[name] = component
                    continue

                if isinstance(field_value, Collection) and not isinstance(
                    field_value, (str, ByteString)
                ):
                    try:
                        element_type = get_args(field.type_)[0]
                    except Exception:
                        continue

                    if issubclass(element_type, Ref):
                        info = cast(RefInfo[Component], element_type)
                        resolved: list[Any] = []
                        for element in field_value:
                            if isinstance(element, str):
                                component = siblings.get(element)
                            else:
                                component = element

                            if (
                                component is None
                                and not is_optional(element_type)
                                and not is_optional(info.cls)
                            ):
                                return Fail(_create_reference_invalid_error(element, info))

                        output[name] = parse_obj_as(field.type_, resolved)

            return Ok(type(self)(**output))

        def get_components(self, alias: str | None = None) -> Sequence["Component"]:
            components = []

            if alias is None:
                for alias in self.dict().keys():
                    components.extend(self.get_components(alias))

                return components

            reference = getattr(self, alias, None)
            if isinstance(reference, Component):
                components.append(reference)
            elif isinstance(reference, Collection):
                for component in reference:
                    if isinstance(component, Component):
                        components.append(component)

            return components

    name: Name = field(default_factory=lambda: randstr(ascii_lowercase, 8))
    paths: ComponentPaths = field(default_factory=ComponentPaths)

    parameters: Parameters = field(default_factory=Parameters)
    jobs: Sequence[JobConfig] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.__local_environment: Environment | None = None
        self.__unit: ref[Unit] | None = None
        self.__events: Stream[Event] = Stream()
        self.__scheduler = Scheduler()
        self.__referencers: WeakValueDictionary[Address, Component] = WeakValueDictionary()

    def __post_init_post_parse__(self) -> None:
        self.__message_write_buffer = WriteBuffer(
            Message,
            MessageEntity,
            lambda: self.environment,
            self.logger,
        )
        self.__alert_write_buffer = WriteBuffer(
            Alert,
            AlertEntity,
            lambda: self.environment,
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

        for component in self.parameters.get_components():
            component.__add_referencer(self)

    def _get_inferred_environment(self) -> Environment | None:
        if self.unit is not None:
            return self.unit.environment

        # TODO: We might want to do a topological sort here to pick the environment.
        for component in self.parameters.get_components():
            return component.environment

        return None

    @property
    def environment(self) -> Environment:
        inferred = self._get_inferred_environment()
        if inferred is not None:
            return inferred

        if self.__local_environment is None:
            self.__local_environment = Environment()

        return self.__local_environment

    @validator("jobs")
    def _validate_jobs(cls, jobs: Sequence[JobConfig]) -> Sequence[JobConfig]:
        from .internal.component import validate_jobs

        error = validate_jobs(cls, jobs)
        if error is not None:
            raise ValueError(error.message)

        return jobs

    @final
    @classmethod
    def get_parameters_type(cls) -> type[Parameters]:
        return get_type_annotations(cls)["parameters"]  # type: ignore

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
    def get_procedure_bindings(cls) -> Mapping[str, ProcedureBinding]:
        return {**cls.get_query_bindings(), **cls.get_action_bindings()}

    @classmethod
    def get_layout(cls) -> Layout | None:
        return None

    @property
    def address(self) -> Address:
        if self.unit is None:
            return Address.create("default", self.name)

        return Address.create(self.unit.name, self.name)

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
        self.__referencers[referencer.address] = referencer

    def __set_emitted_event_source(self, event: Event) -> None:
        if event.source is None:  # type: ignore
            object.__setattr__(event, "source", self.address)

        if isinstance(event, AlertEmittedEvent):
            self.__set_emitted_alert_source(event.alert)

    def __set_emitted_alert_source(self, alert: Alert) -> None:
        if alert.source is None:  # type: ignore
            object.__setattr__(alert, "source", self.address)

    def attach_to_unit(self, unit: Unit) -> None:
        if self.unit is unit:
            return

        if self.unit is not None:
            self.detach_from_unit()

        self.__unit = ref(unit)

    def detach_from_unit(self) -> None:
        if self.unit is None:
            return

        self.unit.remove_component(self)
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
                self.__message_write_buffer.add(event.message)
            case AlertEmittedEvent():
                self.__alert_write_buffer.add(event.alert)
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
                    for component in self.parameters.get_components(alias)
                ):
                    processor.put(event)
                    break

    def emit_alert(self, alert: Alert) -> Alert:
        self.__set_emitted_alert_source(alert)

        match alert.level:
            case AlertLevel.DEBUG:
                log_level = logging.DEBUG
            case AlertLevel.INFO:
                log_level = logging.INFO
            case AlertLevel.WARNING:
                log_level = logging.WARNING
            case AlertLevel.ERROR:
                log_level = logging.ERROR
            case AlertLevel.CRITICAL:
                log_level = logging.CRITICAL

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

        async def run(job: JobConfig) -> None:
            self.logger.info(f"Running job '{job.name}'...")
            try:
                await self.call(job.action, job.input)
            except ProcedureException as exception:
                self.logger.error(
                    f"An error occurred while running job '{job.name}': {strify(exception.error)}"
                )

        for job in self.jobs:
            self.logger.info(f"Scheduling job '{job.name}' on {job.schedule}.")
            self.add_job(partial(run, job), job.schedule, name=job.name)

    @override
    async def __run__(self) -> None:
        if self._get_inferred_environment() is None:
            await self.environment.database.init()
            await self.environment.assign_address_id(self.address)

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

    @override
    async def __stop__(self) -> None:
        self.__scheduler.stop()
        self.__scheduler = Scheduler()
        await asyncio.gather(
            self.__message_write_buffer.flush(),
            self.__alert_write_buffer.flush(),
        )
        if self.__local_environment is not None:
            await self.environment.database.dispose()

    class SubscribeEventsInput(ImmutableDataObject):
        kinds: str | FrozenSet[str] | None = None

    @query("events")
    async def get_events(
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
        procedure: str,
        input: object | None = None,
    ) -> Any:
        if (
            (binding := self.get_procedure_bindings().get(procedure)) is None
            or (method := getattr(self, binding.function, None)) is None
            or not inspect.ismethod(method)
        ):
            raise ProcedureException(ProcedureDoesNotExistError())

        arguments: list[object] = []
        if input is not None:
            arguments.append(input)

        try:
            pre_validate_arguments(method, *arguments)
        except ValidationError as error:
            raise ProcedureException(
                ProcedureInvalidInputError(problems=ValidationProblem.extract(error))
            )

        try:
            return await awaitify(validate_arguments(method)(*arguments))
        except Exception:
            raise ProcedureException(ProcedureInternalError(traceback=traceback.format_exc()))

    async def call(
        self,
        procedure: str,
        input: object | None = None,
    ) -> object | None:
        result = await self.__invoke(procedure, input)
        binding = self.get_procedure_bindings()[procedure]

        if not binding.live:
            return result

        try:
            match binding:
                # If the procedure is a live query, we just return the first output.
                case QueryBinding():
                    async for output in result:
                        return output

                    return None
                # If the procedure is a live action, iterate through all outputs and return the
                # last one.
                case ActionBinding():
                    last: object | None = None
                    async for output in result:
                        last = output
                    return last
        except Exception as exception:
            raise ProcedureException(
                ProcedureInternalError(traceback=traceback.format_exception(exception))
            )

    async def subscribe(
        self,
        procedure: str,
        input: object | None = None,
    ) -> AsyncIterable[object | None]:
        result = await self.__invoke(procedure, input)
        binding = self.get_procedure_bindings()[procedure]

        if not binding.live:
            if isinstance(binding, ActionBinding):
                raise ProcedureException(ProcedureNotSubscribableError())

            try:
                while True:
                    yield await self.__invoke(procedure, input)
                    await asyncio.sleep(binding.poll.total_seconds())
            except Exception as exception:
                self.logger.error(
                    f"An exception occurred in procedure '{procedure}': {traceback.format_exc()}"
                )
                raise ProcedureException(
                    ProcedureInternalError(traceback=traceback.format_exception(exception))
                )

        try:
            async for output in result:
                yield output
        except Exception as exception:
            self.logger.error(
                f"An exception occurred in procedure '{procedure}': {traceback.format_exc()}"
            )
            raise ProcedureException(
                ProcedureInternalError(traceback=traceback.format_exception(exception))
            )


@cached
def _get_listener_bindings(component_cls: type[Component]) -> Sequence[ListenerBinding]:
    return tuple(get_all_bindings(component_cls, ListenerBinding))


@cached
def _get_routine_bindings(component_cls: type[Component]) -> Sequence[RoutineBinding]:
    return tuple(get_all_bindings(component_cls, RoutineBinding))


_ProcedureBindingT = TypeVar("_ProcedureBindingT", bound=BaseProcedureBinding)


@cached
def _get_procedure_bindings(
    component_cls: type[_ComponentT],
    binding_cls: type[_ProcedureBindingT],
) -> Mapping[str, _ProcedureBindingT]:
    return MappingProxyType(
        {binding.name: binding for binding in get_all_bindings(component_cls, binding_cls)}
    )
