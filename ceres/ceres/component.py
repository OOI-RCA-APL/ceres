import asyncio
import inspect
import traceback
from dataclasses import field
from functools import partial
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
    AlertEvent,
    Event,
    LogEvent,
    MessageReceivedEvent,
    MessageSentEvent,
    StartedEvent,
    StoppedEvent,
)
from ceres.exceptions import ProcedureException
from ceres.internal.binding import get_bindings
from ceres.internal.events import EventProcessor
from ceres.internal.scheduler import Scheduler
from ceres.internal.tasklet import Tasklet
from ceres.internal.utilities import (
    awaitify,
    cached,
    lenient_isinstance,
    randstr,
    strify,
    traverse,
)
from ceres.listener import ListenerBinding
from ceres.logs import Log, LogEntry
from ceres.procedure import (
    ActionBinding,
    ProcedureBinding,
    QueryBinding,
)
from ceres.routine import RoutineBinding
from ceres.schedule import Schedule
from ceres.stream import Stream, WriteStream
from ceres.validation import ValidationProblem

if TYPE_CHECKING:
    from ceres.engine import Engine
else:
    Engine = "Engine"
    Unit = "Unit"

_ComponentT = TypeVar("_ComponentT", bound="Component")
_EventT = TypeVar("_EventT", bound=Event)
_EventP = ParamSpec("_EventP")


