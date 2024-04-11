import asyncio
import inspect
import traceback
import warnings
from asyncio import CancelledError
from asyncio import Queue as AsyncQueue
from datetime import datetime, timedelta, timezone
from string import ascii_lowercase
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterable,
    Awaitable,
    Callable,
    Iterable,
    Iterator,
    Mapping,
    ParamSpec,
    Sequence,
    TypeVar,
    final,
)
from weakref import WeakValueDictionary, ref

from aiotools.taskgroup import TaskGroup
from apscheduler.job import Job as InternalJob
from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.base import BaseTrigger
from pydantic import NonNegativeInt, PositiveFloat, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing_extensions import Self, Unpack, overload, override

from ceres.address import Address, AddressSelector, DynamicAddress
from ceres.alert import Alert
from ceres.component import (
    ActionBinding,
    Component,
    ListenerBinding,
    QueryBinding,
    RoutineBinding,
    RoutineRestartPolicy,
)
from ceres.config import SystemConfig
from ceres.data import Name, PositiveTimeDelta
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
from ceres.filter import SystemFilter, SystemFilterArgs
from ceres.internal.database.entities import StoreEntity
from ceres.internal.utilities import (
    awaitify,
    create_validated_function,
    decode_td,
    get_session,
    get_traceback,
    get_type_adapter,
    lenient_isinstance,
    randstr,
    setattr_internal,
    strify,
    traverse,
    uniquify,
    validated_function,
)
from ceres.level import Level
from ceres.logs import LogEntry
from ceres.message import Message
from ceres.node import Node
from ceres.schedule import Schedule, Trigger
from ceres.status import Status
from ceres.store import Store
from ceres.validation import ValidationProblem

if TYPE_CHECKING:
    from ceres.engine import Engine
    from ceres.reference import Reference
else:
    Engine = object
    Reference = object

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


