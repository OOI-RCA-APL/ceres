import asyncio
import inspect
import traceback
from asyncio import Event as AsyncEvent
from asyncio import Lock as AsyncLock
from collections.abc import Sequence
from dataclasses import field
from datetime import datetime
from enum import Enum
from functools import partial
from itertools import groupby
from string import ascii_lowercase
from types import MappingProxyType
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterable,
    Callable,
    Final,
    Generic,
    Iterable,
    Iterator,
    Mapping,
    ParamSpec,
    Protocol,
    SupportsIndex,
    TypedDict,
    TypeVar,
    final,
)
from uuid import UUID, uuid4
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
from sqlalchemy import BinaryExpression, ColumnElement, Text, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import SQLCoreOperations
from sqlalchemy.sql.roles import ExpressionElementRole
from typing_extensions import Self, Unpack, dataclass_transform, override

from ceres.address import Address, AddressPattern
from ceres.alert import Alert
from ceres.config import ComponentConfig, DatabaseKind
from ceres.data import (
    VALIDATED_DATACLASS_FIELD_SPECIFIERS,
    BytesPattern,
    DataObject,
    DateTime,
    ImmutableDataObject,
    Name,
    PositiveTimeDelta,
    StrPattern,
    ValidatedDataclass,
    jsonify,
)
from ceres.database import Database
from ceres.directory import Directory
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
from ceres.internal.database.entities import (
    AlertEntity,
    ComponentEntity,
    LogEntryEntity,
    MessageEntity,
)
from ceres.internal.events import EventProcessor
from ceres.internal.scheduler import Scheduler
from ceres.internal.tasklet import Tasklet
from ceres.internal.utilities import (
    awaitify,
    cached,
    chunkify,
    dictify,
    escape_like_expression,
    lenient_isinstance,
    randstr,
    setattr_internal,
    strify,
    traverse,
    uniquify,
)
from ceres.level import Level
from ceres.listener import ListenerBinding
from ceres.logs import Log, LogEntry
from ceres.message import Message, MessageDirection
from ceres.procedure import (
    ActionBinding,
    ProcedureBinding,
    QueryBinding,
)
from ceres.routine import RoutineBinding
from ceres.schedule import Schedule
from ceres.stream import Stream, WriteStream
from ceres.timing import utc
from ceres.validation import ValidationProblem

if TYPE_CHECKING:
    from ceres.engine import Engine
else:
    Engine = "Engine"

_ComponentT = TypeVar("_ComponentT", bound="Component")
_EventT = TypeVar("_EventT", bound=Event)
_EventP = ParamSpec("_EventP")

WhereExpression = ColumnElement[bool] | ExpressionElementRole[bool]
OrderByExpression = ColumnElement[Any] | ExpressionElementRole[Any]


class Query(ImmutableDataObject):
    class Config(ImmutableDataObject.Config):
        extra = Extra.ignore

    def with_defaults(self, defaults: Self) -> Self:
        update: dict[str, Any] = {}

        for attribute in self.__fields__:
            current = getattr(self, attribute, None)
            if current is not None:
                continue
            default = getattr(defaults, attribute, None)
            if default is None:
                continue

            update[attribute] = default

        return self.copy(update=update)


class Addressable(Protocol):
    @property
    def address(self) -> Address:
        ...


_ObjectT = TypeVar("_ObjectT", bound=Addressable)


class ObjectQueryArgs(TypedDict, total=False):
    address: AddressPattern | None


class ObjectQuery(Generic[_ObjectT], Query):
    address: AddressPattern | None = None

    def matches(self, obj: _ObjectT, root: "Address") -> bool:
        if not root.contains(obj.address):
            return False

        if self.address is not None:
            if not self.address.matches(obj.address, root):
                return False

        return True


class ComponentQueryArgs(ObjectQueryArgs, total=False):
    pass


class ComponentQuery(ObjectQuery["Component"]):
    pass


class MessageOrder(str, Enum):
    OLD_TO_NEW = "old-to-new"
    NEW_TO_OLD = "new-to-old"


class MessageQueryArgs(ObjectQueryArgs, total=False):
    search: str | None
    search_case_sensitive: bool
    within: PositiveTimeDelta | None
    after: DateTime | None
    before: DateTime | None
    direction: MessageDirection | None
    prefix: bytes | None
    suffix: bytes | None
    regex: BytesPattern | None
    order: MessageOrder | None
    limit: int | None
    offset: int | None


