"""How a procedure returning a file or a stream reports the end of its call."""

from collections import defaultdict
from collections.abc import AsyncIterable, AsyncIterator
from typing import TYPE_CHECKING, override

import pytest

from ceres import Component, action, listener, query
from ceres.component import FileOutput, StreamingOutput
from ceres.error import ProcedureInternalError
from ceres.event import (
    Event,
    ProcedureCalledEvent,
    ProcedureCancelledEvent,
    ProcedureCompletedEvent,
    ProcedureExceptionEvent,
)

if TYPE_CHECKING:
    from pathlib import Path

ENDS = (ProcedureCompletedEvent, ProcedureCancelledEvent, ProcedureExceptionEvent)


class Outputs(Component):
    @override
    def __setup__(self) -> None:
        super().__setup__()
        self.emitted: defaultdict[type[Event], list[Event]] = defaultdict(list)

    @listener(local=True)
    def on__event(self, event: Event) -> None:
        self.emitted[type(event)].append(event)

    async def ends(self) -> list[type[Event]]:
        await self.system.settle()
        return [kind for kind in ENDS for _ in self.emitted[kind]]

    @query(media="text/plain")
    async def chunks(self, count: int = 3, fail: bool = False) -> StreamingOutput:
        async def stream() -> AsyncIterator[bytes]:
            for _ in range(count):
                yield b"abc"
            if fail:
                raise ConnectionError("lost")

        return StreamingOutput(stream, "text/plain")

    @action
    async def counting(self) -> AsyncIterable[int]:
        yield 1
        raise ValueError("abc")

    @query(media="text/plain")
    async def file(self, path: str) -> FileOutput:
        return FileOutput(path, "text/plain")


@pytest.fixture
async def component() -> AsyncIterator[Outputs]:
    component = Outputs()
    component.system.start()
    yield component
    await component.system.stop()


async def call(component: Outputs, procedure: str, **arguments: object) -> StreamingOutput:
    output = await component.system.call(procedure, arguments)
    assert isinstance(output, StreamingOutput)
    return output


async def test_a_stream_read_to_its_end_completes_the_call(component: Outputs) -> None:
    output = await call(component, "chunks")
    assert await component.ends() == []
    assert len(component.emitted[ProcedureCalledEvent]) == 1

    async with output:
        assert [bytes(chunk) async for chunk in output] == [b"abc"] * 3
        assert await component.ends() == []

    assert await component.ends() == [ProcedureCompletedEvent]


async def test_a_stream_raising_while_read_fails_the_call(component: Outputs) -> None:
    output = await call(component, "chunks", fail=True)
    try:
        async with output:
            async for _ in output:
                pass
    except ConnectionError:
        pass

    assert await component.ends() == [ProcedureExceptionEvent]
    event = component.emitted[ProcedureExceptionEvent][0]
    assert isinstance(event, ProcedureExceptionEvent)
    assert event.procedure == "chunks"
    assert any("lost" in line for line in event.exception.traceback)


async def test_a_stream_closed_before_its_end_cancels_the_call(component: Outputs) -> None:
    output = await call(component, "chunks")
    async with output:
        async for _ in output:
            break

    assert await component.ends() == [ProcedureCancelledEvent]


async def test_only_the_first_close_ends_the_call(component: Outputs) -> None:
    output = await call(component, "chunks")
    for _ in range(2):
        async with output:
            async for _ in output:
                pass

    assert await component.ends() == [ProcedureCompletedEvent]


async def test_an_unopened_stream_never_ends_the_call(component: Outputs) -> None:
    await call(component, "chunks")
    assert await component.ends() == []


async def test_a_stream_not_returned_by_a_procedure_reports_nothing(component: Outputs) -> None:
    output = await component.chunks()
    async with output:
        async for _ in output:
            pass

    assert await component.ends() == []


async def test_a_returned_file_completes_the_call(component: Outputs, tmp_path: Path) -> None:
    (path := tmp_path / "file.txt").write_text("abc")
    output = await component.system.call("file", {"path": str(path)})
    assert isinstance(output, FileOutput)
    assert await component.ends() == [ProcedureCompletedEvent]


async def test_a_live_action_raising_ends_its_call_once(component: Outputs) -> None:
    try:
        await component.system.call("counting")
    except ProcedureInternalError:
        pass

    assert await component.ends() == [ProcedureExceptionEvent]


async def test_a_reopened_stream_keeps_its_procedure(component: Outputs) -> None:
    output = await call(component, "chunks")
    for _ in range(2):
        async with output:
            async for _ in output:
                pass

    assert output._procedure == "chunks"  # noqa: SLF001
    assert output._component is component.system  # noqa: SLF001
