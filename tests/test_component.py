from asyncio import CancelledError
from collections import defaultdict
from datetime import timedelta
from typing import Any, override

import pytest

from ceres import Component, Engine, Event, Level, Ref, action, listener, query, routine
from ceres.address import Address
from ceres.component import (
    ComponentAccessLevel,
    RoutineBinding,
    RoutineRestartPolicy,
    get_procedure_bindings,
    get_routine_bindings,
)
from ceres.concurrency import sleep
from ceres.config import ComponentConfig, Config
from ceres.data import validate
from ceres.error import (
    ProcedureInternalError,
    ProcedureInvalidArgumentsError,
    ProcedureNotFoundError,
    ValidationProblem,
)
from ceres.event import (
    RoutineCancelledEvent,
    RoutineCompletedEvent,
    RoutineExceptionEvent,
    RoutineRestartedEvent,
    RoutineStartedEvent,
    RoutineStoppedEvent,
)


def test_attach_engine_top_level_component() -> None:
    engine = Engine()

    root = Component()
    engine.attach(root)
    assert engine.get_component(root.system.address) is root
    assert root.system.engine is engine


def test_attach_engine_top_level_component_system() -> None:
    engine = Engine()

    root = Component()
    engine.attach(root.system)
    assert engine.get_component(root.system.address) is root
    assert root.system.engine is engine


def test_detach_from_engine() -> None:
    engine = Engine()

    root = Component()
    engine.attach(root)
    address = root.system.address
    assert engine.get_component(address) is root
    assert root.system.engine is engine

    root.system.detach()
    assert engine.get_component(address) is None
    assert root.system.engine is None
    assert root.system.container is None

    root.system.detach()
    assert engine.get_component(address) is None
    assert root.system.engine is None
    assert root.system.container is None


@pytest.mark.parametrize(["with_engine"], [[True], [False]])
def test_tree(with_engine: bool) -> None:
    engine = Engine() if with_engine else None

    root = Component(__with_name__="root")
    child = Component(__with_name__="child")
    grandchild = Component(__with_name__="grandchild")

    if engine is not None:
        engine.attach(root)

    root.system.attach(child)
    child.system.attach(grandchild)

    assert root.system.container is engine
    assert root.system.parent is None
    assert root.system.engine is engine

    assert child.system.container is root.system
    assert child.system.parent is root.system
    assert child.system.engine is engine

    assert grandchild.system.container is child.system
    assert grandchild.system.parent is child.system
    assert grandchild.system.engine is engine

    assert root.system.children == [child.system]
    assert child.system.children == [grandchild.system]
    assert grandchild.system.children == []

    assert root.system.address == Address("@root")
    assert child.system.address == Address("@root.child")
    assert grandchild.system.address == Address("@root.child.grandchild")

    assert root.system.database is child.system.database is grandchild.system.database

    grandchild.system.detach()
    assert grandchild.system.container is None
    assert grandchild.system.parent is None
    assert child.system.children == []
    assert grandchild.system.database is not child.system.database

    child.system.detach()
    assert child.system.container is None
    assert child.system.parent is None
    assert root.system.children == []


async def test_listeners() -> None:
    class EmitterEvent(Event):
        type: str = "emitter-event"
        value: int

    class SelfEvent(Event):
        type: str = "self-event"
        value: int

    class Emitter(Component):
        pass

    class Receiver(Component):
        emitter: Ref[Emitter]

        @override
        def __setup__(self) -> None:
            self.received_emitter_events: list[EmitterEvent] = []
            self.received_self_events: list[SelfEvent] = []

        @listener(reference="emitter")
        def on__other_event(self, event: EmitterEvent) -> None:
            self.received_emitter_events.append(event)

        @listener(local=True)
        def on__self_event(self, event: SelfEvent) -> None:
            self.received_self_events.append(event)

    root = Component()
    root.system.attach(emitter := Emitter())
    root.system.attach(receiver := Receiver(emitter=emitter))

    receiver.system.start()
    emitter.system.start()

    assert root.system.running
    assert receiver.system.running
    assert emitter.system.running

    emitter.system.events.emit(EmitterEvent, value=0)
    emitter.system.events.emit(EmitterEvent, value=1)
    receiver.system.events.emit(SelfEvent, value=0)
    receiver.system.events.emit(SelfEvent, value=1)

    await root.system.stop()
    assert not root.system.running
    assert not receiver.system.running
    assert not emitter.system.running

    assert [(type(event), event.value) for event in receiver.received_emitter_events] == [
        (EmitterEvent, 0),
        (EmitterEvent, 1),
    ]
    assert [(type(event), event.value) for event in receiver.received_self_events] == [
        (SelfEvent, 0),
        (SelfEvent, 1),
    ]


