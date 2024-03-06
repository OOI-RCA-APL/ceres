import asyncio
import inspect
import traceback
import warnings
from asyncio import CancelledError
from asyncio import Queue as AsyncQueue
from datetime import datetime, timedelta, timezone
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
    get_args,
    get_type_hints,
    runtime_checkable,
)
from weakref import WeakValueDictionary, ref

from aiotools.taskgroup import TaskGroup
from apscheduler.job import Job as InternalJob
from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.base import BaseTrigger
from pydantic import Field, NonNegativeInt, PositiveFloat, ValidationError
from pydantic.fields import FieldInfo
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing_extensions import Self, Unpack, dataclass_transform, overload, override

from ceres.address import Address, AddressSelector, DynamicAddress
from ceres.alert import Alert
from ceres.config import ComponentConfig
from ceres.data import (
    ImmutableDataObject,
    Name,
    PositiveTimeDelta,
    StrEnum,
)
from ceres.database.database import Database
from ceres.errors import (
    Failure,
    ProcedureInternalError,
    ProcedureInvalidArgumentsError,
    ProcedureNotFoundError,
    ProcedureNotSubscribableError,
)
from ceres.events import (
    AddedEvent,
    AlertEvent,
    DisabledEvent,
    EnabledEvent,
    Event,
    JobCancelledEvent,
    JobCompletedEvent,
    JobExceptionEvent,
    JobRetryEvent,
    JobRetryPendingEvent,
    JobStartedEvent,
    JobStoppedEvent,
    ProcedureCalledEvent,
    ProcedureCancelledEvent,
    ProcedureCompletedEvent,
    ProcedureExceptionEvent,
    RemovedEvent,
    RoutineCancelledEvent,
    RoutineCompletedEvent,
    RoutineExceptionEvent,
    RoutineRestartedEvent,
    RoutineRestartingEvent,
    RoutineStartedEvent,
    RoutineStoppedEvent,
    StoppedEvent,
    StoppingEvent,
)
from ceres.filter import ComponentFilter, ComponentFilterArgs
from ceres.internal.database.entities import StoreEntity
from ceres.internal.utilities import (
    Undefined,
    awaitify,
    cached,
    create_validated_function,
    decode_td,
    get_args_model,
    get_function_name,
    get_inner_function,
    get_return_annotation,
    get_session,
    get_traceback,
    get_type_adapter,
    lenient_isinstance,
    randstr,
    setattr_internal,
    strify,
    strlist,
    traverse,
    uniquify,
    validated_function,
)
from ceres.level import Level
from ceres.logs import LogEntry
from ceres.message import Message
from ceres.object import Object, Status
from ceres.schedule import Schedule, Trigger
from ceres.store import Store
from ceres.validation import ValidationProblem

if TYPE_CHECKING:
    from ceres.engine import Engine
    from ceres.reference import Reference
else:
    Engine = object
    Reference = object

_ComponentT = TypeVar("_ComponentT", bound="Component")
_EventT = TypeVar("_EventT", bound=Event)
_EventP = ParamSpec("_EventP")


Record = Message | Alert | LogEntry
Item = Store | Record

warnings.filterwarnings(
    action="ignore",
    module="apscheduler",
    message=r".*localize method is no longer necessary.*",
)


class Job:
    def __init__(
        self,
        *,
        internal: InternalJob,
        schedule: Schedule,
        action: Name,
        arguments: Mapping[str, Any] | None,
        retries: int,
        retry_delay: timedelta,
    ) -> None:
        self.__internal = internal
        self.__schedule = schedule
        self.__action = action
        self.__arguments = arguments
        self.__retries = retries
        self.__retry_delay = retry_delay

    @property
    def name(self) -> Name:
        return self.__internal.name

    @property
    def schedule(self) -> Schedule:
        return self.__schedule

    @property
    def action(self) -> Name:
        return self.__action

    @property
    def arguments(self) -> Mapping[str, Any] | None:
        return self.__arguments

    @property
    def retries(self) -> int:
        return self.__retries

    @property
    def retry_delay(self) -> timedelta:
        return self.__retry_delay

    @property
    def next_run_time(self) -> datetime | None:
        return self.__internal.next_run_time

    def get_run_times(
        self,
        start: datetime | None = None,
        *,
        end: datetime | None = None,
        count: int | None = None,
    ) -> Iterable[datetime]:
        yield from self.__schedule.as_trigger().get_fire_times(start, end=end, count=count)