@final
class System(Node):
    def __init__(
        self,
        component: Component | Callable[[], Component] | None = None,
        *,
        name: Name | None = None,
    ) -> None:
        super().__init__()

        if name is None:
            name = randstr(ascii_lowercase, 8)
        if component is None:
            component = Component()
        elif callable(component) and not lenient_isinstance(component, Component):
            component = component()

        self.__name = name
        self.__component = component
        self.__component.__bind__(self)

        self.__parent: ref[System] | None = None
        self.__scheduler = AsyncIOScheduler(timezone=timezone.utc)
        self.__jobs: dict[str, Job] = {}
        self.__referencers: WeakValueDictionary[int, System] = WeakValueDictionary()
        self.__children: dict[Name, System] = {}
        self.__config__: "SystemConfig | None" = None
        self.__enabled = False
        self.__engine: Engine | None = None
        self.__database: Database | None = None
        self.__listeners: list[_Listener] = []

        self.sync_references()
        self.__setup__()

    def __setup__(self) -> None:
        pass

    @classmethod
    def from_config(cls, config: SystemConfig) -> "System":
        component: Component = get_type_adapter(config.component).validate_python(config.arguments)
        system = cls(component, name=config.name)
        system.__config__ = config
        for job in config.jobs:
            # TODO: Validate job arguments.
            system.add_job(job.name, job.schedule, job.action, job.arguments)

        return system

    @property
    @override
    def __node_parent__(self) -> "Node | None":
        if self.parent is not None:
            return self.parent

        return self.engine

    @property
    @override
    def __node_descendants__(self) -> Iterable["Node"]:
        return self.get_systems(inclusive=False)

    @property
    @override
    def parent(self) -> "System | None":
        """
        Get the parent component of this component. Returns `None` if the component has no parent.
        """
        if self.__parent is None:
            return None

        return self.__parent()

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
    @override
    def root(self) -> "System":
        current: System | None = self
        while current.parent is not None:
            current = current.parent

        return current

    @property
    @override
    def database(self) -> Database:
        if self.parent is not None:
            return self.parent.database
        if self.engine is not None:
            return self.engine.database
        if self.__database is None:
            self.__database = Database()

        return self.__database

    @property
    @override
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

    @override
    async def __node_sync__(self, session: AsyncSession | None = None) -> None:
        async with await get_session(self.database, session) as session:
            await super().__node_sync__(session)
            self.__enabled = await self.__get_enabled_in_database(session)

    @property
    def name(self) -> Name:
        return self.__name

    @property
    def component(self) -> Component:
        return self.__component

    @property
    def enabled(self) -> bool:
        """
        `True` if the system is enabled. Enabled systems start automatically when their parent
        system starts.
        """
        return self.__enabled

    @property
    @override
    def settled(self) -> bool:
        """
        `True` if the system is stopped or all event listeners are idle.
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
        Enable the system, and implicitly, all ancestors. Enabled systems start automatically
        when their parent starts.
        """
        if self.parent is not None:
            await self.parent.enable()

        async with await self.database.init() as session:
            await self.__set_enabled_in_database(session, True)
        self.__enabled = True
        self.emit(EnabledEvent)

    async def disable(self) -> None:
        """
        Disable the system.
        """
        async with await self.database.init() as session:
            await self.__set_enabled_in_database(session, False)
        self.__enabled = False
        self.emit(DisabledEvent)

    async def up(self) -> None:
        """
        Enable and start the system.
        """
        await self.enable()
        self.start()

    async def down(self) -> None:
        """
        Disable and stop the system.
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
        if self.database.type == "sqlite":
            from sqlalchemy.dialects.sqlite import insert
        else:
            from sqlalchemy.dialects.postgresql import insert

        await self.__node_sync__(session)
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
    def subsystems(self) -> "SystemGroup":
        """
        Get all child subsystems of this system
        """
        return SystemGroup(self.__children.values())

    def sync_references(self) -> tuple[list[Reference], list[Reference]]:
        resolved: list[Reference] = []
        unresolved: list[Reference] = []

        for reference in self.get_references():
            reference.__reference_root__ = self.component

            if reference.unref() is not None:
                resolved.append(reference)
            else:
                unresolved.append(reference)

        for referencer in list(self.__referencers.values()):
            if id(self) not in {id(other.unref()) for other in referencer.get_references()}:
                self.__referencers.pop(id(referencer))

        for component in self.get_referenced_systems():
            component.__referencers[id(self)] = self

        return resolved, unresolved

    def get_references(self) -> list[Reference]:
        from ceres.reference import Reference

        references: list[Reference] = []

        def visit(obj: Any) -> bool:
            if isinstance(obj, Reference):
                references.append(obj)
                return False

            return True

        traverse(self.component, visit)
        return references

    def get_referenced_systems(self, alias: str | None = None) -> "SystemGroup":
        systems: list[System] = []
        root = self.component

        if alias is not None:
            for segment in alias.split("."):
                root = getattr(root, segment, None)
                if root is None:
                    break

        if root is None:
            return SystemGroup(systems)

        def visit(obj: Any) -> bool:
            if lenient_isinstance(obj, Component):
                obj = obj.unref()
                if obj is not self and obj is not self.component:
                    systems.append(obj.system)
                    return False

            return True

        traverse(root, visit)
        return SystemGroup(systems)

    def add(
        self,
        system: "System",
        /,
        name: Name | None = None,
    ) -> "System":
        """
        Add a child system to this system.
        """
        if system is self or system in self.get_ancestors():
            raise ValueError("component cannot contain itself")

        system.remove()

        name = name or system.name
        self.remove(name)

        if system.name != name:
            setattr_internal(System, system, "__name", name)

        self.__children[system.name] = system
        system.__parent = ref(self)  # type: ignore
        system.sync_references()
        system.emit(AddedEvent)

        self.__sync_child_order()
        return system

    def remove(self, address: str | DynamicAddress | None = None) -> "System | None":
        """
        Remove a system from the tree at the given address, if it exists. If no address is given,
        remove this system itself. The removed system is returned, or `None` if the system
        was not found.
        """
        if address is None:
            if self.parent is None:
                return self

            current = self.parent.__children.get(self.name)

            if current is not None and current is self:
                self.emit(RemovedEvent)
                self.parent.__children.pop(self.name, None)
                self.parent.__sync_child_order()
                current.sync_references()

            self.__parent = None

            return self

        component = self.get_system(address)
        if component is not None:
            component.remove()

        return component

    @override
    def get_system(self, address: str | DynamicAddress | None = None, /) -> "System | None":
        if not address:
            return self

        if not isinstance(address, DynamicAddress):
            address = DynamicAddress(address)

        if address.is_absolute and self.parent is not None:
            return self.root.get_system(address)

        current: System | None = self
        for name in address.names:
            if current is None:
                break

            current = current.__children.get(name)

        return current

    @override
    def get_systems(
        self,
        filter: SystemFilter | AddressSelector | None = None,
        /,
        *,
        inclusive: bool = False,
        **kwargs: Unpack[SystemFilterArgs],
    ) -> "SystemGroup":
        components: list[System] = []

        overrides = SystemFilter(**kwargs)
        if isinstance(filter, SystemFilter):
            filter = filter.with_overrides(overrides)
        elif isinstance(filter, AddressSelector):
            filter = SystemFilter(address=filter).with_overrides(overrides)
        else:
            filter = overrides

        filter = filter.with_defaults(SystemFilter(root=self.address))

        def traverse(current: System) -> None:
            if (inclusive or current is not self) and filter.matches(current):
                components.append(current)

            for component in current.__children.values():
                traverse(component)

        traverse(self)

        return SystemGroup(components)

    @override
    async def get_status(self) -> Status:
        status = await super().get_status()
        status.enabled = self.enabled
        status.connectivity = self.component.__connectivity__()
        return status

    def get_ancestors(self, *, inclusive: bool = False) -> "SystemGroup":
        """
        Return a group of all ancestor components in ascending order. If `inclusive` is `True`,
        include this component itself as the first component in the sequence.
        """
        ancestors: list[System] = []

        current: System | None = self if inclusive else self.parent
        while current is not None:
            ancestors.append(current)
            current = current.parent

        return SystemGroup(ancestors)

    def emit(
        self,
        event_cls: Callable[_EventP, _EventT],
        /,
        *args: _EventP.args,
        **kwargs: _EventP.kwargs,
    ) -> _EventT:
        """
        Construct and emit an event, assigning the address of the event to this system's address
        if unset. Emitted events are propagated to all ancestor systems and any other systems
        currently holding a reference to this system's component.
        """
        if "address" not in kwargs:
            kwargs["address"] = self.address

        return self.propagate(event_cls(*args, **kwargs))

    def propagate(self, event: _EventT) -> _EventT:
        """
        Propagate an event to all ancestor systems and any other systems currently holding a
        reference to this system's component.
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
        binding = self.component.get_action_binding(action)
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

    @property
    def jobs(self) -> list[Job]:
        """
        Get a list of all registered jobs on this system.
        """
        return list(self.__jobs.values())

    def get_job(self, name: Name) -> Job | None:
        """
        Get a registered job from this system by name. Returns `None` if the job does not exist.
        """
        return self.__jobs.get(name)

    def remove_job(self, name: Name) -> Job | None:
        """
        Remove a registered job from this system by name. Returns the removed job, or `None` if
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
        for component in reversed(self.get_ancestors()):
            component.start(all_enabled=False)

        super().start(
            on_completed=on_completed,
            on_exception=on_exception,
        )

        if all_enabled:
            for component in self.subsystems:
                if component.enabled:
                    component.start()

    @override
    async def __run__(self) -> None:
        try:
            self.__listeners = [
                _Listener(
                    system=self,
                    binding=binding,
                    handler=getattr(self.component, binding.method),
                )
                for binding in self.component.get_listener_bindings()
            ]

            for component in reversed(self.get_ancestors()):
                component.start(all_enabled=False)

            await self.__node_sync__()

            self.__scheduler.start()

            async with TaskGroup() as group:
                group.create_task(super().__run__())
                group.create_task(self.__process_events())
                group.create_task(self.__process_routines())
        except Exception:
            self.log.error("An error occurred during system execution.", exc_info=True)
            traceback.print_exc()
            raise

    async def __process_events(self) -> None:
        async with TaskGroup() as group:
            for listener in self.__listeners:
                group.create_task(listener.run())

    async def __process_routine(self, binding: "RoutineBinding") -> None:
        routine = getattr(self.component, binding.method, None)
        if routine is None:
            return

        self.emit(RoutineStartedEvent, routine=binding.method)

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
            for binding in self.component.get_routine_bindings():
                group.create_task(self.__process_routine(binding))

    @override
    async def __stop__(self) -> None:
        self.emit(StoppingEvent)
        for component in reversed(self.subsystems):
            await component.stop()

        if self.__scheduler.running:
            self.__scheduler.shutdown()

        self.emit(StoppedEvent)
        await self.flush()

        self.__listeners = []

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
            (binding := self.component.get_procedure_bindings().get(procedure)) is None
            or (method := getattr(self.component, binding.method, None)) is None
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
        binding = self.component.get_procedure_bindings()[procedure]

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
        binding = self.component.get_procedure_bindings()[procedure]

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

    def __sync_child_order(self) -> None:
        if self.__config__ is None:
            return

        order: list[System] = []
        for config in self.__config__.subsystems:
            component = self.__children.get(config.name)
            if component is not None:
                order.append(component)

        for component in self.__children.values():
            if not any(current is component for current in order):
                order.append(component)

        self.__children.clear()
        for component in order:
            self.__children[component.name] = component


class SystemGroup(Sequence[System]):
    __slots__ = (
        "__systems",
        "__identities",
    )

    def __init__(self, nodes: Iterable[System] = ()):
        self.__systems = tuple(uniquify(nodes, key=lambda current: id(current)))
        self.__identities: set[int] | None = None

    def __repr__(self) -> str:
        return f"{type(self).__name__}({repr(list(self.__systems))})"

    def __str__(self) -> str:
        return repr(self)

    @overload
    def __getitem__(self, __index: int) -> Component: ...

    @overload
    def __getitem__(self, __index: slice) -> Self: ...

    def __getitem__(self, __index: int | slice) -> "System | Self":  # type: ignore
        value = self.__systems[__index]
        if isinstance(value, tuple):
            return type(self)(value)

        return value

    def __len__(self) -> int:
        return len(self.__systems)

    def __iter__(self) -> Iterator[System]:
        return iter(self.__systems)

    def __contains__(self, other: object) -> bool:
        if not self.__systems:
            return False

        if self.__identities is None:
            self.__identities = {id(component) for component in self.__systems}

        return id(other) in self.__identities

    def reversed(self) -> Self:
        return type(self)(reversed(self.__systems))

    def start(self) -> None:
        for current in self.__systems:
            current.start()

    async def stop(self) -> None:
        for current in reversed(self.__systems):
            await current.stop()

    async def enable(self) -> None:
        for current in self.__systems:
            await current.enable()

    async def disable(self) -> None:
        for current in reversed(self.__systems):
            await current.disable()

    async def up(self) -> None:
        for current in self.__systems:
            await current.up()

    async def down(self) -> None:
        for current in reversed(self.__systems):
            await current.down()

    def __or__(self, __other: "SystemGroup") -> Self:
        return type(self)(uniquify((*self.__systems, *__other.__systems)))


@final
class _Listener:
    __slots__ = (
        "__system",
        "__binding",
        "__handler",
        "__handler_arity",
        "__queue",
    )

    def __init__(
        self,
        *,
        system: System,
        binding: ListenerBinding,
        handler: Callable[[Event], None | Awaitable[None]] | Callable[[], None | Awaitable[None]],
    ) -> None:
        self.__system = system
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
            if event.address == self.__system.address:
                return True

        if self.__binding.reference:
            for alias in self.__binding.reference:
                if self.__system.address == event.address or any(
                    system.address == event.address
                    for system in self.__system.get_referenced_systems(alias)
                ):
                    return True

        if self.__binding.address is not None:
            if self.__binding.address.matches(event.address, self.__system.address):
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
                self.__system.log.error(
                    f"An exception occurred while processing event {event}: "
                    f"{traceback.format_exc()}"
                )
            finally:
                self.__queue.task_done()

    async def settle(self) -> None:
        if self.__queue.empty():
            return

        await self.__queue.join()