async def test_alerts() -> None:
    component = Component()
    component.system.start()

    alerts = await component.system.alerts.select()
    assert len(alerts) == 0

    component.system.alerts.emit(Level.INFO, "test-alert-1")
    component.system.alerts.emit(Level.ERROR, "test-alert-2")

    await component.system.flush()
    alerts = await component.system.alerts.select()
    assert len(alerts) == 2
    assert (alerts[0].level, alerts[0].type) == (Level.INFO, "test-alert-1")
    assert (alerts[1].level, alerts[1].type) == (Level.ERROR, "test-alert-2")

    await component.system.stop()


@pytest.mark.parametrize(["decorator"], [[query], [action]])
async def test_call_no_args(decorator: Any) -> None:
    class Test(Component):
        @decorator
        async def something(self) -> int:
            return 5

    component = Test()
    assert await component.system.call("something", {}) == 5


@pytest.mark.parametrize(["decorator"], [[query], [action]])
async def test_call_with_args(decorator: Any) -> None:
    class Test(Component):
        @decorator
        async def add(self, left: int, right: int) -> int:
            return left + right

    component = Test()
    assert await component.system.call("add", {"left": 1, "right": 2}) == 3


@pytest.mark.parametrize(
    ["decorator", "kwonly"],
    [
        [query, False],
        [query, True],
        [action, False],
        [action, True],
    ],
)
async def test_call_with_kwonly_args(decorator: Any, kwonly: bool) -> None:
    class Test(Component):
        if kwonly:

            @decorator
            async def add(self, *, left: int, right: int) -> int:
                return left + right

        else:

            @decorator
            async def add(self, left: int, right: int) -> int:
                return left + right

    component = Test()
    assert await component.system.call("add", {"left": 1, "right": 2}) == 3


@pytest.mark.parametrize(
    ["decorator", "kwonly"],
    [
        [query, False],
        [query, True],
        [action, False],
        [action, True],
    ],
)
async def test_call_with_default_args(decorator: Any, kwonly: bool) -> None:
    class Test(Component):
        if kwonly:

            @decorator
            async def add(self, *, left: int = 1, right: int = 2) -> int:
                return left + right

        else:

            @decorator
            async def add(self, left: int = 1, right: int = 2) -> int:
                return left + right

    component = Test()
    assert await component.system.call("add") == 3
    assert await component.system.call("add", {}) == 3
    assert await component.system.call("add", {"left": 5}) == 7
    assert await component.system.call("add", {"right": 3}) == 4
    assert await component.system.call("add", {"left": 5, "right": 5}) == 10


@pytest.mark.parametrize(["decorator"], [[query], [action]])
async def test_procedure_does_not_exist_error(decorator: Any) -> None:
    class Test(Component):
        @decorator
        async def add(self, left: int, right: int) -> int:
            return left + right

    component = Test()
    with pytest.raises(ProcedureNotFoundError) as context:
        await component.system.call("add_missing", {"left": 1, "right": 2})

    assert context.value == ProcedureNotFoundError()


@pytest.mark.parametrize(["decorator"], [[query], [action]])
async def test_procedure_invalid_arguments_error(decorator: Any) -> None:
    class Test(Component):
        @decorator
        async def add(self, left: int, right: int) -> int:
            return left + right

    component = Test()
    with pytest.raises(ProcedureInvalidArgumentsError) as context:
        await component.system.call("add", {"left": 1})

    assert context.value == ProcedureInvalidArgumentsError(
        problems=[
            ValidationProblem(
                location=["right"],
                message="Missing required argument",
                type="missing_argument",
            )
        ],
    )


@pytest.mark.parametrize(["decorator"], [[query], [action]])
async def test_procedure_internal_error(decorator: Any) -> None:
    class Test(Component):
        @decorator
        async def test(self, left: int, right: int) -> float:
            raise Exception("whoops")

    component = Test()
    with pytest.raises(ProcedureInvalidArgumentsError):
        await component.system.call("test")

    with pytest.raises(ProcedureInternalError) as context:
        await component.system.call("test", {"left": 5, "right": 5})

    assert any('raise Exception("whoops")' in line for line in context.value.exception.traceback)


