import asyncio
import inspect
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
    Final,
    Mapping,
    ParamSpec,
    Sequence,
    TypeVar,
    final,
)
from weakref import WeakValueDictionary, ref

from pydantic import (
    ConfigDict,
    Extra,
    Field,
    ValidationError,
    root_validator,
    validate_arguments,
    validator,
)
from pydantic.decorator import ValidatedFunction
from typing_extensions import Self, dataclass_transform, override

from ceres.address import Address
from ceres.alert import Alert
from ceres.data import (
    VALIDATED_DATACLASS_FIELD_SPECIFIERS,
    ImmutableDataObject,
    Name,
    ValidatedDataclass,
)
from ceres.directory import Directory
from ceres.environment import Environment
from ceres.errors import (
    ComponentReferenceInvalidError,
    ProcedureDoesNotExistError,
    ProcedureInternalError,
    ProcedureInvalidArgsError,
    ProcedureNotSubscribableError,
)
from ceres.events import (
    AlertEmittedEvent,
    Event,
    MessageReceivedEvent,
    MessageSentEvent,
    StartedEvent,
    StoppedEvent,
)
from ceres.exceptions import ComponentClassInvalidException, ProcedureException
from ceres.internal import logs
from ceres.internal.binding import get_bindings
from ceres.internal.database.buffer import WriteBuffer
from ceres.internal.database.entities import AlertEntity, MessageEntity
from ceres.internal.events import EventProcessor
from ceres.internal.scheduler import Scheduler
from ceres.internal.tasklet import Tasklet
from ceres.internal.utilities import (
    awaitify,
    cached,
    has_field,
    lenient_isinstance,
    randstr,
    sleep_forever,
    strify,
    traverse,
)
from ceres.listener import ListenerBinding
from ceres.message import Message
from ceres.procedure import (
    ActionBinding,
    ProcedureBinding,
    QueryBinding,
)
from ceres.routine import RoutineBinding, routine
from ceres.schedule import Schedule
from ceres.stream import Stream, StreamView
from ceres.validation import ValidationProblem

if TYPE_CHECKING:
    from ceres.engine import Engine
    from ceres.unit import Unit
else:
    Engine = "Engine"
    Unit = "Unit"

_ComponentT = TypeVar("_ComponentT", bound="Component")
_EventT = TypeVar("_EventT", bound=Event)
_EventP = ParamSpec("_EventP")


class ComponentPaths(ImmutableDataObject):
    data: Directory = Field(default_factory=Directory)
    local: Directory = Field(default_factory=Directory)


class Job(ImmutableDataObject):
    name: Name
    action: Name
    args: Mapping[Name, Any] | None = None
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

        if not job.args and (action.args is not None and action.args.required):
            raise ValueError(
                f"missing required arguments for job '{job.name}', add arguments to the job's "
                "'args' value"
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
        for referencer in list(self.__referencers.values()):
            if id(self) not in {id(other) for other in referencer.get_referenced_components()}:
                self.__referencers.pop(id(referencer))

        referenced = self.get_referenced_components()
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
        return {
            name: binding
            for name, binding in cls.get_procedure_bindings().items()
            if isinstance(binding, QueryBinding)
        }

    @final
    @classmethod
    def get_action_bindings(cls) -> Mapping[str, ActionBinding]:
        return {
            name: binding
            for name, binding in cls.get_procedure_bindings().items()
            if isinstance(binding, ActionBinding)
        }

    @final
    @classmethod
    def get_procedure_bindings(cls) -> Mapping[str, ProcedureBinding]:
        return _get_procedure_bindings(cls)

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

    def unref(self) -> Self:
        return self

    def assign_references(
        self,
        components: Mapping[str, Self],
    ) -> ComponentReferenceInvalidError | None:
        from ceres.ref import get_references

        for reference in get_references(self):
            component = components.get(reference.__component_name__)
            if component is None:
                return ComponentReferenceInvalidError(
                    message=(
                        f"reference to component '{reference}' of type "
                        f"{strify(reference.__component_cls__)} is required and specified by "
                        f"{strify(type(self))}, but it hasn't loaded yet or failed to load"
                    )
                )

            reference.__component_instance__ = component

        self.__sync_referencers()

    def get_referenced_components(self, alias: str | None = None) -> Sequence["Component"]:
        components: list[Component] = []

        if alias is None:
            root = self
        else:
            root = getattr(self, alias, None)

        if root is None:
            return components

        def visit(obj: Any) -> bool:
            if lenient_isinstance(obj, Component):
                obj = obj.unref()
                if obj is not self:
                    components.append(obj)
                    return False

            return True

        traverse(root, visit)
        return components

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

    def emit_event(
        self,
        event_cls: Callable[_EventP, _EventT],
        /,
        *args: _EventP.args,
        **kwargs: _EventP.kwargs,
    ) -> _EventT:
        if "source" not in kwargs:
            kwargs["source"] = self.address

        return self.emit_event_instance(event_cls(*args, **kwargs))

    def emit_event_instance(self, event: _EventT) -> _EventT:
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
                await self.call(job.action, job.args)
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
        self.emit_event(StartedEvent)

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
            await self.__message_write_buffer.flush()
            await asyncio.sleep(0.1)

    @routine
    async def __flush_alert_buffer(self) -> None:
        while True:
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

    @override
    async def __done__(self) -> None:
        self.emit_event(StoppedEvent)

    async def __invoke(
        self,
        procedure: str,
        args: Mapping[Name, Any] | None = None,
    ) -> Any:
        if args is None:
            args = {}

        if (
            (binding := self.get_procedure_bindings().get(procedure)) is None
            or (method := getattr(self, binding.function, None)) is None
            or not inspect.ismethod(method)
        ):
            raise ProcedureException(ProcedureDoesNotExistError())

        config: Any = ConfigDict(
            allow_population_by_field_name=True,
            arbitrary_types_allowed=True,
            extra=Extra.forbid,
        )

        try:
            ValidatedFunction(method, config).init_model_instance(**args)
        except ValidationError as error:
            raise ProcedureException(
                ProcedureInvalidArgsError(problems=ValidationProblem.extract(error))
            )

        try:
            return await awaitify(validate_arguments(config=config)(method)(**args))
        except Exception:
            raise ProcedureException(ProcedureInternalError(traceback=traceback.format_exc()))

    async def call(
        self,
        procedure: str,
        args: Mapping[Name, Any] | None = None,
    ) -> object | None:
        result = await self.__invoke(procedure, args)
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
        args: Mapping[Name, Any] | None = None,
    ) -> AsyncIterable[object | None]:
        result = await self.__invoke(procedure, args)
        binding = self.get_procedure_bindings()[procedure]

        if not binding.live:
            if isinstance(binding, ActionBinding):
                raise ProcedureException(ProcedureNotSubscribableError())

            try:
                while True:
                    yield await self.__invoke(procedure, args)
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
def _get_listener_bindings(cls: type[Component]) -> Sequence[ListenerBinding]:
    return get_bindings(cls, ListenerBinding)


@cached
def _get_routine_bindings(cls: type[Component]) -> Sequence[RoutineBinding]:
    return get_bindings(cls, RoutineBinding)


@cached
def _get_procedure_bindings(cls: type[_ComponentT]) -> Mapping[Name, ProcedureBinding]:
    return MappingProxyType(
        {
            binding.name: binding
            for binding in sorted(
                get_bindings(cls, ProcedureBinding),
                key=lambda current: current.name,
            )
        }
    )
