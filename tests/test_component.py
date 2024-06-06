import asyncio
from collections import defaultdict
from datetime import timedelta
from typing import Any, override

import pytest

from ceres import Component, Event, Level, Ref, action, listener, query
from ceres.component import (
    RoutineBinding,
    RoutineRestartPolicy,
    get_component_routine_bindings,
    routine,
)
from ceres.error import (
    Failure,
    ProcedureInternalError,
    ProcedureInvalidArgumentsError,
    ProcedureNotFoundError,
)
from ceres.event import (
    RoutineCancelledEvent,
    RoutineCompletedEvent,
    RoutineExceptionEvent,
    RoutineRestartedEvent,
    RoutineStartedEvent,
    RoutineStoppedEvent,
)
from ceres.validation import ValidationProblem


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

    alerts = await component.system.alerts.get_all()
    assert len(alerts) == 0

    component.system.alerts.emit(Level.INFO, "test-alert-1")
    component.system.alerts.emit(Level.ERROR, "test-alert-2")

    await component.system.flush()
    alerts = await component.system.alerts.get_all()
    assert len(alerts) == 2
    assert (alerts[0].level, alerts[0].code) == (Level.INFO, "test-alert-1")
    assert (alerts[1].level, alerts[1].code) == (Level.ERROR, "test-alert-2")

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
    with pytest.raises(Failure) as context:
        await component.system.call("add_missing", {"left": 1, "right": 2})

    assert context.value.error == ProcedureNotFoundError()


@pytest.mark.parametrize(["decorator"], [[query], [action]])
async def test_procedure_invalid_arguments_error(decorator: Any) -> None:
    class Test(Component):
        @decorator
        async def add(self, left: int, right: int) -> int:
            return left + right

    component = Test()
    with pytest.raises(Failure) as context:
        await component.system.call("add", {"left": 1})

    assert context.value.error == ProcedureInvalidArgumentsError(
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
    with pytest.raises(Failure) as context:
        await component.system.call("test")

    assert isinstance(context.value.error, ProcedureInvalidArgumentsError)

    with pytest.raises(Failure) as context:
        await component.system.call("test", {"left": 5, "right": 5})

    assert isinstance(context.value.error, ProcedureInternalError)
    assert any('raise Exception("whoops")' in line for line in context.value.error.traceback)


class RoutineComponent(Component):
    @override
    def __setup__(self) -> None:
        super().__setup__()
        self.count = 0
        self.emitted: defaultdict[type[Event], list[Event]] = defaultdict(list)

    @listener(local=True)
    def on__event(self, event: Event) -> None:
        self.emitted[type(event)].append(event)


async def test_routines() -> None:
    class RunsOnce(RoutineComponent):
        @routine
        async def main(self) -> None:
            self.count += 1

    assert get_component_routine_bindings(RunsOnce) == [
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
                await asyncio.sleep(0.001)

    assert get_component_routine_bindings(RunsForever) == [
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

    assert get_component_routine_bindings(RestartsForever) == [
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

    assert get_component_routine_bindings(CrashesForever) == [
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

    await asyncio.sleep(1)

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

    # TODO: Fix in CI for Python 3.10.
    assert 1 < crashes_forever.count < 10000
    assert len(crashes_forever.emitted[RoutineStartedEvent]) == 1
    assert len(crashes_forever.emitted[RoutineStoppedEvent]) == 1
    assert len(crashes_forever.emitted[RoutineCompletedEvent]) == 0
    assert len(crashes_forever.emitted[RoutineCancelledEvent]) == 1
    assert 1 < len(crashes_forever.emitted[RoutineExceptionEvent]) < 10000
    assert 1 < len(crashes_forever.emitted[RoutineRestartedEvent]) < 10000