class _TriggerAdapter(BaseTrigger):
    def __init__(self, inner: Trigger) -> None:
        super().__init__()
        self.__inner = inner

    def get_next_fire_time(  # type: ignore
        self,
        previous_fire_time: datetime | None,
        now: datetime,
    ) -> datetime | None:
        return self.__inner.get_next_fire_time(previous_fire_time, now)


@dataclass_transform(
    kw_only_default=True,
    field_specifiers=(Field, FieldInfo),
)
class Component(Object):
    """
    A node in the component tree that performs asyncronous work.

    Components can be started and stopped, enabled or disabled, interact with other components
    directly, or through events, and schedule actions as jobs to run on a schedule.
    """

    name: Final[Name] = Field(default_factory=lambda: randstr(ascii_lowercase, 8))

    def __post_init__(self) -> None:
        super().__post_init__()
        self.__parent: ref[Component] | None = None
        self.__scheduler = AsyncIOScheduler(timezone=timezone.utc)
        self.__jobs: dict[str, Job] = {}
        self.__referencers: WeakValueDictionary[int, Component] = WeakValueDictionary()
        self.__components: dict[Name, Component] = {}
        self.__config__: "ComponentConfig | None" = None
        self.__enabled = False
        self.__engine: Engine | None = None
        self.__database: Database | None = None
        self.__listeners = [
            _Listener(
                component=self,
                binding=binding,
                handler=getattr(self, binding.method),
            )
            for binding in self.get_listener_bindings()
        ]

        self.sync_component_references()
        self.__setup__()

    def __setup__(self) -> None:
        pass

    @final
    @classmethod
    def get_listener_bindings(cls) -> Sequence["ListenerBinding"]:
        """
        Get all listener bindings for this component class.
        """
        return _get_listener_bindings(cls)

    @final
    @classmethod
    def get_routine_bindings(cls) -> Sequence["RoutineBinding"]:
        """
        Get all routine bindings for this component class.
        """
        return _get_routine_bindings(cls)

    @final
    @classmethod
    def get_query_bindings(cls) -> Mapping[str, "QueryBinding"]:
        """
        Get all query bindings for this component class. Returns a mapping of query names to query
        bindings.
        """
        return {
            name: binding
            for name, binding in cls.get_procedure_bindings().items()
            if isinstance(binding, QueryBinding)
        }

    @final
    @classmethod
    def get_query_binding(cls, name: Callable[..., Any] | str) -> "QueryBinding | None":
        """
        Get a query binding for this component class by name. Returns `None` if the query binding
        does not exist.
        """
        procedure = cls.get_procedure_binding(name)
        if not isinstance(procedure, QueryBinding):
            return None

        return procedure

    @final
    @classmethod
    def get_action_bindings(cls) -> Mapping[str, "ActionBinding"]:
        """
        Get all action bindings for this component class. Returns a mapping of action names to
        action bindings.
        """
        return {
            name: binding
            for name, binding in cls.get_procedure_bindings().items()
            if isinstance(binding, ActionBinding)
        }

    @final
    @classmethod
    def get_action_binding(cls, name: Callable[..., Any] | str) -> "ActionBinding | None":
        """
        Get an action binding for this component class by name. Returns `None` if the action binding
        does not exist.
        """
        procedure = cls.get_procedure_binding(name)
        if not isinstance(procedure, ActionBinding):
            return None

        return procedure

    @final
    @classmethod
    def get_procedure_bindings(cls) -> Mapping[str, "ProcedureBinding"]:
        """
        Get all procedure bindings (actions and queries) for this component class. Returns a mapping
        of procedure names to procedure bindings.
        """
        return _get_procedure_bindings(cls)

    @final
    @classmethod
    def get_procedure_binding(cls, name: Callable[..., Any] | str) -> "ProcedureBinding | None":
        """
        Get a procedure binding (action or query) for this component class by name. Returns `None`
        if the procedure does not exist.
        """
        if isinstance(name, str):
            return cls.get_procedure_bindings().get(name)

        return get_method_binding(name, ProcedureBinding)  # type: ignore

    @property
    @override
    def __object_parent__(self) -> Object | None:
        if self.parent is not None:
            return self.parent

        return self.engine

    @property
    @override
    def __object_descendants__(self) -> Iterable[Object]:
        return self.get_components()

    @property
    @override
    @final
    def __object_database__(self) -> Database:
        if self.parent is not None:
            return self.parent.__object_database__
        if self.engine is not None:
            return self.engine.__object_database__
        if self.__database is None:
            self.__database = Database()

        return self.__database

    @override
    async def __object_sync__(self, session: AsyncSession | None = None) -> None:
        async with await get_session(self.__object_database__, session) as session:
            await super().__object_sync__(session)
            self.__enabled = await self.__get_enabled_in_database(session)

    @property
    @override
    def address(self) -> Address:
        """
        The current address of the component.
        """
        if self.parent is not None:
            return self.parent.address / self.name

        return Address.root()

    @property
    def enabled(self) -> bool:
        """
        `True` if the component is enabled. Enabled components start automatically when their parent
        starts.
        """
        return self.__enabled

    @property
    @override
    def settled(self) -> bool:
        """
        `True` if the component is stopped or all event listeners are idle.
        """
        if not self.running:
            return True

        return super().settled and all(processor.idle for processor in self.__listeners)

    @override
    async def settle(self) -> None:
        """
        Wait until `settled` returns `True`.
        """
        while not self.settled:
            async with TaskGroup() as group:
                group.create_task(super().settle())
                for listener in self.__listeners:
                    group.create_task(listener.settle())

    @override
    def handle(self, event: Event) -> None:
        """
        Handle a given event.
        """

        super().handle(event)

        if not self.running or self.stopping:
            return

        for listener in self.__listeners:
            listener.handle(event)

    async def enable(self) -> None:
        """
        Enable the component, and implicitly, all ancestors. Enabled components start automatically
        when their parent starts.
        """
        if self.parent is not None:
            await self.parent.enable()

        async with await self.__object_database__.init() as session:
            await self.__set_enabled_in_database(session, True)
        self.__enabled = True
        self.emit(EnabledEvent)

    async def disable(self) -> None:
        """
        Disable the component.
        """
        async with await self.__object_database__.init() as session:
            await self.__set_enabled_in_database(session, False)
        self.__enabled = False
        self.emit(DisabledEvent)

    async def up(self) -> None:
        """
        Enable and start the component.
        """
        await self.enable()
        self.start()

    async def down(self) -> None:
        """
        Disable and stop the component.
        """
        await self.disable()
        await self.stop()

    async def __get_enabled_in_database(self, session: AsyncSession) -> bool:
        enabled = await session.scalar(
            select(StoreEntity.enabled).where(StoreEntity.address == self.address)
        )

        if enabled is None:
            return False

        return enabled

    async def __set_enabled_in_database(self, session: AsyncSession, enabled: bool) -> None:
        if self.__object_database__.type == "sqlite":
            from sqlalchemy.dialects.sqlite import insert
        else:
            from sqlalchemy.dialects.postgresql import insert

        await self.__object_sync__(session)
        await session.execute(
            insert(StoreEntity)
            .values(
                address=self.address,
                enabled=enabled,
            )
            .on_conflict_do_update(
                index_elements=[StoreEntity.address],
                set_={"enabled": enabled},
            )
        )

        await session.commit()

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
        """
        Get the parent component of this component. Returns `None` if the component has no parent.
        """
        if self.__parent is None:
            return None

        return self.__parent()

    @property
    @override
    @final
    def engine(self) -> Engine | None:
        """
        Get the engine that the component is running under. Returns `None` if the component is not
        running under an engine.
        """

        if self.parent is not None:
            return self.parent.engine
        if self.__engine is not None:
            return self.__engine

        return None

    @engine.setter
    def engine(self, engine: Engine) -> None:
        """
        Bind the component to a given engine.
        """
        self.__engine = engine

    @property
    def components(self) -> "ComponentGroup":
        """
        Get the child components of this component.
        """
        return ComponentGroup(self.__components.values())

    def unref(self) -> Self:
        return self

    def sync_component_references(self) -> tuple[list[Reference], list[Reference]]:
        resolved: list[Reference] = []
        unresolved: list[Reference] = []

        for reference in self.get_component_references():
            reference.__reference_root__ = self

            if reference.unref() is not None:
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
        from ceres.reference import Reference

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
        """
        Add a child component to this component.
        """
        if component is self or component in self.get_ancestor_components():
            raise ValueError("component cannot contain itself")

        component.remove_component()

        name = name or component.name
        self.remove_component(name)

        if component.name != name:
            setattr_internal(Component, component, "name", name)

        self.__components[component.name] = component
        component.__parent = ref(self)  # type: ignore
        component.sync_component_references()
        component.emit(AddedEvent)

        self.__sync_component_order()
        return component

    def remove_component(self, address: str | DynamicAddress | None = None) -> "Component | None":
        """
        Remove a component at the given address from the tree if it exists. If no address is given,
        remove this component itself. The removed component is returned, or `None` if the component
        was not found.
        """
        if address is None:
            if self.parent is None:
                return self

            current = self.parent.__components.get(self.name)

            if current is not None and current is self:
                self.emit(RemovedEvent)
                self.parent.__components.pop(self.name, None)
                self.parent.__sync_component_order()
                current.sync_component_references()

            self.__parent = None

            return self

        component = self.get_component(address)
        if component is not None:
            component.remove_component()

        return component

    @override
    def get_component(self, address: str | DynamicAddress | None = None, /) -> "Component | None":
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
            filter = ComponentFilter(address=filter).with_overrides(overrides)
        else:
            filter = overrides

        filter = filter.with_defaults(ComponentFilter(root=self.address))

        def traverse(current: Component) -> None:
            if (inclusive or current is not self) and filter.matches(current):
                components.append(current)

            for component in current.__components.values():
                traverse(component)

        traverse(self)

        return ComponentGroup(components)

    @override
    async def get_status(self) -> Status:
        status = await super().get_status()
        status.enabled = self.enabled
        return status

    def get_ancestor_components(self, *, inclusive: bool = False) -> "ComponentGroup":
        """
        Return a group of all ancestor components in ascending order. If `inclusive` is `True`,
        include this component itself as the first component in the sequence.
        """
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
        """
        Construct and emit an event, assigning the address of the event to this component's address
        if unset. Emitted events are propagated to all ancestor components and any other components
        currently holding a reference to this component.
        """
        if "address" not in kwargs:
            kwargs["address"] = self.address

        return self.propagate(event_cls(*args, **kwargs))

    def propagate(self, event: _EventT) -> _EventT:
        """
        Propagate an event to all ancestor components and any other components currently holding a
        reference to this component.
        """
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
        """
        Emit an alert with the given `level`, `code`, and `info`.
        """
        alert = Alert(
            address=self.address,
            level=level,
            code=code,
            info=dict(info) if info is not None else {},
        )
        self.emit(AlertEvent, alert=alert)
        return alert

    @validated_function
    def add_job(
        self,
        name: Name,
        schedule: Schedule,
        action: Callable[..., Any] | Name,
        arguments: Mapping[Name, Any] | None = None,
        retries: NonNegativeInt = 0,
        retry_delay: PositiveFloat | PositiveTimeDelta = timedelta(seconds=5),
    ) -> Job:
        """
        Register an `action` to be executed as a job on a given `schedule`.
        """
        binding = self.get_action_binding(action)
        if binding is None:
            raise ValueError(f"action '{action}' does not exist on {strify(type(self))}")

        retry_delay = decode_td(retry_delay)

        async def callback() -> None:
            await self.__process_job(
                name=name,
                action=binding.name,
                arguments=arguments,
                retries=retries,
                retry_delay=retry_delay,
            )

        internal: InternalJob = self.__scheduler.add_job(
            callback,
            trigger=_TriggerAdapter(schedule.as_trigger()),
            name=name,
            id=name,
        )

        job = Job(
            internal=internal,
            schedule=schedule,
            action=binding.name,
            arguments=arguments,
            retries=retries,
            retry_delay=retry_delay,
        )

        self.__jobs[name] = job
        return job

    async def __process_job(
        self,
        name: Name,
        action: Name,
        arguments: Mapping[str, Any] | None,
        retries: NonNegativeInt,
        retry_delay: PositiveTimeDelta,
    ) -> None:
        self.emit(JobStartedEvent, job=name)
        retry = 0

        while True:
            try:
                await self.call(action, arguments)
                self.emit(JobCompletedEvent, job=name)
                break
            except CancelledError:
                self.emit(JobCancelledEvent, job=name)
                break
            except Exception as exception:
                self.emit(JobExceptionEvent, job=name, traceback=get_traceback(exception))
                if retry >= retries:
                    break

                self.emit(JobRetryPendingEvent, job=name, delay=retry_delay)
                retry += 1
                await asyncio.sleep(retry_delay.total_seconds())
                self.emit(JobRetryEvent, job=name)

        self.emit(JobStoppedEvent, job=name)

    def get_jobs(self) -> list[Job]:
        """
        Get a list of all registered jobs on this component.
        """
        return list(self.__jobs.values())

    def get_job(self, name: Name) -> Job | None:
        """
        Get a registered job from this component by name. Returns `None` if the job does not exist.
        """
        return self.__jobs.get(name)

    def remove_job(self, name: Name) -> Job | None:
        """
        Remove a registered job from this component by name. Returns the removed job, or `None` if
        the job does not exist.
        """
        job = self.__jobs.pop(name, None)

        try:
            self.__scheduler.remove_job(name)
        except JobLookupError:
            pass

        return job

    def clear_jobs(self) -> None:
        """
        Remove all registered jobs.
        """
        self.__jobs.clear()
        for job in self.__scheduler.get_jobs():
            job: InternalJob = job
            self.__scheduler.remove_job(job.id)

    @override
    def start(
        self,
        *,
        on_completed: Callable[[Self], None] | None = None,
        on_exception: Callable[[Self, BaseException], None] | None = None,
        all_enabled: bool = True,
    ) -> None:
        for component in reversed(self.get_ancestor_components()):
            component.start(all_enabled=False)

        super().start(
            on_completed=on_completed,
            on_exception=on_exception,
        )

        if all_enabled:
            for component in self.__components.values():
                if component.enabled:
                    component.start()

    @override
    async def __run__(self) -> None:
        for component in reversed(self.get_ancestor_components()):
            component.start(all_enabled=False)

        await self.__object_sync__()

        self.__scheduler.start()

        async with TaskGroup() as group:
            group.create_task(super().__run__())
            group.create_task(self.__process_events())
            group.create_task(self.__process_routines())

    async def __process_events(self) -> None:
        async with TaskGroup() as group:
            for listener in self.__listeners:
                group.create_task(listener.run())

    async def __process_routine(self, binding: "RoutineBinding") -> None:
        routine = getattr(self, binding.method, None)
        if routine is None:
            return

        self.emit(RoutineStartedEvent, routine=binding.method)
        if type(self).__name__ == "RunsForever":
            self.log.info(f"Running routine '{binding.method}' forever...")

        try:
            while True:
                try:
                    await routine()
                    self.emit(RoutineCompletedEvent, routine=binding.method)
                    if binding.restart == RoutineRestartPolicy.ON_COMPLETED:
                        break
                except Exception as exception:
                    self.emit(
                        RoutineExceptionEvent,
                        routine=binding.method,
                        traceback=get_traceback(exception),
                    )
                    if binding.restart == RoutineRestartPolicy.ON_EXCEPTION:
                        break

                if binding.restart == RoutineRestartPolicy.NEVER:
                    break

                self.emit(
                    RoutineRestartingEvent,
                    routine=binding.method,
                    delay=binding.restart_delay,
                )
                await asyncio.sleep(binding.restart_delay.total_seconds())
                self.emit(RoutineRestartedEvent, routine=binding.method)
        except CancelledError:
            self.emit(RoutineCancelledEvent, routine=binding.method)
            raise
        finally:
            self.emit(RoutineStoppedEvent, routine=binding.method)

    async def __process_routines(self) -> None:
        async with TaskGroup() as group:
            for binding in self.get_routine_bindings():
                group.create_task(self.__process_routine(binding))

    @override
    async def __stop__(self) -> None:
        self.emit(StoppingEvent)
        for component in reversed(self.components):
            await component.stop()

        if self.__scheduler.running:
            self.__scheduler.shutdown()

        self.emit(StoppedEvent)
        await self.flush()

        if self.__database is not None:
            await self.__database.dispose()
            self.__database = None

    async def __invoke(
        self,
        procedure: str,
        arguments: Mapping[Name, Any] | None = None,
    ) -> Any:
        if arguments is None:
            arguments = {}

        if (
            (binding := self.get_procedure_bindings().get(procedure)) is None
            or (method := getattr(self, binding.method, None)) is None
            or not inspect.ismethod(method)
        ):
            raise Failure(ProcedureNotFoundError)

        validated = create_validated_function(method)

        try:
            self.emit(ProcedureCalledEvent, procedure=procedure)
            return await awaitify(validated(**arguments))
        except CancelledError:
            self.emit(ProcedureCancelledEvent, procedure=procedure)
            raise
        except ValidationError as error:
            if method.__name__ in error.title:
                raise Failure(
                    ProcedureInvalidArgumentsError(problems=ValidationProblem.extract(error))
                )

            raise
        except Exception as exception:
            traceback = get_traceback(exception)
            self.emit(ProcedureExceptionEvent, procedure=procedure, traceback=traceback)
            raise Failure(ProcedureInternalError(traceback=list(traceback)))

    async def call(
        self,
        procedure: str,
        arguments: Mapping[Name, Any] | None = None,
    ) -> object | None:
        """
        Call a procedure on the component with the given `arguments`.
        """
        result = await self.__invoke(procedure, arguments)
        binding = self.get_procedure_bindings()[procedure]

        if not binding.live:
            self.emit(ProcedureCompletedEvent, procedure=procedure)
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
            traceback = get_traceback(exception)
            self.emit(ProcedureExceptionEvent, procedure=procedure, traceback=traceback)
            raise Failure(ProcedureInternalError(traceback=list(traceback)))
        finally:
            self.emit(ProcedureCompletedEvent, procedure=procedure)

    async def subscribe(
        self,
        procedure: str,
        arguments: Mapping[Name, Any] | None = None,
    ) -> AsyncIterable[object | None]:
        """
        Subscribe to a procedure on the component with the given `arguments`. Not all procedures are
        subscribable.
        """
        result = await self.__invoke(procedure, arguments)
        binding = self.get_procedure_bindings()[procedure]

        if not binding.live:
            if isinstance(binding, ActionBinding):
                raise Failure(ProcedureNotSubscribableError)

            try:
                while True:
                    yield await self.__invoke(procedure, arguments)
                    await asyncio.sleep(binding.poll.total_seconds())
            except CancelledError:
                self.emit(ProcedureCancelledEvent, procedure=procedure)
                raise
            except Exception as exception:
                traceback = get_traceback(exception)
                self.emit(ProcedureExceptionEvent, procedure=procedure, traceback=traceback)
                raise Failure(ProcedureInternalError(traceback=list(traceback)))

        try:
            if result is not None:
                async for output in result:
                    yield output
            self.emit(ProcedureCompletedEvent, procedure=procedure)
        except CancelledError:
            self.emit(ProcedureCancelledEvent, procedure=procedure)
            raise
        except Exception as exception:
            traceback = get_traceback(exception)
            self.emit(ProcedureExceptionEvent, procedure=procedure, traceback=traceback)
            raise Failure(ProcedureInternalError(traceback=list(traceback)))

    def __sync_component_order(self) -> None:
        if self.__config__ is None:
            return

        order: list[Component] = []
        for config in self.__config__.components:
            component = self.__components.get(config.name)
            if component is not None:
                order.append(component)

        for component in self.__components.values():
            if not any(current is component for current in order):
                order.append(component)

        self.__components.clear()
        for component in order:
            self.__components[component.name] = component


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

    def __init__(self, components: Iterable[Component] = ()):
        self.__components = tuple(uniquify(components, key=lambda component: id(component.unref())))
        self.__identities: set[int] | None = None

    def __repr__(self) -> str:
        return f"{type(self).__name__}({repr(list(self.__components))})"

    def __str__(self) -> str:
        return repr(self)

    @overload
    def __getitem__(self, __index: int) -> Component: ...

    @overload
    def __getitem__(self, __index: slice) -> Self: ...

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
        if not self.__components:
            return False

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
    method: Name
    event: type | UnionType
    local: bool
    reference: Sequence[str]
    address: AddressSelector | None