class RoutineComponent(Component):
    @override
    def __setup__(self) -> None:
        super().__setup__()
        self.count = 0
        self.emitted: defaultdict[type[Event], list[Event]] = defaultdict(list)

    @listener(local=True)
    def on__event(self, event: Event) -> None:
        for current in type(event).__mro__:
            self.emitted[current].append(event)


async def test_routines() -> None:
    class RunsOnce(RoutineComponent):
        @routine
        async def main(self) -> None:
            self.count += 1

    assert get_routine_bindings(RunsOnce) == [
        RoutineBinding(
            method="main",
            restart=RoutineRestartPolicy.NEVER,
            restart_delay=timedelta(seconds=1),
        ),
    ]

    class RunsForever(RoutineComponent):
        @routine
        async def main(self) -> None:
            while True:
                self.count += 1
                await sleep(0.001)

    assert get_routine_bindings(RunsForever) == [
        RoutineBinding(
            method="main",
            restart=RoutineRestartPolicy.NEVER,
            restart_delay=timedelta(seconds=1),
        ),
    ]

    class RestartsForever(RoutineComponent):
        @routine(restart="always", restart_delay=0.01)
        async def main(self) -> None:
            self.count += 1

    assert get_routine_bindings(RestartsForever) == [
        RoutineBinding(
            method="main",
            restart=RoutineRestartPolicy.ALWAYS,
            restart_delay=timedelta(seconds=0.01),
        ),
    ]

    class CrashesForever(RoutineComponent):
        @routine(restart="always", restart_delay=0.01)
        async def main(self) -> None:
            self.count += 1
            raise Exception("whoops")

    assert get_routine_bindings(CrashesForever) == [
        RoutineBinding(
            method="main",
            restart=RoutineRestartPolicy.ALWAYS,
            restart_delay=timedelta(seconds=0.01),
        ),
    ]

    components = [
        runs_forever := RunsForever(),
        runs_once := RunsOnce(),
        restarts_forever := RestartsForever(),
        crashes_forever := CrashesForever(),
    ]

    for component in components:
        component.system.start()

    await sleep(2)

    for component in components:
        await component.system.settle()
        await component.system.stop()
        assert not component.system.running

    assert runs_once.count == 1
    assert len(runs_once.emitted[RoutineStartedEvent]) == 1
    assert len(runs_once.emitted[RoutineStoppedEvent]) == 1
    assert len(runs_once.emitted[RoutineCompletedEvent]) == 1
    assert len(runs_once.emitted[RoutineCancelledEvent]) == 0
    assert len(runs_once.emitted[RoutineExceptionEvent]) == 0
    assert len(runs_once.emitted[RoutineRestartedEvent]) == 0

    assert 1 < runs_forever.count < 10000
    assert len(runs_forever.emitted[RoutineStartedEvent]) == 1
    assert len(runs_forever.emitted[RoutineStoppedEvent]) == 1
    assert len(runs_forever.emitted[RoutineCompletedEvent]) == 0
    assert len(runs_forever.emitted[RoutineCancelledEvent]) == 1
    assert len(runs_forever.emitted[RoutineExceptionEvent]) == 0
    assert len(runs_forever.emitted[RoutineRestartedEvent]) == 0

    assert 1 < restarts_forever.count < 10000
    assert len(restarts_forever.emitted[RoutineStartedEvent]) == 1
    assert len(restarts_forever.emitted[RoutineStoppedEvent]) == 1
    assert 1 < len(restarts_forever.emitted[RoutineCompletedEvent]) < 10000
    assert len(restarts_forever.emitted[RoutineCancelledEvent]) == 1
    assert len(restarts_forever.emitted[RoutineExceptionEvent]) == 0
    assert 1 < len(restarts_forever.emitted[RoutineRestartedEvent]) < 10000

    assert 1 < crashes_forever.count < 10000
    assert len(crashes_forever.emitted[RoutineStartedEvent]) == 1
    assert len(crashes_forever.emitted[RoutineStoppedEvent]) == 1
    assert len(crashes_forever.emitted[RoutineCompletedEvent]) == 0
    assert len(crashes_forever.emitted[RoutineCancelledEvent]) == 1
    assert 1 < len(crashes_forever.emitted[RoutineExceptionEvent]) < 10000
    assert 1 < len(crashes_forever.emitted[RoutineRestartedEvent]) < 10000


