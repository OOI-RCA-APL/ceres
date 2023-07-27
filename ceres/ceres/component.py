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
    Iterable,
    Iterator,
    Mapping,
    ParamSpec,
    Sequence,
    TypeVar,
    final,
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
from ceres.filter import ComponentFilter, ComponentFilterArgs
from ceres.internal.binding import get_bindings
from ceres.internal.database.entities import ComponentEntity
from ceres.internal.events import EventProcessor
from ceres.internal.scheduler import Scheduler
from ceres.internal.utilities import (
    awaitify,
    cached,
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
from ceres.message import Message
from ceres.object import Object, Status
from ceres.procedure import (
    ActionBinding,
    ProcedureBinding,
    QueryBinding,
)
from ceres.routine import RoutineBinding
from ceres.schedule import Schedule
from ceres.validation import ValidationProblem

if TYPE_CHECKING:
    from ceres.server import Server
else:
    Server = object

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

        return Address.root()

    @property
    def enabled(self) -> bool:
        return self.__enabled

    @property
    @override
    def settled(self) -> bool:
        if not self.running:
            return True

        return super().settled and all(processor.idle for processor in self.__event_processors)

    @override
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
        if component is self or component in self.get_ancestor_components():
            raise ValueError("component cannot contain itself")

        if isinstance(name, str):
            setattr_internal(Component, component, "name", name)

        self.__components[component.name] = component
        component.remove_component()
        component.__parent = ref(self)  # type: ignore

        return component

    def remove_component(self, address: str | DynamicAddress | None = None) -> "Component | None":
        if address is None:
            if self.parent is not None:
                self.parent.__components.pop(self.name, None)
                self.__parent = None

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


class ComponentGroup(Sequence[Component]):
    def __init__(self, components: Iterable[Component]):
        self.components = tuple(uniquify(components, key=lambda component: component.address))

    def __repr__(self) -> str:
        return f"{type(self).__name__}({repr(list(self.components))})"

    def __str__(self) -> str:
        return repr(self)

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