_ListenerMethodReturn = None | Awaitable[None]
_ListenerMethod = (
    Callable[[Any], _ListenerMethodReturn] | Callable[[Any, Any], _ListenerMethodReturn]
)
_ListenerMethodTransform = Callable[[_ListenerMethod], _ListenerMethod]


@overload
def on(method: _ListenerMethod) -> _ListenerMethod: ...


@overload
def on(
    *,
    event: type | UnionType | None = None,
    local: bool | None = None,
    reference: str | Sequence[str] | None = None,
    address: str | AddressSelector | Sequence[str | AddressSelector] | None = None,
) -> _ListenerMethodTransform: ...


@validated_function
def on(
    method: _ListenerMethod | None = None,
    *,
    event: type | UnionType | None = None,
    local: bool | None = None,
    reference: str | Sequence[str] | None = None,
    address: str | AddressSelector | Sequence[str | AddressSelector] | None = None,
) -> _ListenerMethod | _ListenerMethodTransform:
    reference = strlist(reference)

    if address is not None:
        if isinstance(address, (str, DynamicAddress)):
            address = [address]

        address = AddressSelector("|".join(str(current) for current in address))

    if local is None:
        local = len(reference) == 0 and address is None

    def on(method: _ListenerMethod) -> _ListenerMethod:
        signature = inspect.signature(method)

        assigned_event_type = event

        if assigned_event_type is None:
            hints = get_type_hints(method)
            parameters = list(signature.parameters.values())
            if len(parameters) > 1:
                event_parameter = parameters[1]
                assigned_event_type = hints.get(event_parameter.name)

        if assigned_event_type is None:
            assigned_event_type = Event

        _bind(
            method,
            ListenerBinding(
                name=_get_bound_name(method),
                method=get_function_name(method),
                reference=tuple(reference),
                address=address,
                local=local,
                event=assigned_event_type,
            ),
        )

        return method

    if method is None:
        return on

    return on(method)


