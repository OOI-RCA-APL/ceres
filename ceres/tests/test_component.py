import asyncio
from collections import defaultdict
from datetime import timedelta
from typing import TYPE_CHECKING, Any, TypeVar

import pytest

from ceres import Component, Event, Level, Ref, action, on, query
from ceres.component import ComponentGroup, RoutineBinding, RoutineRestartPolicy, routine
from ceres.errors import (
    ProcedureDoesNotExistError,
    ProcedureInternalError,
    ProcedureInvalidArgsError,
)
from ceres.events import (
    RoutineCancelledEvent,
    RoutineCompletedEvent,
    RoutineExceptionEvent,
    RoutineRestartedEvent,
    RoutineStartedEvent,
    RoutineStoppedEvent,
)
from ceres.exceptions import ProcedureException
from ceres.validation import ValidationProblem


async def test_event_listeners() -> None:
    class EmitterEvent(Event):
        kind: str = "emitter-event"
        value: int

    class SelfEvent(Event):
        kind: str = "self-event"
        value: int

    class Emitter(Component):
        pass

    class Receiver(Component):
        emitter: Ref[Emitter]

        def __setup__(self) -> None:
            self.received_emitter_events: list[EmitterEvent] = []
            self.received_self_events: list[SelfEvent] = []

        @on(reference="emitter")
        def on__other_event(self, event: EmitterEvent) -> None:
            self.received_emitter_events.append(event)

        @on(local=True)
        def on__self_event(self, event: SelfEvent) -> None:
            self.received_self_events.append(event)

    emitter = Emitter()
    receiver = Receiver(emitter=emitter)

    receiver.start()
    emitter.start()

    emitter.emit(EmitterEvent, value=0)
    emitter.emit(EmitterEvent, value=1)
    receiver.emit(SelfEvent, value=0)
    receiver.emit(SelfEvent, value=1)

    await receiver.settle()
    await emitter.settle()
    await receiver.stop()
    await emitter.stop()

    assert [(type(event), event.value) for event in receiver.received_emitter_events] == [
        (EmitterEvent, 0),
        (EmitterEvent, 1),
    ]
    assert [(type(event), event.value) for event in receiver.received_self_events] == [
        (SelfEvent, 0),
        (SelfEvent, 1),
    ]

    await emitter.stop()
    await receiver.stop()


async def test_component_alerts() -> None:
    class Test(Component):
        pass

    component = Test()
    component.start()

    alerts = await component.get_alerts()
    assert len(alerts) == 0

    component.alert(Level.INFO, "test-alert-1")
    component.alert(Level.ERROR, "test-alert-2")

    await component.flush()
    alerts = await component.get_alerts()
    assert len(alerts) == 2
    assert (alerts[0].level, alerts[0].code) == (Level.INFO, "test-alert-1")
    assert (alerts[1].level, alerts[1].code) == (Level.ERROR, "test-alert-2")

    await component.stop()


@pytest.mark.parametrize(["decorator"], [[query], [action]])
async def test_component_procedure_no_args(decorator: Any) -> None:
    class Test(Component):
        @decorator
        async def something(self) -> int:
            return 5

    component = Test()
    assert await component.call("something", {}) == 5


@pytest.mark.parametrize(["decorator"], [[query], [action]])
async def test_component_procedure_with_args(decorator: Any) -> None:
    class Test(Component):
        @decorator
        async def add(self, left: int, right: int) -> int:
            return left + right

    component = Test()
    assert await component.call("add", {"left": 1, "right": 2}) == 3


@pytest.mark.parametrize(["decorator"], [[query], [action]])
async def test_component_procedure_with_default_args(decorator: Any) -> None:
    class Test(Component):
        @decorator
        async def add(self, left: int = 1, right: int = 2) -> int:
            return left + right

    component = Test()
    assert await component.call("add") == 3
    assert await component.call("add", {}) == 3
    assert await component.call("add", {"left": 5}) == 7
    assert await component.call("add", {"right": 3}) == 4
    assert await component.call("add", {"left": 5, "right": 5}) == 10


@pytest.mark.parametrize(["decorator"], [[query], [action]])
async def test_component_procedure_does_not_exist_error(decorator: Any) -> None:
    class Test(Component):
        @decorator
        async def add(self, left: int, right: int) -> int:
            return left + right

    component = Test()
    with pytest.raises(ProcedureException) as context:
        await component.call("add_missing", {"left": 1, "right": 2})

    assert context.value.error == ProcedureDoesNotExistError()


@pytest.mark.parametrize(["decorator"], [[query], [action]])
async def test_component_procedure_invalid_args_error(decorator: Any) -> None:
    class Test(Component):
        @decorator
        async def add(self, left: int, right: int) -> int:
            return left + right

    component = Test()
    with pytest.raises(ProcedureException) as context:
        await component.call("add", {"left": 1})

    assert context.value.error == ProcedureInvalidArgsError(
        problems=[
            ValidationProblem(
                location=["right"],
                message="Missing required argument",
                kind="missing_argument",
            )
        ],
    )


@pytest.mark.parametrize(["decorator"], [[query], [action]])
async def test_component_procedure_internal_error(decorator: Any) -> None:
    class Test(Component):
        @decorator
        async def test(self, left: int, right: int) -> float:
            raise Exception("whoops")

    component = Test()
    with pytest.raises(ProcedureException) as context:
        await component.call("test")

    assert isinstance(context.value.error, ProcedureInvalidArgsError)

    with pytest.raises(ProcedureException) as context:
        await component.call("test", {"left": 5, "right": 5})

    assert isinstance(context.value.error, ProcedureInternalError)
    assert any('raise Exception("whoops")' in line for line in context.value.error.traceback)


_EventT = TypeVar("_EventT", bound=Event)


class RoutineComponent(Component):
    def __setup__(self) -> None:
        super().__setup__()
        self.count = 0
        self.emitted: defaultdict[type[Event], list[Event]] = defaultdict(list)

    if not TYPE_CHECKING:

        def emit(self, *args, **kwargs) -> _EventT:
            event = super().emit(*args, **kwargs)
            self.emitted[type(event)].append(event)
            return event


async def test_routines() -> None:
    class RunsOnce(RoutineComponent):
        @routine
        async def main(self) -> None:
            self.count += 1

    assert RunsOnce.get_routine_bindings() == [
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

    assert RunsForever.get_routine_bindings() == [
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

    assert RestartsForever.get_routine_bindings() == [
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

    assert CrashesForever.get_routine_bindings() == [
        RoutineBinding(
            method="main",
            restart=RoutineRestartPolicy.ALWAYS,
            restart_delay=timedelta(seconds=0.01),
        ),
    ]

    components = ComponentGroup(
        [
            runs_forever := RunsForever(),
            runs_once := RunsOnce(),
            restarts_forever := RestartsForever(),
            crashes_forever := CrashesForever(),
        ]
    )

    components.start()

    await asyncio.sleep(0.5)

    await components.stop()

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
