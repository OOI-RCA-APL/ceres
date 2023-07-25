import asyncio
import inspect
import traceback
from dataclasses import field
from datetime import datetime
from enum import Enum
from functools import partial
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
    Sequence,
    TypedDict,
    TypeVar,
    final,
    overload,
)
from uuid import UUID
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
from sqlalchemy import (
    BinaryExpression,
    ColumnElement,
    SQLColumnExpression,
    Text,
    cast,
    func,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.roles import ExpressionElementRole
from typing_extensions import Self, Unpack, dataclass_transform, override

from ceres.address import Address, AddressSelector, DynamicAddress
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
    jsonify,
)
from ceres.database import Database
from ceres.errors import (
    ComponentReferenceInvalidError,
    ProcedureDoesNotExistError,
    ProcedureInternalError,
    ProcedureInvalidArgsError,
    ProcedureNotSubscribableError,
)
from ceres.events import AlertEvent, DisabledEvent, EnabledEvent, Event
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
from ceres.internal.utilities import (
    awaitify,
    cached,
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
from ceres.logs import LogEntry
from ceres.message import Message, MessageDirection
from ceres.object import Object
from ceres.procedure import (
    ActionBinding,
    ProcedureBinding,
    QueryBinding,
)
from ceres.routine import RoutineBinding
from ceres.schedule import Schedule
from ceres.timing import utc
from ceres.validation import ValidationProblem

if TYPE_CHECKING:
    from ceres.server import Server
else:
    Server = object

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
    address: AddressSelector | None


class ObjectQuery(Generic[_ObjectT], Query):
    address: AddressSelector | None = None

    def matches(self, obj: _ObjectT, root: Address = Address.root()) -> bool:
        if not root.contains(obj.address):
            return False

        if self.address is not None:
            if not self.address.matches(obj.address, root):
                return False

        return True


class ComponentQueryArgs(ObjectQueryArgs, total=False):
    enabled: bool | None
    running: bool | None


class ComponentQuery(ObjectQuery["Component"]):
    enabled: bool | None = None
    running: bool | None = None

    @override
    def matches(self, obj: "Component", root: Address = Address.root()) -> bool:
        if not super().matches(obj, root):
            return False

        if self.enabled is not None and obj.enabled != self.enabled:
            return False

        if self.running is not None and obj.running != self.running:
            return False

        return True


class ComponentStatus(ImmutableDataObject):
    address: Address
    running: bool
    enabled: bool


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
    def matches(self, obj: Message, root: Address = Address.root()) -> bool:
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
    def matches(self, obj: Alert, root: Address = Address.root()) -> bool:
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
    def matches(self, obj: LogEntry, root: Address = Address.root()) -> bool:
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
    root: DynamicAddress | None
    within: PositiveTimeDelta | None
    after: DateTime | None
    before: DateTime | None


class StatisticsQuery(Query):
    root: DynamicAddress | None = None
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
class Component(Object):
    name: Final[Name] = Field(default_factory=lambda: randstr(ascii_lowercase, 8))
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
        super().__post_init_post_parse__()

        self.__parent: ref[Component] | None = None
        self.__scheduler = Scheduler()
        self.__referencers: WeakValueDictionary[int, Component] = WeakValueDictionary()
        self.__components: dict[Name, Component] = {}
        self.__config__: "ComponentConfig | None" = None
        self.__enabled = False
        self.__server: Server | None = None
        self.__database: Database | None = None
        self.__event_processors = [
            EventProcessor(
                binding=binding,
                handler=getattr(self, binding.function),
                log=self.log,
            )
            for binding in self.get_listener_bindings()
        ]

        self.__setup__()

    def __setup__(self) -> None:
        pass

    @property
    @override
    def __container__(self) -> Object | None:
        if self.parent is not None:
            return self.parent

        return self.server

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
    @override
    def address(self) -> Address:
        if self.parent is not None:
            return self.parent.address / self.name

        return Address("@")

    @property
    def enabled(self) -> bool:
        return self.__enabled

    @property
    def settled(self) -> bool:
        if not self.running:
            return True

        return super().settled and all(processor.idle for processor in self.__event_processors)

    async def settle(self) -> None:
        while not self.settled:
            await asyncio.gather(
                super().settle(),
                *(processor.wait_until_empty() for processor in self.__event_processors),
            )

    def handle_event(self, event: Event) -> None:
        from ceres.component import Component

        if not self.running or self.stopping:
            return

        for processor in self.__event_processors:
            if not lenient_isinstance(event, processor.binding.event_cls):
                continue

            for alias in processor.binding.sources:
                if (
                    alias == "self"
                    and self.address == event.address
                    or (
                        isinstance(self, Component)
                        and any(
                            component.address == event.address
                            for component in self.get_referencers(alias)
                        )
                    )
                ):
                    processor.put(event)
                    break

    async def enable(self) -> None:
        await self.__set_enabled_in_database(True)
        self.__enabled = True

    async def disable(self) -> None:
        await self.__set_enabled_in_database(False)
        self.__enabled = False

    async def up(self) -> None:
        await self.enable()
        self.start()

    async def down(self) -> None:
        await self.disable()
        await self.stop()

    async def __get_enabled_in_database(self) -> bool:
        async with await self.__init_database_session() as session:
            return (
                await session.scalar(
                    select(ComponentEntity.enabled).where(ComponentEntity.address == self.address)
                )
                or False
            )

    async def __set_enabled_in_database(self, enabled: bool) -> None:
        async with await self.__init_database_session() as session:
            await session.execute(
                update(ComponentEntity)
                .where(ComponentEntity.address == self.address)
                .values(enabled=enabled)
            )

            await session.commit()

        if enabled:
            self.emit(EnabledEvent)
        else:
            self.emit(DisabledEvent)

    @property
    @override
    def root(self) -> "Component":
        current: Component | None = self
        while current.parent is not None:
            current = current.parent

        return current

    @property
    def parent(self) -> "Component | None":
        if self.__parent is None:
            return None

        return self.__parent()

    @property
    @override
    def database(self) -> Database:
        if self.parent is not None:
            return self.parent.database
        if self.server is not None:
            return self.server.database
        if self.__database is None:
            self.__database = Database()

        return self.__database

    @property
    @override
    def server(self) -> "Server | None":
        if self.parent is not None:
            return self.parent.server
        if self.__server is not None:
            return self.__server

        return None

    @server.setter
    def server(self, server: Server) -> None:
        self.__server = server

    @property
    def scheduler(self) -> Scheduler:
        return self.__scheduler

    @property
    def components(self) -> "ComponentGroup":
        return ComponentGroup(self.__components.values())

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

    def get_referencers(self, alias: str | None = None) -> Sequence["Component"]:
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

        self.__components[component.name] = component
        component.detach()
        component.__parent = ref(self)  # type: ignore

        return component

    def detach(self) -> None:
        if self.parent is None:
            return

        self.parent.__components.pop(self.name, None)
        self.__parent = None

    def remove_component(self, address: str | DynamicAddress | None, /) -> "Component | None":
        component = self.get_component(address)
        if component is not None:
            component.detach()

        return component

    def get_component(self, address: str | DynamicAddress | None, /) -> "Component | None":
        if not address:
            return self

        if not isinstance(address, DynamicAddress):
            address = DynamicAddress(address)

        if address.is_absolute and self.parent is not None:
            return self.root.get_component(address)

        current: Component | None = self
        for name in address.names:
            if current is None:
                break

            current = current.__components.get(name)

        return current

    def get_components(
        self,
        __query: ComponentQuery | AddressSelector | None = None,
        /,
        *,
        inclusive: bool = False,
        **kwargs: Unpack[ComponentQueryArgs],
    ) -> "ComponentGroup":
        components: list[Component] = []

        query = ComponentQuery(**kwargs)
        if isinstance(__query, ComponentQuery):
            query = __query.with_defaults(query)
        elif isinstance(__query, AddressSelector):
            query = ComponentQuery(**{**query.dict(), "address": __query})  # type: ignore

        def traverse(current: Component) -> None:
            if (inclusive or current is not self) and query.matches(current, self.address):
                components.append(current)

            for component in current.__components.values():
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

        super().propagate(event)

        # Send the event to all components have a reference to this one.
        for referencer in self.__referencers.values():
            referencer.handle_event(event)

        return event

    def alert(
        self,
        level: Level,
        code: str,
        info: Mapping[str, Any] | None = None,
    ) -> Alert:
        alert = Alert(
            address=self.address,
            level=level,
            code=code,
            info=info if info is not None else {},
        )
        self.emit(AlertEvent, alert=alert)
        return alert

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

    def start(
        self,
        *,
        on_completed: Callable[[Self], None] | None = None,
        on_exception: Callable[[Self, BaseException], None] | None = None,
    ) -> None:
        for component in reversed(self.get_ancestors()):
            component.start()

        super().start(
            on_completed=on_completed,
            on_exception=on_exception,
        )

    @override
    async def __run__(self) -> None:
        await self.sync_with_database()

        self.__start_scheduler()

        await asyncio.gather(
            super().__run__(),
            self.__process_events(),
            self.__process_routines(),
        )

    async def __process_events(self) -> None:
        await asyncio.gather(*(processor.run() for processor in self.__event_processors))

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

    @override
    async def __stop__(self) -> None:
        for component in reversed(self.components):
            self.log.info(f"Stopping '{component.address}'...")
            await component.stop()

        self.__scheduler.stop()
        self.__scheduler = Scheduler()
        await self.flush()
        if self.__database is not None:
            await self.__database.dispose()
            self.__database = None

        await super().__stop__()

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

    async def sync_with_database(self) -> UUID:
        id = await self.get_id(self.address)
        self.__enabled = await self.__get_enabled_in_database()
        return id

    async def __get_ids(self, query: ComponentQuery) -> list[UUID]:
        return [
            await self.get_id(component.address)
            for component in self.get_components(query, inclusive=True)
        ]

    async def get_status(self) -> ComponentStatus:
        return ComponentStatus(
            address=self.address,
            running=self.running,
            enabled=self.enabled,
        )

    async def get_statuses(
        self,
        query: ComponentQuery | None = None,
        **kwargs: Unpack[ComponentQueryArgs],
    ) -> list[ComponentStatus]:
        if query is not None:
            query = query.with_defaults(ComponentQuery(**kwargs))
        else:
            query = ComponentQuery(**kwargs)

        return [
            await component.get_status() for component in self.get_components(query, inclusive=True)
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

        ids = await self.__get_ids(ComponentQuery(address=query.address))
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

        async with await self.__init_database_session() as session:
            rows = await session.execute(statement)

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

        ids = await self.__get_ids(ComponentQuery(address=query.address))
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

        ids = await self.__get_ids(ComponentQuery(address=query.address))
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

        root = self.address if query.root is None else self.address / query.root
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


@cached
def _get_listener_bindings(cls: type[Object]) -> Sequence[ListenerBinding]:
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
    expression: SQLColumnExpression[Any],
    pattern: str | bytes,
    case_sensitive: bool = False,
) -> BinaryExpression[bool]:
    if case_sensitive:
        return expression.like(pattern)
    return expression.ilike(pattern)


def _format_timestamp(timestamp: datetime) -> str:
    return timestamp.strftime("%Y-%m-%d %H:%M:%f")[:-3]


def _sqlite_format_timestamp(timestamp: SQLColumnExpression[datetime]) -> Any:
    return func.strftime("%Y-%m-%d %H:%M:%f", func.julianday(timestamp))


def _pg_format_timestamp(timestamp: SQLColumnExpression[datetime]) -> Any:
    return func.to_char(timestamp, "YYYY-MM-DD HH24:MI:SS.MS")


def _address_contains(
    self: Address,
    other: SQLColumnExpression[Address],
) -> bool | SQLColumnExpression[bool]:
    if self.is_server:
        return True

    return (other == self) | ((other != "~") & (other.like(f"{self}.%") | (self.is_root)))


class ComponentGroup(Sequence[Component]):
    def __init__(self, components: Iterable[Component]):
        self.components = tuple(uniquify(components, key=lambda component: component.address))

    @overload
    def __getitem__(self, __index: int) -> Component:
        ...

    @overload
    def __getitem__(self, __index: slice) -> Self:
        ...

    def __getitem__(self, __index: int | slice) -> "Component | Self":  # type: ignore
        value = self.components[__index]
        if isinstance(value, tuple):
            return type(self)(value)

        return value

    def __len__(self) -> int:
        return len(self.components)

    def __iter__(self) -> Iterator[Component]:
        return iter(self.components)

    def __contains__(self, __object: object) -> bool:
        return __object in self.components

    def reversed(self) -> Self:
        return type(self)(reversed(self.components))

    def start(self) -> None:
        for component in self.components:
            component.start()

    async def stop(self) -> None:
        for component in reversed(self.components):
            await component.stop()

    async def enable(self) -> None:
        for component in self.components:
            await component.enable()

    async def disable(self) -> None:
        for component in reversed(self.components):
            await component.disable()

    async def up(self) -> None:
        for component in self.components:
            await component.up()

    async def down(self) -> None:
        for component in reversed(self.components):
            await component.down()

    def __or__(self, __other: "ComponentGroup") -> Self:
        return type(self)(uniquify((*self.components, *__other.components)))