class ProcedureType(StrEnum):
    QUERY = "query"
    ACTION = "action"


class ProcedureSchemas(ImmutableDataObject):
    arguments: Mapping[str, Any] | None
    output: Mapping[str, Any]


class ProcedureArgumentsInfo(ImmutableDataObject):
    json_schema: Mapping[str, Any]
    required: bool


class ProcedureOutputInfo(ImmutableDataObject):
    json_schema: Mapping[str, Any]


class __BaseProcedureBinding(ImmutableDataObject):
    name: Name
    type: ProcedureType
    method: str
    live: bool
    arguments: ProcedureArgumentsInfo | None
    output: ProcedureOutputInfo


class QueryBinding(__BaseProcedureBinding):
    type: Literal[ProcedureType.QUERY] = ProcedureType.QUERY
    poll: PositiveTimeDelta = timedelta(seconds=1)


class ActionBinding(__BaseProcedureBinding):
    type: Literal[ProcedureType.ACTION] = ProcedureType.ACTION


ProcedureBinding = QueryBinding | ActionBinding


_P = ParamSpec("_P")
_T = TypeVar("_T", bound=Awaitable[Any] | AsyncIterable[Any])


@overload
def query(method: Callable[_P, _T]) -> Callable[_P, _T]: ...


@overload
def query(
    *,
    poll: float | timedelta = ...,
) -> Callable[[Callable[_P, _T]], Callable[_P, _T]]: ...


