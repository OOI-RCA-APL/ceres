from dataclasses import field
from typing import Any

import pytest

from ceres import Alerter, Component, Event, Level, Ref, on, query
from ceres.errors import (
    ProcedureDoesNotExistError,
    ProcedureInternalError,
    ProcedureInvalidArgsError,
)
from ceres.exceptions import ProcedureException
from ceres.procedure import action
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

        received_emitter_events: list[EmitterEvent] = field(default_factory=list)
        received_self_events: list[SelfEvent] = field(default_factory=list)

        @on(EmitterEvent, "emitter")
        def _on_other_event(self, event: EmitterEvent) -> None:
            self.received_emitter_events.append(event)

        @on(SelfEvent)
        def _on_self_event(self, event: SelfEvent) -> None:
            self.received_self_events.append(event)

    emitter = Emitter()
    receiver = Receiver(emitter=emitter)

    receiver.start()
    emitter.start()

    emitter.emit_event(EmitterEvent, value=0)
    emitter.emit_event(EmitterEvent, value=1)
    receiver.emit_event(SelfEvent, value=0)
    receiver.emit_event(SelfEvent, value=1)

    await receiver.settle()
    await emitter.settle()
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
    class Test(Alerter):
        pass

    component = Test()
    component.start()
    component.emit_alert(Level.ERROR, "test-alert-1")
    component.emit_alert(Level.ERROR, "test-alert-2")

    await component.settle()
    assert len(await component.environment.get_alerts()) == 2
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
                message="field required",
                kind="value_error.missing",
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
