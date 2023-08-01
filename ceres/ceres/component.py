import asyncio
import inspect
import traceback
from asyncio import Queue as AsyncQueue
from dataclasses import field
from datetime import timedelta
from enum import Enum
from functools import partial
from inspect import Parameter
from string import ascii_lowercase
from types import MappingProxyType, UnionType
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterable,
    Awaitable,
    Callable,
    Final,
    Iterable,
    Iterator,
    Literal,
    Mapping,
    ParamSpec,
    Protocol,
    Sequence,
    TypeVar,
    final,
    get_type_hints,
    runtime_checkable,
)
from uuid import UUID
from weakref import WeakValueDictionary, ref

from pydantic import (
    BaseModel,
    ConfigDict,
    Extra,
    Field,
    ValidationError,
    root_validator,
    schema_of,
    validate_arguments,
    validator,
)
from pydantic.decorator import ValidatedFunction
from pydantic.typing import get_args
from sqlalchemy import (
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession
from typing_extensions import Self, Unpack, dataclass_transform, overload, override

from ceres.address import Address, AddressSelector, DynamicAddress
from ceres.alert import Alert
from ceres.config import ComponentConfig
from ceres.data import (
    VALIDATED_DATACLASS_FIELD_SPECIFIERS,
    ImmutableDataObject,
    Name,
    PositiveTimeDelta,
)
from ceres.database import Database
from ceres.errors import (
    ProcedureDoesNotExistError,
    ProcedureInternalError,
    ProcedureInvalidArgsError,
    ProcedureNotSubscribableError,
)
from ceres.events import AlertEvent, DisabledEvent, EnabledEvent, Event
from ceres.exceptions import ProcedureException
from ceres.filter import ComponentFilter, ComponentFilterArgs
from ceres.internal.database.entities import ComponentEntity
from ceres.internal.scheduler import Scheduler
from ceres.internal.utilities import (
    awaitify,
    cached,
    get_function_name,
    get_inner_function,
    lenient_isinstance,
    randstr,
    setattr_internal,
    strify,
    traverse,
    uniquify,
)
from ceres.level import Level
from ceres.logs import LogEntry
from ceres.message import Message
from ceres.object import Object, Status
from ceres.schedule import Schedule
from ceres.validation import ValidationProblem

if TYPE_CHECKING:
    from ceres.ref import Reference
    from ceres.server import Server
else:
    Server = object
    Reference = object

_ComponentT = TypeVar("_ComponentT", bound="Component")
_EventT = TypeVar("_EventT", bound=Event)
_EventP = ParamSpec("_EventP")


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
        self.__listeners = [
            _Listener(
                component=self,
                binding=binding,
                handler=getattr(self, binding.function),
            )
            for binding in self.get_listener_bindings()
        ]

        self.sync_component_references()
        self.__setup__()

    def __setup__(self) -> None:
        pass

    @property
    @override
    def __container__(self) -> Object | None:
        if self.parent is not None:
            return self.parent

        return self.server

    @property
    @override
    def __contained__(self) -> Sequence[Object]:
        return list(self.get_components())

    @final
    @classmethod
    def get_listener_bindings(cls) -> Sequence["ListenerBinding"]:
        return _get_listener_bindings(cls)

    @final
    @classmethod
    def get_routine_bindings(cls) -> Sequence["RoutineBinding"]:
        return _get_routine_bindings(cls)

    @final
    @classmethod
    def get_query_bindings(cls) -> Mapping[str, "QueryBinding"]:
        return {
            name: binding
            for name, binding in cls.get_procedure_bindings().items()
            if isinstance(binding, QueryBinding)
        }

    @final
    @classmethod
    def get_action_bindings(cls) -> Mapping[str, "ActionBinding"]:
        return {
            name: binding
            for name, binding in cls.get_procedure_bindings().items()
            if isinstance(binding, ActionBinding)
        }

    @final
    @classmethod
    def get_procedure_bindings(cls) -> Mapping[str, "ProcedureBinding"]:
        return _get_procedure_bindings(cls)

    @property
    @override
    def address(self) -> Address:
        if self.parent is not None:
            return self.parent.address / self.name

        return Address.root()

    @property
    def enabled(self) -> bool:
        return self.__enabled

    @property
    @override
    def settled(self) -> bool:
        if not self.running:
            return True

        return super().settled and all(processor.idle for processor in self.__listeners)

    @override
    async def settle(self) -> None:
        while not self.settled:
            await asyncio.gather(
                super().settle(),
                *(listener.settle() for listener in self.__listeners),
            )

    @override
    def handle(self, event: Event) -> None:
        super().handle(event)

        if not self.running or self.stopping:
            return

        for listener in self.__listeners:
            listener.handle(event)

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
            enabled = await session.scalar(
                select(ComponentEntity.enabled).where(ComponentEntity.address == self.address)
            )

            if enabled is None:
                return False

            return enabled

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
    @final
    def root(self) -> "Component":
        current: Component | None = self
        while current.parent is not None:
            current = current.parent

        return current

    @property
    @final
    def parent(self) -> "Component | None":
        if self.__parent is None:
            return None

        return self.__parent()

    @property
    @override
    @final
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
    @final
    def server(self) -> Server | None:
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

    def sync_component_references(self) -> tuple[list[Reference], list[Reference]]:
        resolved: list[Reference] = []
        unresolved: list[Reference] = []

        for reference in self.get_component_references():
            reference.__reference_root__ = self

            if reference.__reference_component__ is not None:
                resolved.append(reference)
            else:
                unresolved.append(reference)

        for referencer in list(self.__referencers.values()):
            if id(self) not in {
                id(other.unref()) for other in referencer.get_component_references()
            }:
                self.__referencers.pop(id(referencer))

        for component in self.get_referenced_components():
            component.__referencers[id(self)] = self

        return resolved, unresolved

    def get_component_references(self) -> list[Reference]:
        from ceres.ref import Reference

        references: list[Reference] = []

        def visit(obj: Any) -> bool:
            if isinstance(obj, Reference):
                references.append(obj)
                return False

            return True

        traverse(self, visit)
        return references

    def get_referenced_components(self, alias: str | None = None) -> "ComponentGroup":
        components: list[Component] = []
        root = self

        if alias is not None:
            for segment in alias.split("."):
                root = getattr(root, segment, None)
                if root is None:
                    break

        if root is None:
            return ComponentGroup(components)

        def visit(obj: Any) -> bool:
            if lenient_isinstance(obj, Component):
                obj = obj.unref()
                if obj is not self:
                    components.append(obj)
                    return False

            return True

        traverse(root, visit)
        return ComponentGroup(components)

    def add_component(
        self,
        component: _ComponentT,
        /,
        name: Name | None = None,
    ) -> _ComponentT:
        if component is self or component in self.get_ancestor_components():
            raise ValueError("component cannot contain itself")

        if isinstance(name, str):
            setattr_internal(Component, component, "name", name)

        self.__components[component.name] = component
        component.remove_component()
        component.__parent = ref(self)  # type: ignore
        component.sync_component_references()

        return component

    def remove_component(self, address: str | DynamicAddress | None = None) -> "Component | None":
        if address is None:
            if self.parent is not None:
                removed = self.parent.__components.pop(self.name, None)
                self.__parent = None
                if removed is not None:
                    removed.sync_component_references()

            return

        component = self.get_component(address)
        if component is not None:
            component.remove_component()

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

    @override
    def get_components(
        self,
        filter: ComponentFilter | AddressSelector | None = None,
        /,
        *,
        inclusive: bool = False,
        **kwargs: Unpack[ComponentFilterArgs],
    ) -> "ComponentGroup":
        components: list[Component] = []

        overrides = ComponentFilter(**kwargs)
        if isinstance(filter, ComponentFilter):
            filter = filter.with_overrides(overrides)
        elif isinstance(filter, AddressSelector):
            filter = ComponentFilter(**{**overrides.dict(), "address": filter})  # type: ignore
        else:
            filter = overrides

        def traverse(current: Component) -> None:
            if (inclusive or current is not self) and filter.matches(current, self.address):
                components.append(current)

            for component in current.__components.values():
                traverse(component)

        traverse(self)

        return ComponentGroup(components)

    @overload
    async def get_status(self, address: str | DynamicAddress) -> Status | None:
        ...

    @overload
    async def get_status(self, address: None = None) -> Status:
        ...

    async def get_status(self, address: str | DynamicAddress | None = None) -> Status | None:
        if address is None:
            return Status(
                address=self.address,
                running=self.running,
                enabled=self.enabled,
            )

        return await super().get_status(address)

    def get_ancestor_components(self, *, inclusive: bool = False) -> "ComponentGroup":
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
        super().propagate(event)

        for referencer in self.__referencers.values():
            if referencer.root is not self.root:
                referencer.handle(event)

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
        for component in reversed(self.get_ancestor_components()):
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
        await asyncio.gather(*(processor.run() for processor in self.__listeners))

    async def __process_routine(self, binding: "RoutineBinding") -> None:
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


@cached
def _get_listener_bindings(cls: type[Component]) -> Sequence["ListenerBinding"]:
    return get_bindings(cls, ListenerBinding)


@cached
def _get_routine_bindings(cls: type[Component]) -> Sequence["RoutineBinding"]:
    return get_bindings(cls, RoutineBinding)


@cached
def _get_procedure_bindings(cls: type[_ComponentT]) -> Mapping[Name, "ProcedureBinding"]:
    queries = get_bindings(cls, QueryBinding)
    actions = get_bindings(cls, ActionBinding)
    procedures = sorted([*queries, *actions], key=lambda current: current.name)

    return MappingProxyType({binding.name: binding for binding in procedures})


class ComponentGroup(Sequence[Component]):
    __slots__ = (
        "__components",
        "__identities",
    )

    def __init__(self, components: Iterable[Component]):
        self.__components = tuple(uniquify(components, key=lambda component: component.address))
        self.__identities: set[int] | None = None

    def __repr__(self) -> str:
        return f"{type(self).__name__}({repr(list(self.__components))})"

    def __str__(self) -> str:
        return repr(self)

    @overload
    def __getitem__(self, __index: int) -> Component:
        ...

    @overload
    def __getitem__(self, __index: slice) -> Self:
        ...

    def __getitem__(self, __index: int | slice) -> "Component | Self":  # type: ignore
        value = self.__components[__index]
        if isinstance(value, tuple):
            return type(self)(value)

        return value

    def __len__(self) -> int:
        return len(self.__components)

    def __iter__(self) -> Iterator[Component]:
        return iter(self.__components)

    def __contains__(self, other: object) -> bool:
        if self.__identities is None:
            self.__identities = {id(component.unref()) for component in self.__components}

        if isinstance(other, Component):
            other = other.unref()

        return id(other) in self.__identities

    def reversed(self) -> Self:
        return type(self)(reversed(self.__components))

    def start(self) -> None:
        for component in self.__components:
            component.start()

    async def stop(self) -> None:
        for component in reversed(self.__components):
            await component.stop()

    async def enable(self) -> None:
        for component in self.__components:
            await component.enable()

    async def disable(self) -> None:
        for component in reversed(self.__components):
            await component.disable()

    async def up(self) -> None:
        for component in self.__components:
            await component.up()

    async def down(self) -> None:
        for component in reversed(self.__components):
            await component.down()

    def __or__(self, __other: "ComponentGroup") -> Self:
        return type(self)(uniquify((*self.__components, *__other.__components)))


class ListenerBinding(ImmutableDataObject):
    name: Name
    function: Name
    event: type | UnionType
    self: bool
    reference: Sequence[str]
    address: AddressSelector | None


_ListenerReturn = None | Awaitable[None]
_ListenerFunctionT = TypeVar(
    "_ListenerFunctionT",
    bound=Callable[[Any], _ListenerReturn] | Callable[[Any, Any], _ListenerReturn],
)


@overload
def on(function: _ListenerFunctionT) -> _ListenerFunctionT:
    ...


@overload
def on(
    *,
    event: type | UnionType | None = None,
    self: bool = False,
    reference: str | Sequence[str] = "self",
    address: str | AddressSelector | Sequence[str | AddressSelector] | None = None,
) -> Callable[[_ListenerFunctionT], _ListenerFunctionT]:
    ...


@validate_arguments(config={"arbitrary_types_allowed": True})
def on(
    function: _ListenerFunctionT | None = None,
    *,
    event: type | UnionType | None = None,
    self: bool = False,
    reference: str | Sequence[str] | None = None,
    address: str | AddressSelector | Sequence[str | AddressSelector] | None = None,
) -> _ListenerFunctionT | Callable[[_ListenerFunctionT], _ListenerFunctionT]:
    if reference is None:
        reference = []
    if isinstance(reference, str):
        reference = [reference]

    if address is not None:
        if isinstance(address, (str, DynamicAddress)):
            address = [address]

        address = AddressSelector("|".join(str(current) for current in address))

    def on(
        function: Callable[[Any], _ListenerReturn] | Callable[[Any, _EventT], _ListenerReturn]
    ) -> Any:
        signature = inspect.signature(function)

        assigned_event_type = event

        if assigned_event_type is None:
            hints = get_type_hints(function)
            parameters = list(signature.parameters.values())
            if len(parameters) > 1:
                event_parameter = parameters[1]
                assigned_event_type = hints.get(event_parameter.name)

        if assigned_event_type is None:
            assigned_event_type = Event

        _bind(
            function,
            ListenerBinding(
                name=_get_bound_name(function),
                function=get_function_name(function),
                reference=tuple(reference),
                address=address,
                self=self,
                event=assigned_event_type,
            ),
        )

        return function

    if function is None:
        return on

    return on(function)


class ProcedureKind(str, Enum):
    QUERY = "query"
    ACTION = "action"


class ProcedureSchemas(ImmutableDataObject):
    args: Mapping[str, Any] | None
    output: Mapping[str, Any]


class ProcedureArgsInfo(ImmutableDataObject):
    json_schema: Mapping[str, Any]
    required: bool


class ProcedureOutputInfo(ImmutableDataObject):
    json_schema: Mapping[str, Any]


class _ProcedureBinding(ImmutableDataObject):
    name: str
    kind: ProcedureKind
    function: str
    live: bool
    args: ProcedureArgsInfo | None
    output: ProcedureOutputInfo


class QueryBinding(_ProcedureBinding):
    kind: Literal[ProcedureKind.QUERY] = ProcedureKind.QUERY
    poll: PositiveTimeDelta = timedelta(seconds=1)


class ActionBinding(_ProcedureBinding):
    kind: Literal[ProcedureKind.ACTION] = ProcedureKind.ACTION


ProcedureBinding = QueryBinding | ActionBinding


_P = ParamSpec("_P")
_T = TypeVar("_T", bound=Awaitable[Any] | AsyncIterable[Any])


@overload
def query(function: Callable[_P, _T]) -> Callable[_P, _T]:
    ...


@overload
def query(
    *,
    poll: float | timedelta = ...,
) -> Callable[[Callable[_P, _T]], Callable[_P, _T]]:
    ...


@validate_arguments
def query(
    function: Callable[_P, _T] | None = None,
    *,
    poll: float | timedelta = timedelta(seconds=5),
) -> Callable[_P, _T] | Callable[[Callable[_P, _T]], Callable[_P, _T]]:
    def query(function: Callable[_P, _T]) -> Callable[_P, _T]:
        validated = _validate_procedure(function, ProcedureKind.QUERY)
        _bind(
            function,
            QueryBinding(
                name=_get_bound_name(function),
                function=get_function_name(function),
                args=validated.args,
                output=validated.output,
                live=validated.live,
                poll=poll if isinstance(poll, timedelta) else timedelta(seconds=poll),
            ),
        )

        return function

    if function is None:
        return query

    return query(function)


@overload
def action(function: Callable[_P, _T]) -> Callable[_P, _T]:
    ...


@overload
def action() -> Callable[[Callable[_P, _T]], Callable[_P, _T]]:
    ...


@validate_arguments
def action(
    function: Callable[_P, _T] | None = None,
) -> Callable[_P, _T] | Callable[[Callable[_P, _T]], Callable[_P, _T]]:
    def action(function: Callable[_P, _T]) -> Callable[_P, _T]:
        validated = _validate_procedure(function, ProcedureKind.ACTION)
        _bind(
            function,
            ActionBinding(
                name=_get_bound_name(function),
                function=get_function_name(function),
                args=validated.args,
                output=validated.output,
                live=validated.live,
            ),
        )

        return function

    if function is None:
        return action

    return action(function)


def _remove_extra_args(current: Any) -> bool:
    if isinstance(current, dict) and current.get("type") == "object":
        properties = current.get("properties")
        if isinstance(properties, dict):
            for key in list(properties):
                if isinstance(key, str) and (key.startswith("v__") or key == "self"):
                    del properties[key]
            args_property = properties.get("args")
            if isinstance(args_property, dict):
                if args_property.get("type") == "array" and args_property.get("items") == {}:
                    del properties["args"]

            kwargs_property = properties.get("kwargs")
            if isinstance(kwargs_property, dict):
                if kwargs_property.get("type") == "object" and kwargs_property.get("items") is None:
                    del properties["kwargs"]

            required = current.get("required")
            if isinstance(required, list):
                if "self" in required:
                    required.remove("self")
                if not required:
                    del current["required"]

    return True


def _get_args_schema(model: type[BaseModel]) -> Mapping[str, Any]:
    schema = schema_of(model)
    traverse(schema, _remove_extra_args)
    return schema


def _get_output_schema(hint: Any) -> Mapping[str, Any]:
    return schema_of(hint)


class _ValidatedProcedureInfo(ImmutableDataObject):
    args: ProcedureArgsInfo | None
    output: ProcedureOutputInfo
    live: bool


def _validate_procedure(
    function: Callable[..., Any],
    kind: ProcedureKind,
) -> _ValidatedProcedureInfo:
    signature = inspect.signature(function)
    parameters = [*signature.parameters.values()]
    if not parameters or parameters[0].name != "self":
        raise ValueError(f"{kind} {strify(function)} must have 'self' as its first parameter")
    if any(parameter.kind == Parameter.POSITIONAL_ONLY for parameter in parameters[1:]):
        raise ValueError(f"{kind} {strify(function)} cannot have positional-only arguments")

    validation_config: Any = ConfigDict(extra=Extra.forbid)
    validated = ValidatedFunction(function, validation_config)
    args_model = validated.model
    args_json_schema = _get_args_schema(args_model)
    args_info = ProcedureArgsInfo(
        json_schema=args_json_schema,
        required=any(
            field.required and not field.name == "self" for field in args_model.__fields__.values()
        ),
    )

    hints = get_type_hints(function)
    if "return" not in hints:
        raise ValueError(f"return type of {kind} {strify(function)} must be specified")

    output_hint = hints["return"]

    live = inspect.isasyncgenfunction(function)

    if live:
        error = ValueError(
            f"return type of live {kind} {strify(function)} must be AsyncIterable[T]"
        )

        try:
            if output_hint.__name__ != "AsyncIterable":
                raise error

            output_hint = get_args(output_hint)[0]
        except Exception:
            raise error

    try:
        output_json_schema = _get_output_schema(output_hint)
    except Exception as exception:
        raise ValueError(
            f"output type of {kind} {strify(function)} must be serializable as a JSON object: "
            f"{exception}"
        )

    output_info = ProcedureOutputInfo(
        json_schema=output_json_schema,
    )

    return _ValidatedProcedureInfo(
        args=args_info,
        output=output_info,
        live=live,
    )


_BINDINGS_ATTRIBUTE = "__bindings__"


class RoutineBinding(ImmutableDataObject):
    function: Name


_RoutineReturn = Awaitable[None]


def routine(function: Callable[[Any], _RoutineReturn]) -> Callable[[Any], _RoutineReturn]:
    _bind(
        function,
        RoutineBinding(
            function=get_function_name(function),
        ),
    )

    return function


def _get_bound_name(function: Callable[..., Any]) -> str:
    return _get_normalized_name(get_function_name(function))


def _get_normalized_name(name: str) -> Name:
    return name.replace("_", "-").strip().strip("-")


@runtime_checkable
class Binding(Protocol):
    function: str


_BindingT = TypeVar("_BindingT", bound=Binding)


def get_function_bindings(
    function: Callable[..., Any],
    binding_cls: type[_BindingT],
) -> tuple[_BindingT, ...]:
    function = get_inner_function(function)
    output: list[_BindingT] = []

    if values := getattr(function, _BINDINGS_ATTRIBUTE, None):
        if isinstance(values, Iterable):
            for value in values:
                if isinstance(value, binding_cls):
                    output.append(value)

    return tuple(output)


def _bind(function: Callable[..., object], binding: Binding) -> None:
    function = get_inner_function(function)
    bindings: Sequence[Binding] | None = getattr(function, _BINDINGS_ATTRIBUTE, None)

    if not isinstance(bindings, Sequence):
        bindings = []

    if isinstance(bindings, list):
        bindings.append(binding)
    else:
        bindings = [*bindings, binding]

    setattr(function, _BINDINGS_ATTRIBUTE, bindings)


def get_bindings(component_cls: type[Component], binding_cls: type[_BindingT]) -> list[_BindingT]:
    bindings: dict[str, _BindingT] = {}

    for cls in reversed(component_cls.__mro__):
        for member in vars(cls).values():
            if not callable(member):
                continue

            for binding in get_function_bindings(member, binding_cls):
                bindings[binding.function] = binding

    return sorted(bindings.values(), key=lambda current: current.function)


@final
class _Listener:
    __slots__ = (
        "__component",
        "__binding",
        "__handler",
        "__handler_arity",
        "__queue",
    )

    def __init__(
        self,
        *,
        component: Component,
        binding: ListenerBinding,
        handler: Callable[[Event], None | Awaitable[None]] | Callable[[], None | Awaitable[None]],
    ) -> None:
        self.__component = component
        self.__binding = binding
        self.__handler = handler
        self.__handler_arity = len(inspect.signature(self.__handler).parameters)
        self.__queue: AsyncQueue[Event] = AsyncQueue()

    @property
    def idle(self) -> bool:
        return self.__queue._finished.is_set()  # type: ignore

    def clear(self) -> None:
        while not self.__queue.empty():
            self.__queue.get_nowait()
            self.__queue.task_done()

    def handles(self, event: Event) -> bool:
        if not lenient_isinstance(event, self.__binding.event):
            return False

        if self.__binding.self:
            if event.address == self.__component.address:
                return True

        if self.__binding.reference:
            for alias in self.__binding.reference:
                if self.__component.address == event.address or any(
                    component.address == event.address
                    for component in self.__component.get_referenced_components(alias)
                ):
                    return True

        if self.__binding.address is not None:
            if self.__binding.address.matches(event.address, self.__component.address):
                return True

        return False

    def handle(self, event: Event) -> bool:
        if not self.handles(event):
            return False

        self.__queue.put_nowait(event)
        return True

    async def run(self) -> None:
        while True:
            event = await self.__queue.get()

            try:
                result = self.__handler(*[event][: self.__handler_arity])
                if inspect.iscoroutine(result):
                    await result
            except Exception:
                self.__component.log.error(
                    f"An exception occurred while processing event {event}: "
                    f"{traceback.format_exc()}"
                )
            finally:
                self.__queue.task_done()

    async def settle(self) -> None:
        if self.__queue.empty():
            return

        await self.__queue.join()