class Paths(ImmutableDataObject):
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
    name: Final[Name] = Field(default_factory=lambda: randstr(ascii_lowercase, 8))
    paths: Final[Paths] = field(default_factory=Paths)
    jobs: Final[Sequence[Job]] = field(default_factory=list)

    @validator("jobs")
    def _validate_jobs(cls, jobs: Sequence[Job]) -> Sequence[Job]:
        seen: set[str] = set()

        for job in jobs:
            if job.name in seen:
                raise ValueError(f"duplicate job '{job.name}', give the job a unique 'name' value")

            seen.add(job.name)

        return jobs

    def __post_init_post_parse__(self) -> None:
        self.__environment: Environment | None = None
        self.__parent: ref[Component] | None = None
        self.__events: WriteStream[Event] = WriteStream()
        self.__scheduler = Scheduler()
        self.__referencers: WeakValueDictionary[int, Component] = WeakValueDictionary()
        self.__log = Log(lambda: self.address)
        self.__log.add_handler(self.__handle_log_entry)
        self.__children: dict[Name, Component] = {}

        self.__event_processors = [
            EventProcessor(
                binding=binding,
                handler=getattr(self, binding.function),
                log=self.log,
            )
            for binding in self.get_listener_bindings()
        ]

        self.__sync_referencers()
        self.__setup__()

    def bind(self, environment: Environment) -> None:
        self.__environment = environment

    def __setup__(self) -> None:
        pass

    def __handle_log_entry(self, entry: LogEntry) -> None:
        self.emit(LogEvent, entry=entry)

    def __sync_referencers(self) -> None:
        for referencer in list(self.__referencers.values()):
            if id(self) not in {id(other) for other in referencer.get_referencers()}:
                self.__referencers.pop(id(referencer))

        referenced = self.get_referencers()
        for component in referenced:
            component.__referencers[id(self)] = self

    def infer_environment(self) -> Environment | None:
        if self.parent is not None:
            return self.parent.environment

        # TODO: We might want to do a topological sort here to pick the environment.
        for component in self.get_referencers():
            return component.environment

        return None

    @property
    def environment(self) -> Environment:
        inferred = self.infer_environment()
        if inferred is not None:
            return inferred

        if self.__environment is None:
            self.__environment = Environment()

        return self.__environment

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
        if self.parent is not None:
            return self.parent.address / self.name

        return Address(self.name)

    @property
    def engine(self) -> "Engine | None":
        if self.parent is None:
            return None

        from ceres.engine import Engine

        if isinstance(self.parent, Engine):
            return self.parent

        return self.parent.engine

    @property
    def parent(self) -> "Component | None":
        if self.__parent is None:
            return None

        return self.__parent()

    @property
    def scheduler(self) -> Scheduler:
        return self.__scheduler

    @property
    def log(self) -> Log:
        return self.__log

    @property
    def events(self) -> Stream[Event]:
        return self.__events.view()

    @property
    def children(self) -> Sequence[Self]:
        return list(self.__children.values())

    @property
    def settled(self) -> bool:
        return not self.running or (
            all(processor.idle for processor in self.__event_processors)
            and self.environment.settled
        )

    async def settle(self) -> None:
        while not self.settled:
            await asyncio.gather(
                *(processor.wait_until_empty() for processor in self.__event_processors),
                self.environment.settle(),
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

    def get_referencers(self, alias: str | None = None) -> Sequence[Self]:
        components: list[Component] = []
        root = self

        if alias is not None:
            for segment in alias.split("."):
                root = getattr(root, segment, None)
                if root is None:
                    break

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

    def add_child(self, child: "Component", name: Name | None = None) -> None:
        if child is self:
            return

        current = self.get_child(child.name)
        if current is child:
            return
        if current is not None:
            self.remove_child(current)

        if name is not None:
            child.name = name  # type: ignore

        self.__children[child.name] = child
        child.attach_to(self)

    def remove_child(self, child: "Component") -> None:
        if child is self:
            return

        if self.get_child(child.name) is not child:
            return

        self.__children.pop(child.name, None)
        if child.parent is self:
            child.detach()

    def get_child(self, name: Name) -> "Component | None":
        return self.__children.get(name)

    def get_component(self, address: Address | None = None) -> "Component | None":
        if not address or not address.head:
            return self

        child = self.get_child(address.head)
        if child is None:
            return None

        return child.get_component(address.tail)

    def attach_to(self, parent: "Component") -> None:
        if self.parent is parent:
            return

        if self.parent is not None:
            self.detach()

        self.__parent = ref(parent)

    def detach(self) -> None:
        if self.parent is None:
            return

        self.parent.remove_child(self)
        self.__parent = None

    def emit(
        self,
        event_cls: Callable[_EventP, _EventT],
        /,
        *args: _EventP.args,
        **kwargs: _EventP.kwargs,
    ) -> _EventT:
        if "source" not in kwargs:
            kwargs["source"] = self.address

        event = event_cls(*args, **kwargs)
        match event:
            case MessageSentEvent() | MessageReceivedEvent():
                self.environment.add(event.message)
            case AlertEvent():
                self.environment.add(event.alert)
            case LogEvent():
                self.environment.add(event.entry)
            case _:
                pass

        return self.propagate(event)

    def propagate(self, event: _EventT) -> _EventT:
        # Handle "self" events.
        self.handle_event(event)
        # Send the event to all components have a reference to this one.
        for referencer in self.__referencers.values():
            referencer.handle_event(event)
        # Add the event to the outgoing event stream.
        self.__events.put(event)
        # Pass the event up to the containing unit if it exists.
        if self.parent is not None:
            self.parent.propagate(event)

        return event

    def handle_event(self, event: Event) -> None:
        if not self.running or self.stopping:
            return

        for processor in self.__event_processors:
            if not lenient_isinstance(event, processor.binding.event_cls):
                continue

            for alias in processor.binding.sources:
                if (alias == "self" and self.address == event.source) or any(
                    component.address == event.source for component in self.get_referencers(alias)
                ):
                    processor.put(event)
                    break

    def schedule_job(
        self,
        function: Callable[[], Any],
        schedule: Schedule,
        name: str | None = None,
    ) -> None:
        self.__scheduler.schedule(function, schedule, name=name)

    def unschedule_job(self, name: str | Callable[[], Any]) -> None:
        self.__scheduler.unschedule(name)

    def __start_scheduler(self) -> None:
        self.__scheduler.start()

        async def run(job: Job) -> None:
            self.log.info(f"Running job '{job.name}'...")
            try:
                await self.call(job.action, job.args)
            except ProcedureException as exception:
                self.log.error(
                    f"An error occurred while running job '{job.name}': {strify(exception.error)}"
                )

        for job in self.jobs:
            self.log.info(f"Scheduling job '{job.name}' on {job.schedule}.")
            self.schedule_job(partial(run, job), job.schedule, name=job.name)

    @override
    async def __run__(self) -> None:
        if self.infer_environment() is None:
            await self.environment.database.init()
            await self.environment.assign_component_id(self.address)

        self.__start_scheduler()
        self.emit(StartedEvent)

        await asyncio.gather(
            self.__process_routines(),
            self.__process_events(),
            self.__process_environment(),
        )

    async def __process_routine(self, binding: RoutineBinding) -> None:
        routine = getattr(self, binding.function, None)
        if routine is None:
            return

        try:
            await routine()
        except Exception:
            self.log.error(
                f"An exception occurred while running routine '{strify(binding.function)}': "
                f"{strify(traceback.format_exc())}"
            )

    async def __process_routines(self) -> None:
        await asyncio.gather(
            *(self.__process_routine(binding) for binding in self.get_routine_bindings())
        )

    async def __process_events(self) -> None:
        await asyncio.gather(*(processor.run() for processor in self.__event_processors))

    async def __process_environment(self) -> None:
        while True:
            if self.__environment is not None:
                await self.__environment.flush()
            await asyncio.sleep(0.1)

    @override
    async def __stop__(self) -> None:
        self.__scheduler.stop()
        self.__scheduler = Scheduler()
        if self.__environment is not None:
            await self.__environment.flush()
            await self.__environment.database.dispose()

    @override
    async def __done__(self) -> None:
        self.emit(StoppedEvent)

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
        except Exception as exception:
            raise ProcedureException(
                ProcedureInternalError(traceback=traceback.format_exception(exception))
            )

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
                self.log.error(
                    f"An exception occurred in procedure '{procedure}': {traceback.format_exc()}"
                )
                raise ProcedureException(
                    ProcedureInternalError(traceback=traceback.format_exception(exception))
                )

        try:
            async for output in result:
                yield output
        except Exception as exception:
            self.log.error(
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