@validated_function
def query(
    method: Callable[_P, _T] | None = None,
    *,
    poll: float | timedelta = timedelta(seconds=5),
) -> Callable[_P, _T] | Callable[[Callable[_P, _T]], Callable[_P, _T]]:
    def query(method: Callable[_P, _T]) -> Callable[_P, _T]:
        info = __get_procedure_method_info(method, ProcedureType.QUERY)
        _bind(
            method,
            QueryBinding(
                name=_get_bound_name(method),
                method=get_function_name(method),
                arguments=info.arguments,
                output=info.output,
                live=info.live,
                poll=poll if isinstance(poll, timedelta) else timedelta(seconds=poll),
            ),
        )

        return method

    if method is None:
        return query

    return query(method)


@overload
def action(method: Callable[_P, _T]) -> Callable[_P, _T]: ...


@overload
def action() -> Callable[[Callable[_P, _T]], Callable[_P, _T]]: ...


@validated_function
def action(
    method: Callable[_P, _T] | None = None,
) -> Callable[_P, _T] | Callable[[Callable[_P, _T]], Callable[_P, _T]]:
    def action(method: Callable[_P, _T]) -> Callable[_P, _T]:
        validated = __get_procedure_method_info(method, ProcedureType.ACTION)
        _bind(
            method,
            ActionBinding(
                name=_get_bound_name(method),
                method=get_function_name(method),
                arguments=validated.arguments,
                output=validated.output,
                live=validated.live,
            ),
        )

        return method

    if method is None:
        return action

    return action(method)