async def test_routines_wait_on_cancellation() -> None:
    from tests.testing import wait_for_condition

    class Test(Component):
        @override
        def __setup__(self) -> None:
            self.started = False
            self.count = 0
            self.cancelled = False

        @routine
        async def main(self) -> None:
            # No await sits between the flag and the try, so a cancellation seen after
            # the flag always lands inside it.
            self.started = True
            try:
                await sleep(100)
            except CancelledError:
                self.cancelled = True
                for _ in range(3):
                    await sleep(0.1)
                    self.count += 1
                raise

    component = Test()
    component.system.start()
    await wait_for_condition("the routine enters its sleep", lambda: component.started, 30)
    await component.system.stop()
    assert not component.system.running
    assert component.cancelled
    assert component.count == 3


async def test_component_access_level_ordering() -> None:
    assert ComponentAccessLevel.DENY < ComponentAccessLevel.VIEW
    assert ComponentAccessLevel.VIEW < ComponentAccessLevel.OPERATE
    assert ComponentAccessLevel.OPERATE < ComponentAccessLevel.MANAGE
    assert ComponentAccessLevel.MANAGE > ComponentAccessLevel.DENY
    assert ComponentAccessLevel.VIEW > None


async def test_component_access_level_values() -> None:
    assert ComponentAccessLevel.DENY == "deny"
    assert ComponentAccessLevel.VIEW == "view"
    assert ComponentAccessLevel.OPERATE == "operate"
    assert ComponentAccessLevel.MANAGE == "manage"


async def test_component_config_tags_default_empty() -> None:
    config = ComponentConfig(name="test")
    assert config.tags == []


async def test_component_config_tags_set() -> None:
    config = ComponentConfig(name="test", tags=["pressure", "seabird"])
    assert config.tags == ["pressure", "seabird"]


async def test_component_config_access_default_none() -> None:
    config = ComponentConfig(name="test")
    assert config.access is None


async def test_component_config_access_set() -> None:
    config = ComponentConfig(name="test", access=ComponentAccessLevel.VIEW)
    assert config.access == ComponentAccessLevel.VIEW


async def test_component_config_access_deny() -> None:
    config = ComponentConfig(name="test", access=ComponentAccessLevel.DENY)
    assert config.access == ComponentAccessLevel.DENY


def test_component_system_tags_empty_without_config() -> None:
    component = Component()
    assert component.system.tags == []


def test_component_system_tags_from_config() -> None:
    component = Component(__with_config__=ComponentConfig(name="test", tags=["pressure"]))
    assert component.system.tags == ["pressure"]


def test_component_system_access_none_without_config() -> None:
    component = Component()
    assert component.system.access is None


def test_component_system_access_from_config() -> None:
    component = Component(
        __with_config__=ComponentConfig(name="test", access=ComponentAccessLevel.OPERATE)
    )
    assert component.system.access == ComponentAccessLevel.OPERATE


def test_component_system_get_resolved_access_defaults_to_view() -> None:
    component = Component()
    assert component.system.get_resolved_access() == ComponentAccessLevel.VIEW


def test_component_system_get_resolved_access_from_own_config() -> None:
    component = Component(
        __with_config__=ComponentConfig(name="test", access=ComponentAccessLevel.MANAGE)
    )
    assert component.system.get_resolved_access() == ComponentAccessLevel.MANAGE


def test_component_system_get_resolved_access_from_ancestor() -> None:
    parent = Component(
        __with_config__=ComponentConfig(name="parent", access=ComponentAccessLevel.OPERATE)
    )
    child = Component(__with_name__="child")
    parent.system.attach(child)
    assert child.system.get_resolved_access() == ComponentAccessLevel.OPERATE


def test_component_system_get_inherited_tags_combines_ancestors() -> None:
    parent = Component(__with_config__=ComponentConfig(name="parent", tags=["site-a"]))
    child = Component(
        __with_name__="child",
        __with_config__=ComponentConfig(name="child", tags=["pressure"]),
    )
    parent.system.attach(child)
    assert child.system.get_inherited_tags() == {"site-a", "pressure"}


async def test_component_system_get_resolved_access_falls_back_to_config_default() -> None:
    engine = Engine()
    config = validate(
        Config,
        {
            "database": {"type": "sqlite"},
            "access": "operate",
            "components": [{"name": "leaf", "class": "ceres.component:Component"}],
        },
    )
    await engine.load(config, checks=())

    leaf = engine.get_component(Address("@leaf"))
    assert leaf is not None
    assert leaf.system.get_resolved_access() == ComponentAccessLevel.OPERATE

    await engine.database.dispose()