class MessageQuery(ObjectQuery[Message]):
    search: str | None = None
    search_case_sensitive: bool = False
    within: PositiveTimeDelta | None = None
    after: DateTime | None = None
    before: DateTime | None = None
    direction: MessageDirection | None = None
    prefix: bytes | None = None
    suffix: bytes | None = None
    regex: BytesPattern | None = None
    order: MessageOrder | None = None
    limit: int | None = Field(default=None, ge=0)
    offset: int | None = Field(default=None, ge=0)

    @override
    def matches(self, obj: Message, root: Address) -> bool:
        if not super().matches(obj, root):
            return False

        if self.search is not None:
            search = self.search
            timestamp = _format_timestamp(obj.timestamp)
            direction = obj.direction
            content = obj.content

            if not self.search_case_sensitive:
                search = search.lower()
                content = content.lower()

            if not (search in timestamp or search.encode() in content or search in direction):
                return False

        if self.within is not None:
            if obj.timestamp < utc() - self.within:
                return False
        if self.after is not None:
            if obj.timestamp < self.after:
                return False
        if self.before is not None:
            if obj.timestamp >= self.before:
                return False

        if self.direction is not None:
            if obj.direction != self.direction:
                return False

        if self.prefix is not None:
            if not obj.content.startswith(self.prefix):
                return False
        if self.suffix is not None:
            if not obj.content.endswith(self.suffix):
                return False
        if self.regex is not None:
            if not self.regex.match(obj.content):
                return False

        return True


class AlertOrder(str, Enum):
    OLD_TO_NEW = "old-to-new"
    NEW_TO_OLD = "new-to-old"


class AlertQueryArgs(TypedDict, total=False):
    search: str | None
    search_case_sensitive: bool
    within: PositiveTimeDelta | None
    after: DateTime | None
    before: DateTime | None
    level: Level | Sequence[Level] | None
    code: str | Sequence[str] | None
    code_regex: StrPattern | None
    order: AlertOrder | None
    limit: int | None
    offset: int | None


class AlertQuery(ObjectQuery[Alert]):
    search: str | None = None
    search_case_sensitive: bool = False
    within: PositiveTimeDelta | None = None
    after: DateTime | None = None
    before: DateTime | None = None
    level: Level | Sequence[Level] | None = None
    code: str | Sequence[str] | None = None
    code_regex: StrPattern | None = None
    order: AlertOrder | None = None
    limit: int | None = Field(default=None, ge=0)
    offset: int | None = Field(default=None, ge=0)

    @override
    def matches(self, obj: Alert, root: Address) -> bool:
        if not super().matches(obj, root):
            return False

        if self.search is not None:
            search = self.search
            timestamp = _format_timestamp(obj.timestamp)
            level = obj.level
            code = obj.code
            info = jsonify(obj.info)

            if self.search_case_sensitive:
                search = search.lower()
                code = code.lower()
                info = info.lower()

            if not (search in timestamp or search in level or search in code or search in info):
                return False

        if self.within is not None:
            if obj.timestamp < utc() - self.within:
                return False
        if self.after is not None:
            if obj.timestamp < self.after:
                return False
        if self.before is not None:
            if obj.timestamp >= self.before:
                return False

        if self.level is not None:
            if isinstance(self.level, Level):
                if obj.level != self.level:
                    return False
            else:
                if obj.level not in self.level:
                    return False

        if self.code is not None:
            if isinstance(self.code, str):
                if obj.code != self.code:
                    return False
            else:
                if obj.code not in self.code:
                    return False

        if self.code_regex is not None:
            if not self.code_regex.match(obj.code):
                return False

        return True


class LogEntryOrder(str, Enum):
    OLD_TO_NEW = "old-to-new"
    NEW_TO_OLD = "new-to-old"


class LogEntryQueryArgs(TypedDict, total=False):
    search: str | None
    search_case_sensitive: bool
    within: PositiveTimeDelta | None
    after: DateTime | None
    before: DateTime | None
    level: Level | Sequence[Level] | None
    prefix: str | None
    suffix: str | None
    regex: StrPattern | None
    order: LogEntryOrder | None
    limit: int | None
    offset: int | None