class __ProcedureMethodInfo(ImmutableDataObject):
    name: str
    method: str
    arguments: ProcedureArgumentsInfo | None
    output: ProcedureOutputInfo
    live: bool


def __get_procedure_method_info(
    method: Callable[..., Any],
    type_: ProcedureType,
    /,
) -> __ProcedureMethodInfo:
    method = get_inner_function(method)
    signature = inspect.signature(method)

    parameters = [*signature.parameters.values()]
    if not parameters or parameters[0].name != "self":
        raise ValueError(f"{type_} {strify(method)} must have 'self' as its first parameter")
    if any(parameter.kind == Parameter.POSITIONAL_ONLY for parameter in parameters[1:]):
        raise ValueError(f"{type_} {strify(method)} cannot have positional-only arguments")

    arguments_json_schema = get_args_model(method).model_json_schema()
    arguments_required = len(arguments_json_schema.get("properties", {}).get("required", [])) > 0

    output_annotation = get_return_annotation(method, Undefined)
    if output_annotation is Undefined:
        raise ValueError(f"return type of {type_} {strify(method)} must be specified")

    live = inspect.isasyncgenfunction(method)

    if live:
        error = ValueError(f"return type of live {type_} {strify(method)} must be AsyncIterable[T]")

        try:
            if output_annotation.__name__ != "AsyncIterable":
                raise error

            output_annotation = get_args(output_annotation)[0]
        except Exception:
            raise error

    try:
        output_json_schema = get_type_adapter(output_annotation).json_schema()
    except Exception as exception:
        raise ValueError(
            f"output type of {type_} {strify(method)} must be serializable as a JSON object: "
            f"{exception}"
        )

    return __ProcedureMethodInfo(
        name=_get_bound_name(method),
        method=get_function_name(method),
        arguments=ProcedureArgumentsInfo(
            json_schema=arguments_json_schema,
            required=arguments_required,
        ),
        output=ProcedureOutputInfo(
            json_schema=output_json_schema,
        ),
        live=live,
    )