async def test_component_system_get_resolved_access_ancestor_wins_over_config_default() -> None:
    engine = Engine()
    config = validate(
        Config,
        {
            "database": {"type": "sqlite"},
            "access": "operate",
            "components": [
                {
                    "name": "parent",
                    "class": "ceres.component:Component",
                    "access": "view",
                    "components": [{"name": "child", "class": "ceres.component:Component"}],
                }
            ],
        },
    )
    await engine.load(config, checks=())

    child = engine.get_component(Address("@parent.child"))
    assert child is not None
    assert child.system.get_resolved_access() == ComponentAccessLevel.VIEW

    await engine.database.dispose()


async def test_component_system_get_resolved_access_detached_defaults_to_view() -> None:
    component = Component()
    assert component.system.engine is None
    assert component.system.get_resolved_access() == ComponentAccessLevel.VIEW


async def test_component_system_get_inherited_tags_falls_back_to_config_default() -> None:
    engine = Engine()
    config = validate(
        Config,
        {
            "database": {"type": "sqlite"},
            "tags": ["site"],
            "components": [{"name": "leaf", "class": "ceres.component:Component"}],
        },
    )
    await engine.load(config, checks=())

    leaf = engine.get_component(Address("@leaf"))
    assert leaf is not None
    assert leaf.system.get_inherited_tags() == {"site"}

    await engine.database.dispose()


async def test_component_system_get_inherited_tags_detached_has_no_config_tags() -> None:
    component = Component()
    assert component.system.engine is None
    assert component.system.get_inherited_tags() == set()


class _PermissionTestComponent:
    @query
    def default_query(self) -> str:
        return "data"

    @action
    def default_action(self) -> str:
        return "done"

    @query(permit="public")
    def public_query(self) -> str:
        return "public"

    @action(permit=ComponentAccessLevel.MANAGE)
    def manage_action(self) -> str:
        return "managed"


async def test_query_default_permission_is_view() -> None:
    bindings = get_procedure_bindings(_PermissionTestComponent)
    assert bindings["default-query"].permissions == ComponentAccessLevel.VIEW


async def test_action_default_permission_is_operate() -> None:
    bindings = get_procedure_bindings(_PermissionTestComponent)
    assert bindings["default-action"].permissions == ComponentAccessLevel.OPERATE


async def test_query_public_permission() -> None:
    bindings = get_procedure_bindings(_PermissionTestComponent)
    assert bindings["public-query"].permissions == "public"


async def test_action_custom_permission() -> None:
    bindings = get_procedure_bindings(_PermissionTestComponent)
    assert bindings["manage-action"].permissions == ComponentAccessLevel.MANAGE


def test_component_repr() -> None:
    component = Component()
    assert repr(component) == "Component()"

    child = Component(__with_name__="child")
    component.system.attach(child)
    assert repr(child) == "Component()"


async def test_status_reports_per_connection_connectivity() -> None:
    from ceres.config import ConnectionConfig
    from ceres.connectivity import Connectivity
    from ceres.data import validate

    engine = Engine()
    connection = validate(
        ConnectionConfig,
        {
            "name": "link",
            "arguments": {
                "name": "link",
                "source": {
                    "class": "ceres.TCPSource",
                    "arguments": {"host": "localhost", "port": 2999},
                },
            },
        },
    )
    config = ComponentConfig(name="wired", connections=[connection])
    component = Component(__with_name__="wired", __with_config__=config)
    engine.attach(component)

    status = await component.system.get_status()

    assert status.connectivity is None
    assert len(status.connections) == 1
    assert status.connections[0].name == "link"
    assert status.connections[0].label == "tcp://localhost:2999"
    assert status.connections[0].connectivity == Connectivity.DISCONNECTED


async def test_status_has_no_connections_without_any() -> None:
    engine = Engine()
    component = Component(__with_name__="bare")
    engine.attach(component)

    status = await component.system.get_status()

    assert status.connections == []
    assert status.connectivity is None


class _ConnectivityComponent(Component):
    @override
    def __connectivity__(self):
        from ceres.connectivity import Connectivity

        return Connectivity.CONNECTED


async def test_status_uses_defined_connectivity_override() -> None:
    from ceres.connectivity import Connectivity

    engine = Engine()
    component = _ConnectivityComponent(__with_name__="explicit")
    engine.attach(component)

    status = await component.system.get_status()

    assert status.connectivity == Connectivity.CONNECTED