class LogEntryQuery(ObjectQuery[LogEntry]):
    search: str | None = None
    search_case_sensitive: bool = False
    within: PositiveTimeDelta | None = None
    after: DateTime | None = None
    before: DateTime | None = None
    level: Level | Sequence[Level] | None = None
    prefix: str | None = None
    suffix: str | None = None
    regex: StrPattern | None = None
    order: LogEntryOrder | None = None
    limit: int | None = Field(default=None, ge=0)
    offset: int | None = Field(default=None, ge=0)

    @override
    def matches(self, obj: LogEntry, root: Address) -> bool:
        if not super().matches(obj, root):
            return False

        if self.search is not None:
            search = self.search
            timestamp = _format_timestamp(obj.timestamp)
            level = obj.level
            content = obj.content

            if not self.search_case_sensitive:
                search = search.lower()
                content = content.lower()

            if not (search in timestamp or search in level or search in content):
                return False

        if self.within is not None:
            if obj.timestamp < utc() - self.within:
                return False
        if self.after is not None:
            if obj.timestamp < self.after:
                return False
        if self.before is not None:
            if obj.timestamp >= self.before:
                return False

        if self.prefix is not None:
            if not obj.content.startswith(self.prefix):
                return False
        if self.suffix is not None:
            if not obj.content.endswith(self.suffix):
                return False
        if self.regex is not None:
            if not self.regex.match(obj.content):
                return False

        return True


class StatisticsQueryArgs(TypedDict, total=False):
    root: Address | None
    within: PositiveTimeDelta | None
    after: DateTime | None
    before: DateTime | None


class StatisticsQuery(Query):
    root: Address | None = None
    within: PositiveTimeDelta | None = None
    after: DateTime | None = None
    before: DateTime | None = None


class LevelStatistics(DataObject):
    level: Level
    count: int = Field(ge=0)


class AlertStatistics(DataObject):
    count: int = 0
    levels: list[LevelStatistics] = Field(default_factory=list)


class Statistics(DataObject):
    address: Address
    alerts: AlertStatistics = Field(default_factory=AlertStatistics)