_BINDINGS_ATTRIBUTE = "__bindings__"


class RoutineRestartPolicy(StrEnum):
    NEVER = "never"
    ALWAYS = "always"
    ON_COMPLETED = "on-completed"
    ON_EXCEPTION = "on-exception"


RoutineRestartPolicyLiteral = Literal[
    "never",
    "always",
    "on-completed",
    "on-exception",
]


class RoutineBinding(ImmutableDataObject):
    method: Name
    restart: RoutineRestartPolicy
    restart_delay: PositiveTimeDelta


_RoutineMethodReturn = Awaitable[None]
_RoutineMethod = Callable[[Any], _RoutineMethodReturn]
_RoutineMethodHandler = Callable[[_RoutineMethod], _RoutineMethod]


@overload
def routine(
    *,
    restart: RoutineRestartPolicy | RoutineRestartPolicyLiteral = RoutineRestartPolicy.NEVER,
    restart_delay: PositiveFloat | PositiveTimeDelta = timedelta(seconds=1),
) -> _RoutineMethodHandler: ...


@overload
def routine(method: _RoutineMethod) -> _RoutineMethod: ...


@validated_function
def routine(
    method: _RoutineMethod | None = None,
    *,
    restart: RoutineRestartPolicy | RoutineRestartPolicyLiteral = RoutineRestartPolicy.NEVER,
    restart_delay: PositiveFloat | PositiveTimeDelta = timedelta(seconds=1),
) -> _RoutineMethod | _RoutineMethodHandler:
    def routine(method: _RoutineMethod) -> _RoutineMethod:
        _bind(
            method,
            RoutineBinding(
                method=get_function_name(method),
                restart=RoutineRestartPolicy(restart),
                restart_delay=decode_td(restart_delay),
            ),
        )

        return method

    if method is None:
        return routine

    return routine(method)


