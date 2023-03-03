import asyncio
import inspect
import logging
import traceback
from dataclasses import field
from functools import partial
from logging import Logger
from string import ascii_lowercase
from types import MappingProxyType
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterable,
    Callable,
    Collection,
    Final,
    FrozenSet,
    Mapping,
    Sequence,
    TypeVar,
    final,
    get_origin,
)
from weakref import WeakValueDictionary, ref

from pydantic import (
    Field,
    ValidationError,
    parse_obj_as,
    root_validator,
    validate_arguments,
    validator,
)
from sqlalchemy.util import unique_list
from typing_extensions import Self, dataclass_transform, override

from .address import Address
from .alert import Alert, AlertLevel
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
from .internal.events import EventProcessor
from .internal.scheduler import Scheduler
from .internal.tasklet import Tasklet
from .internal.utilities import (
    awaitify,
    cached,
    get_model,
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
from .ref import RefType
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


class Job(ImmutableDataObject):
    name: Name
    action: Name
    input: Any = None
    schedule: Schedule = Field(discriminator="kind")
    enabled: bool = True

    @root_validator(pre=True)
    def _default_name_to_action(cls, values: dict[str, Any]) -> Any:
        if "name" not in values and "action" in values:
            values["name"] = values["action"]

        return values


@dataclass_transform(
    kw_only_default=True,
    field_specifiers=VALIDATED_DATACLASS_FIELD_SPECIFIERS,
)
class Component(ValidatedDataclass, Tasklet):
    def __init_subclass__(cls, **kwargs: Any) -> type[Any]:
        super().__init_subclass__(**kwargs)

        for binding in cls.get_listener_bindings():
            for source in binding.sources:
                if source == "self":
                    continue

                if not has_field(cls, source):
                    raise ComponentClassInvalidException(
                        f"event listener '{binding.function}' refers to reference '{source}' "
                        f"which is not defined as an attribute in {strify(cls)}"
                    )

        return cls

    name: Final[Name] = field(default_factory=lambda: randstr(ascii_lowercase, 8))
    paths: Final[ComponentPaths] = field(default_factory=ComponentPaths)
    jobs: Final[Sequence[Job]] = field(default_factory=list)

    @validator("jobs")
    def _validate_jobs(cls, jobs: Sequence[Job]) -> Sequence[Job]:
        seen: set[str] = set()

        for job in jobs:
            if job.name in seen:
                raise ValueError(f"duplicate job '{job.name}', give the job a unique 'name' value")

            seen.add(job.name)

        return jobs

    @validator("jobs", each_item=True)
    def _validate_job(cls, job: Job) -> Job:
        action = cls.get_action_bindings().get(job.action)
        if action is None:
            defined = sorted(cls.get_action_bindings().keys())
            raise ValueError(
                f"{strify(cls)} has no action named '{job.action}', defined actions are "
                f"{defined}"
            )

        if job.input is None and (action.input is not None and action.input.required):
            raise ValueError(
                f"missing required input for job '{job.name}', set the job's 'input' to a "
                "non-none value"
            )

        return job

    def __post_init_post_parse__(self) -> None:
        self.__local_environment: Environment | None = None
        self.__unit: ref[Unit] | None = None
        self.__events: Stream[Event] = Stream()
        self.__scheduler = Scheduler()
        self.__referencers: WeakValueDictionary[int, Component] = WeakValueDictionary()

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
            EventProcessor(
                binding=binding,
                handler=getattr(self, binding.function),
                logger=self.logger,
            )
            for binding in self.get_listener_bindings()
        ]

        self.__sync_referencers()
        self.__setup__()

    def __setup__(self) -> None:
        pass

    def __sync_referencers(self) -> None:
        referenced = self.get_referenced_components()
        for component in list(self.__referencers.values()):
            if component not in referenced:
                component.__referencers.pop(id(component))
        for component in referenced:
            component.__referencers[id(self)] = self

    def __infer_environment(self) -> Environment | None:
        if self.unit is not None:
            return self.unit.environment

        # TODO: We might want to do a topological sort here to pick the environment.
        for component in self.get_referenced_components():
            return component.environment

        return None

    @property
    def environment(self) -> Environment:
        inferred = self.__infer_environment()
        if inferred is not None:
            return inferred

        if self.__local_environment is None:
            self.__local_environment = Environment()

        return self.__local_environment

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

    def assign_referenced_components(
        self,
        references: Mapping[str, Self],
    ) -> ComponentReferenceInvalidError | None:
        def _create_reference_invalid_error(
            reference: Any,
            info: type[RefType],
        ) -> ComponentReferenceInvalidError:
            return ComponentReferenceInvalidError(
                message=(
                    f"reference to component '{reference}' of type {strify(info.cls)} is "
                    f"required and specified by {strify(type(self))}, but it hasn't loaded yet "
                    "failed to load"
                )
            )

        for name, info in self.__pydantic_model__.__fields__.items():
            outer_type = info.outer_type_
            inner_type = info.type_
            value: Any = getattr(self, name)

            if lenient_issubclass(outer_type, RefType):
                if lenient_isinstance(value, str):
                    component = references.get(value)
                else:
                    component = value

                if (
                    component is None
                    and not is_optional(outer_type)
                    and not is_optional(outer_type.cls)
                ):
                    return _create_reference_invalid_error(value, outer_type)

                object.__setattr__(self, name, component)
                continue

            if lenient_issubclass(inner_type, RefType) and lenient_issubclass(
                get_origin(outer_type) or outer_type, Collection
            ):
                collection = value

                if lenient_issubclass(inner_type, RefType):
                    components: list[Any] = []

                    for element in collection:
                        if isinstance(element, str):
                            component = references.get(element)
                        else:
                            component = element

                        if (
                            component is None
                            and not is_optional(inner_type)
                            and not is_optional(inner_type.cls)
                        ):
                            return _create_reference_invalid_error(element, inner_type)

                        components.append(component)

                    if callable(outer_type):
                        assigned = outer_type(components)
                    else:
                        assigned = parse_obj_as(outer_type, components)

                    object.__setattr__(self, name, assigned)

        self.__sync_referencers()

    def get_referenced_components(self, alias: str | None = None) -> Sequence["Component"]:
        components: list[Component] = []

        if alias is None:
            for alias in get_model(self).__fields__:
                components.extend(self.get_referenced_components(alias))
        else:
            reference = getattr(self, alias, None)
            if isinstance(reference, Component):
                components.append(reference)
            elif isinstance(reference, Collection):
                for component in reference:
                    if isinstance(component, Component):
                        components.append(component)

        return unique_list(components, id)

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
                    for component in self.get_referenced_components(alias)
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

        async def run(job: Job) -> None:
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
        if self.__infer_environment() is None:
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
                f"An exception occurred while running routine '{strify(binding.function)}': "
                f"{strify(traceback.format_exc())}"
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
