"""`StreamingOutput` read as an async context manager, outside any response."""

from collections.abc import AsyncIterator

import pytest

from ceres.component import StreamingOutput


class Producer:
    """A stream of `count` chunks recording when its cleanup and the exit hook run."""

    def __init__(self, count: int = 3, *, fail_on_close: bool = False) -> None:
        self.count = count
        self.fail_on_close = fail_on_close
        self.events: list[str] = []

    async def chunks(self) -> AsyncIterator[bytes]:
        try:
            for _ in range(self.count):
                yield b"abc"
        finally:
            self.events.append("closed")
            if self.fail_on_close:
                raise OSError("abc")

    async def exit(self) -> None:
        self.events.append("exited")

    def output(self, *, factory: bool = True) -> StreamingOutput:
        stream = self.chunks if factory else self.chunks()
        return StreamingOutput(stream, "text/plain", on_exit=self.exit)


async def read(output: StreamingOutput) -> list[bytes]:
    async with output:
        return [bytes(chunk) async for chunk in output]


async def test_leaving_early_closes_the_producer_before_the_exit_hook() -> None:
    producer = Producer()
    output = producer.output()
    async with output:
        async for _ in output:
            break
        assert producer.events == []
    assert producer.events == ["closed", "exited"]


async def test_the_exit_hook_runs_once_when_closing_fails() -> None:
    producer = Producer(fail_on_close=True)
    output = producer.output()
    with pytest.raises(OSError, match="abc"):
        async with output:
            async for _ in output:
                break
    assert producer.events == ["closed", "exited"]


def test_iterating_a_closed_output_raises() -> None:
    with pytest.raises(RuntimeError, match="async with"):
        aiter(Producer().output())


async def test_opening_an_open_output_raises() -> None:
    output = Producer().output()
    async with output:
        with pytest.raises(RuntimeError, match="already open"):
            async with output:
                pass


async def test_a_factory_stream_opens_again() -> None:
    output = Producer().output()
    assert await read(output) == [b"abc"] * 3
    assert await read(output) == [b"abc"] * 3


async def test_a_plain_stream_is_spent_after_one_pass() -> None:
    output = Producer().output(factory=False)
    assert await read(output) == [b"abc"] * 3
    assert await read(output) == []