def _get_bound_name(function: Callable[..., Any]) -> str:
    return _get_normalized_name(get_function_name(function))


def _get_normalized_name(name: str) -> Name:
    return name.replace("_", "-").strip().strip("-")


@runtime_checkable
class Binding(Protocol):
    method: str


_BindingT = TypeVar("_BindingT", bound=Binding)


def get_method_bindings(
    method: Callable[..., Any],
    binding_cls: type[_BindingT],
) -> tuple[_BindingT, ...]:
    method = get_inner_function(method)
    output: list[_BindingT] = []

    if values := getattr(method, _BINDINGS_ATTRIBUTE, None):
        if isinstance(values, Iterable):
            for value in values:
                if isinstance(value, binding_cls):
                    output.append(value)

    return tuple(output)


def get_method_binding(
    method: Callable[..., Any],
    binding_cls: type[_BindingT],
) -> _BindingT | None:
    bindings = get_method_bindings(method, binding_cls)
    if bindings:
        return bindings[0]

    return None


def _bind(method: Callable[..., object], binding: Binding) -> None:
    method = get_inner_function(method)
    bindings: Sequence[Binding] | None = getattr(method, _BINDINGS_ATTRIBUTE, None)

    if not isinstance(bindings, Sequence):
        bindings = []

    if isinstance(bindings, list):
        bindings.append(binding)
    else:
        bindings = [*bindings, binding]

    setattr(method, _BINDINGS_ATTRIBUTE, bindings)


def get_bindings(component_cls: type[Component], binding_cls: type[_BindingT]) -> list[_BindingT]:
    bindings: dict[str, _BindingT] = {}

    for cls in reversed(component_cls.__mro__):
        for member in vars(cls).values():
            if not callable(member):
                continue

            for binding in get_method_bindings(member, binding_cls):
                bindings[binding.method] = binding

    return sorted(bindings.values(), key=lambda current: current.method)


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

        if self.__binding.local:
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