Item = Message | Alert | LogEntry


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
        self.__parent: ref[Component] | None = None
        self.__events: WriteStream[Event] = WriteStream()
        self.__scheduler = Scheduler()
        self.__referencers: WeakValueDictionary[int, Component] = WeakValueDictionary()
        self.__log = Log(lambda: self.address)
        self.__log.add_handler(self.__handle_log_entry)
        self.__children: dict[Name, Component] = {}
        self.__config__: "ComponentConfig | None" = None

        self.__event_processors = [
            EventProcessor(
                binding=binding,
                handler=getattr(self, binding.function),
                log=self.log,
            )
            for binding in self.get_listener_bindings()
        ]

        self.__database: Database | None = None
        self.__mapping: dict[Address, UUID] | None = None
        self.__mapping_lock = AsyncLock()
        self.__flushing = False
        self.__buffer: list[Item] = []
        self.__buffer_empty = AsyncEvent()
        self.__buffer_empty.set()

        self.__sync_referencers()
        self.__setup__()

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
    def root(self) -> "Component":
        current: Component | None = self
        while current.parent is not None:
            current = current.parent

        return current

    @property
    def engine(self) -> "Engine | None":
        from ceres.engine import Engine

        current: Component | None = self
        while current.parent is not None:
            current = current.parent
            if isinstance(current, Engine):
                return current

        return None

    @property
    def parent(self) -> "Component | None":
        if self.__parent is None:
            return None

        return self.__parent()

    @property
    def database(self) -> Database:
        if self.parent is not None:
            return self.parent.database

        if self.__database is None:
            self.__database = Database()

        return self.__database

    @property
    def local_database(self) -> Database | None:
        return self.__database

    @local_database.setter
    def local_database(self, database: Database) -> None:
        self.__database = database

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
    def children(self) -> Sequence["Component"]:
        return list(self.__children.values())

    @property
    def settled(self) -> bool:
        return not self.running or (all(processor.idle for processor in self.__event_processors))

    async def settle(self) -> None:
        while not self.settled:
            await asyncio.gather(
                *(processor.wait_until_empty() for processor in self.__event_processors),
                self.__buffer_empty.wait(),
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

    def add_component(
        self,
        component: _ComponentT,
        /,
        name: Name | None = None,
    ) -> _ComponentT:
        if component is self or component in self.get_ancestors():
            raise ValueError("component cannot contain itself")

        if isinstance(name, str):
            setattr_internal(Component, component, "name", name)

        self.__children[component.name] = component
        component.detach()
        component.__parent = ref(self)

        return component

    def detach(self) -> None:
        if self.parent is None:
            return

        self.parent.__children.pop(self.name, None)
        self.__parent = None

    def remove_component(self, /, address: Name | Address | None) -> "Component | None":
        component = self.get_component(address)
        if component is not None:
            component.detach()

        return component

    def get_component(self, address: Name | Address | None, /) -> "Component | None":
        if not address:
            return self

        address = Address(address)

        current: Component | None = self
        for name in address.path:
            if current is None:
                break

            current = current.__children.get(name)

        return current

    def get_components(
        self,
        /,
        __query: ComponentQuery | AddressPattern | None = None,
        *,
        inclusive: bool = False,
        **kwargs: Unpack[ComponentQueryArgs],
    ) -> "ComponentGroup":
        components: list[Component] = []

        query = ComponentQuery(**kwargs)
        if isinstance(__query, ComponentQuery):
            query = __query.with_defaults(query)
        elif isinstance(__query, AddressPattern):
            query = ComponentQuery(**{**query.dict(), "address": __query})

        def traverse(current: Component) -> None:
            if (inclusive or current is not self) and query.matches(current, self.address):
                components.append(current)

            for component in current.__children.values():
                traverse(component)

        traverse(self)

        return ComponentGroup(components)

    def get_ancestors(self, *, inclusive: bool = False) -> "ComponentGroup":
        ancestors: list[Component] = []

        current: Component | None = self if inclusive else self.parent
        while current is not None:
            ancestors.append(current)
            current = current.parent

        return ComponentGroup(ancestors)

    def emit(
        self,
        event_cls: Callable[_EventP, _EventT],
        /,
        *args: _EventP.args,
        **kwargs: _EventP.kwargs,
    ) -> _EventT:
        if "address" not in kwargs:
            kwargs["address"] = self.address

        return self.propagate(event_cls(*args, **kwargs))

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
        else:
            # Otherwise, store any related items in the database.
            match event:
                case MessageSentEvent() | MessageReceivedEvent():
                    self.store(event.message)
                case AlertEvent():
                    self.store(event.alert)
                case LogEvent():
                    self.store(event.entry)
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
                if (alias == "self" and self.address == event.address) or any(
                    component.address == event.address for component in self.get_referencers(alias)
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
        if self.address:
            await self.root.assign_component_id(self.address)

        self.__start_scheduler()
        self.emit(StartedEvent)

        await asyncio.gather(
            self.__process_flush(),
            self.__process_routines(),
            self.__process_events(),
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

    async def __process_flush(self) -> None:
        while True:
            await self.flush()
            await asyncio.sleep(0.1)

    async def __process_routines(self) -> None:
        await asyncio.gather(
            *(self.__process_routine(binding) for binding in self.get_routine_bindings())
        )

    async def __process_events(self) -> None:
        await asyncio.gather(*(processor.run() for processor in self.__event_processors))

    @override
    async def __stop__(self) -> None:
        for component in reversed(self.children):
            self.log.info(f"Stopping '{component.address}'...")
            await component.stop()

        self.__scheduler.stop()
        self.__scheduler = Scheduler()
        await self.flush()
        if self.__database is not None:
            await self.__database.dispose()
            self.__database = None

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

    async def __init_database_session(self) -> AsyncSession:
        await self.database.init()
        return self.database.session()

    async def assign_component_id(
        self,
        address: Address,
        default: UUID | None = None,
    ) -> UUID:
        if self.__mapping is not None:
            id = self.__mapping.get(address)
            if id is not None:
                return id

        async with await self.__init_database_session() as session:
            mapping = await self.__get_or_load_mapping(session)
            id = mapping.get(address)
            if id is not None:
                return id

            if id is None:
                id = await session.scalar(
                    select(ComponentEntity.id).where(ComponentEntity.address == address),
                )

            if id is None:
                id = default or uuid4()
                component = ComponentEntity(id=id, address=address)

                session.add(component)
                await session.commit()

            mapping[address] = id
            return id

    def store(self, item: Item) -> None:
        if not isinstance(item, Item):
            raise TypeError(f"unsupported item type: {type(item)}")

        self.__buffer.append(item)
        self.__buffer_empty.clear()

    async def flush(self) -> None:
        if self.__flushing or not self.__buffer:
            return
        if not self.__buffer:
            return

        self.__flushing = True

        try:
            async with await self.__init_database_session() as session:
                buffer = self.__buffer
                self.__buffer = []

                match self.database.kind:
                    case DatabaseKind.SQLITE:
                        from sqlalchemy.dialects.sqlite import insert

                        chunk_size = 500

                    case DatabaseKind.POSTGRES:
                        from sqlalchemy.dialects.postgresql import insert  # noqa

                        chunk_size = 1000

                for model_cls, models in groupby(buffer, type):
                    if issubclass(model_cls, Message):
                        entity_cls = MessageEntity
                    elif issubclass(model_cls, Alert):
                        entity_cls = AlertEntity
                    elif issubclass(model_cls, LogEntry):
                        entity_cls = LogEntryEntity
                    else:
                        continue

                    for chunk in chunkify(models, chunk_size):
                        values: list[dict[str, Any]] = []

                        for model in chunk:
                            data = dictify(model)
                            data.pop("address", None)
                            data["component_id"] = await self.assign_component_id(model.address)
                            values.append(data)

                        await session.execute(insert(entity_cls).on_conflict_do_nothing(), values)

                await session.commit()
        except Exception:
            traceback.print_exc()
        finally:
            self.__flushing = False
            if not self.__buffer:
                self.__buffer_empty.set()

    async def __get_component_ids(self, query: ComponentQuery) -> list[UUID]:
        return [
            await self.assign_component_id(component.address)
            for component in self.get_components(query)
        ]

    async def get_messages(
        self,
        query: MessageQuery | None = None,
        *,
        where: Callable[[type[MessageEntity]], WhereExpression] | None = None,
        order_by: Callable[[type[MessageEntity]], OrderByExpression] | None = None,
        **kwargs: Unpack[MessageQueryArgs],
    ) -> list[Message]:
        if query is not None:
            query = query.with_defaults(MessageQuery(**kwargs))
        else:
            query = MessageQuery(**kwargs)

        ids = await self.__get_component_ids(ComponentQuery(address=query.address))
        statement = (
            select(
                MessageEntity.id,
                ComponentEntity.address,
                MessageEntity.timestamp,
                MessageEntity.direction,
                MessageEntity.content,
            )
            .join(ComponentEntity)
            .where(MessageEntity.component_id.in_(ids))
        )

        if query.search is not None:
            pattern = "%" + escape_like_expression(query.search) + "%"
            match self.database.kind:
                case DatabaseKind.SQLITE:
                    statement = statement.where(
                        _like(
                            _sqlite_format_timestamp(MessageEntity.timestamp),
                            pattern,
                            query.search_case_sensitive,
                        )
                        | _like(MessageEntity.direction, pattern, query.search_case_sensitive)
                        | _like(
                            MessageEntity.content,
                            pattern.encode("utf-8"),
                            query.search_case_sensitive,
                        ),
                    )
                case DatabaseKind.POSTGRES:
                    statement = statement.where(
                        _like(
                            _pg_format_timestamp(MessageEntity.timestamp),
                            pattern,
                            query.search_case_sensitive,
                        )
                        | _like(MessageEntity.direction, pattern, query.search_case_sensitive)
                        | _like(
                            func.encode(MessageEntity.content, "escape"),
                            pattern.encode("utf-8").decode("unicode-escape"),
                            query.search_case_sensitive,
                        ),
                    )

        if query.within is not None:
            statement = statement.where(MessageEntity.timestamp >= utc() - query.within)
        if query.after is not None:
            statement = statement.where(MessageEntity.timestamp >= query.after)
        if query.before is not None:
            statement = statement.where(MessageEntity.timestamp < query.before)
        if query.direction is not None:
            statement = statement.where(MessageEntity.direction == query.direction)
        if query.prefix is not None:
            statement = statement.where(
                MessageEntity.content.like(escape_like_expression(query.prefix) + b"%"),
            )
        if query.suffix is not None:
            statement = statement.where(
                MessageEntity.content.like(b"%" + escape_like_expression(query.suffix)),
            )

        if query.order is not None:
            match query.order:
                case MessageOrder.OLD_TO_NEW:
                    statement = statement.order_by(MessageEntity.timestamp)
                case MessageOrder.NEW_TO_OLD:
                    statement = statement.order_by(MessageEntity.timestamp.desc())

        if query.limit is not None:
            statement = statement.limit(query.limit)
        if query.offset is not None and query.offset > 0:
            statement = statement.offset(query.offset)

        if where is not None:
            statement = statement.where(where(MessageEntity))
        if order_by is not None:
            statement = statement.order_by(order_by(MessageEntity))

        if query.order is None and order_by is None:
            statement = statement.order_by(MessageEntity.timestamp)

        start = utc()
        async with await self.__init_database_session() as session:
            rows = await session.execute(statement)
        print("\n\n\nget_messages\n\n\n", utc() - start)

        return [Message.construct(**row._asdict()) for row in rows]  # type: ignore

    async def get_message(
        self,
        query: MessageQuery | None = None,
        *,
        where: Callable[[type[MessageEntity]], WhereExpression] | None = None,
        order_by: Callable[[type[MessageEntity]], OrderByExpression] | None = None,
        **kwargs: Unpack[MessageQueryArgs],
    ) -> Message | None:
        messages = await self.get_messages(
            query,
            where=where,
            order_by=order_by,
            **{**kwargs, "limit": 1},
        )

        return messages[0] if messages else None

    async def get_alerts(
        self,
        query: AlertQuery | None = None,
        *,
        where: Callable[[type[AlertEntity]], WhereExpression] | None = None,
        order_by: Callable[[type[AlertEntity]], OrderByExpression] | None = None,
        **kwargs: Unpack[AlertQueryArgs],
    ) -> list[Alert]:
        if query is not None:
            query = query.with_defaults(AlertQuery(**kwargs))
        else:
            query = AlertQuery(**kwargs)

        ids = await self.__get_component_ids(ComponentQuery(address=query.address))
        statement = (
            select(
                AlertEntity.id,
                ComponentEntity.address,
                AlertEntity.timestamp,
                AlertEntity.level,
                AlertEntity.code,
                AlertEntity.info,
            )
            .join(ComponentEntity)
            .where(ComponentEntity.id.in_(ids))
        )

        if query.search is not None:
            pattern = "%" + escape_like_expression(query.search) + "%"
            match self.database.kind:
                case DatabaseKind.SQLITE:
                    statement = statement.where(
                        _like(
                            _sqlite_format_timestamp(AlertEntity.timestamp),
                            pattern,
                            query.search_case_sensitive,
                        )
                        | _like(AlertEntity.level, pattern, query.search_case_sensitive)
                        | _like(AlertEntity.code, pattern, query.search_case_sensitive)
                        | _like(AlertEntity.info, pattern, query.search_case_sensitive),
                    )
                case DatabaseKind.POSTGRES:
                    statement = statement.where(
                        _like(
                            _pg_format_timestamp(AlertEntity.timestamp),
                            pattern,
                            query.search_case_sensitive,
                        )
                        | _like(AlertEntity.level, pattern, query.search_case_sensitive)
                        | _like(AlertEntity.code, pattern, query.search_case_sensitive)
                        | _like(cast(AlertEntity.info, Text), pattern, query.search_case_sensitive),
                    )

        if query.within is not None:
            statement = statement.where(AlertEntity.timestamp >= utc() - query.within)
        if query.after is not None:
            statement = statement.where(AlertEntity.timestamp >= query.after)
        if query.before is not None:
            statement = statement.where(AlertEntity.timestamp < query.before)
        if query.level is not None:
            if isinstance(query.level, Level):
                statement = statement.where(AlertEntity.level == query.level)
            else:
                statement = statement.where(AlertEntity.level.in_(query.level))
        if query.code is not None:
            if isinstance(query.code, str):
                statement = statement.where(AlertEntity.code == query.code)
            else:
                statement = statement.where(AlertEntity.code.in_(query.code))
        if query.code_regex is not None:
            statement = statement.where(AlertEntity.code.regexp_match(query.code_regex))

        if query.order is not None:
            match query.order:
                case AlertOrder.OLD_TO_NEW:
                    statement = statement.order_by(AlertEntity.timestamp)
                case AlertOrder.NEW_TO_OLD:
                    statement = statement.order_by(AlertEntity.timestamp.desc())
        elif order_by is None:
            statement = statement.order_by(AlertEntity.timestamp)

        if query.limit is not None:
            statement = statement.limit(query.limit)
        if query.offset is not None and query.offset > 0:
            statement = statement.offset(query.offset)

        if where is not None:
            statement = statement.where(where(AlertEntity))
        if order_by is not None:
            statement = statement.order_by(order_by(AlertEntity))

        if query.order is None and order_by is None:
            statement = statement.order_by(AlertEntity.timestamp)

        async with await self.__init_database_session() as session:
            rows = await session.execute(statement)

        return [Alert.construct(**row._asdict()) for row in rows]  # type: ignore

    async def get_alert(
        self,
        query: AlertQuery | None = None,
        *,
        where: Callable[[type[AlertEntity]], WhereExpression] | None = None,
        order_by: Callable[[type[AlertEntity]], OrderByExpression] | None = None,
        **kwargs: Unpack[AlertQueryArgs],
    ) -> Alert | None:
        alerts = await self.get_alerts(
            query,
            where=where,
            order_by=order_by,
            **{**kwargs, "limit": 1},
        )

        return alerts[0] if alerts else None

    async def get_log_entries(
        self,
        query: LogEntryQuery | None = None,
        *,
        where: Callable[[type[LogEntryEntity]], WhereExpression] | None = None,
        order_by: Callable[[type[LogEntryEntity]], OrderByExpression] | None = None,
        **kwargs: Unpack[LogEntryQueryArgs],
    ) -> list[LogEntry]:
        if query is not None:
            query = query.with_defaults(LogEntryQuery(**kwargs))
        else:
            query = LogEntryQuery(**kwargs)

        ids = await self.__get_component_ids(ComponentQuery(address=query.address))
        statement = (
            select(
                LogEntryEntity.id,
                ComponentEntity.address,
                LogEntryEntity.timestamp,
                LogEntryEntity.level,
                LogEntryEntity.content,
            )
            .join(ComponentEntity)
            .where(ComponentEntity.id.in_(ids))
        )

        if query.search is not None:
            pattern = "%" + escape_like_expression(query.search) + "%"
            match self.database.kind:
                case DatabaseKind.SQLITE:
                    statement = statement.where(
                        _like(
                            _sqlite_format_timestamp(LogEntryEntity.timestamp),
                            pattern,
                            query.search_case_sensitive,
                        )
                        | _like(LogEntryEntity.level, pattern, query.search_case_sensitive)
                        | _like(
                            LogEntryEntity.content,
                            pattern,
                            query.search_case_sensitive,
                        ),
                    )
                case DatabaseKind.POSTGRES:
                    statement = statement.where(
                        _like(
                            _pg_format_timestamp(LogEntryEntity.timestamp),
                            pattern,
                            query.search_case_sensitive,
                        )
                        | _like(LogEntryEntity.level, pattern, query.search_case_sensitive)
                        | _like(
                            LogEntryEntity.content,
                            pattern,
                            query.search_case_sensitive,
                        ),
                    )

        if query.within is not None:
            statement = statement.where(LogEntryEntity.timestamp >= utc() - query.within)
        if query.after is not None:
            statement = statement.where(LogEntryEntity.timestamp >= query.after)
        if query.before is not None:
            statement = statement.where(LogEntryEntity.timestamp < query.before)
        if query.level is not None:
            if isinstance(query.level, Level):
                statement = statement.where(LogEntryEntity.level == query.level)
            else:
                statement = statement.where(LogEntryEntity.level.in_(query.level))
        if query.prefix is not None:
            statement = statement.where(
                LogEntryEntity.content.like(escape_like_expression(query.prefix) + "%"),
            )
        if query.suffix is not None:
            statement = statement.where(
                LogEntryEntity.content.like("%" + escape_like_expression(query.suffix)),
            )

        if query.order is not None:
            match query.order:
                case LogEntryOrder.OLD_TO_NEW:
                    statement = statement.order_by(LogEntryEntity.timestamp)
                case LogEntryOrder.NEW_TO_OLD:
                    statement = statement.order_by(LogEntryEntity.timestamp.desc())

        if query.limit is not None:
            statement = statement.limit(query.limit)
        if query.offset is not None and query.offset > 0:
            statement = statement.offset(query.offset)

        if where is not None:
            statement = statement.where(where(LogEntryEntity))
        if order_by is not None:
            statement = statement.order_by(order_by(LogEntryEntity))

        if query.order is None and order_by is None:
            statement = statement.order_by(LogEntryEntity.timestamp)

        async with await self.__init_database_session() as session:
            rows = await session.execute(statement)

        return [LogEntry.construct(**row._asdict()) for row in rows]  # type: ignore

    async def get_log_entry(
        self,
        query: LogEntryQuery | None = None,
        *,
        where: Callable[[type[LogEntryEntity]], WhereExpression] | None = None,
        order_by: Callable[[type[LogEntryEntity]], OrderByExpression] | None = None,
        **kwargs: Unpack[LogEntryQueryArgs],
    ) -> LogEntry | None:
        alerts = await self.get_log_entries(
            query,
            where=where,
            order_by=order_by,
            **{**kwargs, "limit": 1},
        )

        return alerts[0] if alerts else None

    async def get_statistics(
        self,
        query: StatisticsQuery | None = None,
        **kwargs: Unpack[StatisticsQueryArgs],
    ) -> list[Statistics]:
        if self.parent is not None:
            kwargs = {"root": self.address, **kwargs}

        if query is not None:
            query = query.with_defaults(StatisticsQuery(**kwargs))
        else:
            query = StatisticsQuery(**kwargs)

        if self.parent is not None:
            return await self.root.get_statistics(query, **kwargs)

        if query is not None:
            query = query.with_defaults(StatisticsQuery(**kwargs))
        else:
            query = StatisticsQuery(**kwargs)

        root = query.root or self.address
        addresses = [component.address for component in self.get_components()]

        statement = (
            select(ComponentEntity.address, AlertEntity.level, func.count("*"))
            .where(
                AlertEntity.address.in_(addresses)
                & (_address_contains(root, ComponentEntity.address))
            )
            .join(ComponentEntity)
            .group_by(ComponentEntity.address, AlertEntity.level)
        )

        if query.within is not None:
            statement = statement.where(AlertEntity.timestamp >= utc() - query.within)
        if query.after is not None:
            statement = statement.where(AlertEntity.timestamp >= query.after)
        if query.before is not None:
            statement = statement.where(AlertEntity.timestamp < query.before)

        results: dict[Address, Statistics] = {}

        async with self.database.session() as session:
            for address, level, count in await session.execute(statement):
                address: Address
                for ancestor in address.path:
                    if not root.contains(ancestor):
                        continue

                    current = results.setdefault(ancestor, Statistics(address=ancestor))
                    current.alerts.count += count
                    for entry in current.alerts.levels:
                        if entry.level == level:
                            entry.count += count
                            break
                    else:
                        current.alerts.levels.append(LevelStatistics(level=level, count=count))
                        current.alerts.levels.sort(key=lambda entry: entry.level)

        return list(results.values())

    async def __generate_mapping(self, session: AsyncSession) -> dict[Address, UUID]:
        return dict(
            tuple(row)
            for row in await session.execute(
                select(ComponentEntity.address, ComponentEntity.id),
            )
        )

    async def __get_or_load_mapping(self, session: AsyncSession) -> dict[Address, UUID]:
        async with self.__mapping_lock:
            if self.__mapping is None:
                self.__mapping = await self.__generate_mapping(session)

        return self.__mapping


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


def _like(
    expression: SQLCoreOperations[Any],
    pattern: str | bytes,
    case_sensitive: bool = False,
) -> BinaryExpression[bool]:
    if case_sensitive:
        return expression.like(pattern)
    return expression.ilike(pattern)


def _format_timestamp(timestamp: datetime) -> str:
    return timestamp.strftime("%Y-%m-%d %H:%M:%f")[:-3]


def _sqlite_format_timestamp(timestamp: SQLCoreOperations[datetime]) -> Any:
    return func.strftime(
        "%Y-%m-%d %H:%M:%f",
        func.julianday(timestamp),
    )


def _pg_format_timestamp(timestamp: SQLCoreOperations[datetime]) -> Any:
    return func.to_char(timestamp, "YYYY-MM-DD HH24:MI:SS.MS")


def _address_contains(root: Address, expression: SQLCoreOperations[Address]) -> Any:
    return (func.length(root) == 0) | (expression == root) | expression.like(f"{root}.%")


class ComponentGroup(Sequence[Component]):
    def __init__(self, components: Iterable[Component]):
        self.components = tuple(uniquify(components, key=lambda component: component.address))

    def __getitem__(self, __index: SupportsIndex) -> Component:
        return self.components[__index]

    def __len__(self) -> int:
        return len(self.components)

    def __iter__(self) -> Iterator[Component]:
        return iter(self.components)

    def __contains__(self, __object: object) -> bool:
        return __object in self.components

    def reversed(self) -> Self:
        return self.__class__(reversed(self.components))

    def start(self) -> None:
        for component in self.components:
            component.start()

    async def stop(self) -> None:
        for component in reversed(self.components):
            await component.stop()

    def __or__(self, __other: "ComponentGroup") -> Self:
        return self.__class__(uniquify((*self.components, *__other.components)))
