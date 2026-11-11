"""The host's stream release when the server cancels a pull and closes its handle."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest

from ceres import Engine
from ceres.__internal__.app.host import Host


class _Producer:
    """A stream whose cleanup awaits, so a second cancellation would cut it short."""

    def __init__(self) -> None:
        self.cleaning = asyncio.Event()
        self.events: list[str] = []

    async def chunks(self) -> AsyncIterator[bytes]:
        try:
            yield b"abc"
            await asyncio.sleep(30)
            yield b"abcd"
        finally:
            self.cleaning.set()
            await asyncio.sleep(0.01)
            self.events.append("cleaned")


async def _hooked(host: Host, producer: _Producer) -> int:
    """Register the producer's chunks under a handle with an exit hook, its first chunk read."""

    async def hook() -> None:
        producer.events.append("exit hook")

    chunks = producer.chunks()
    host._chunks[7] = chunks  # pyright: ignore[reportPrivateUsage]
    host._releases[7] = hook  # pyright: ignore[reportPrivateUsage]
    assert await host.next_chunk(7) == b"abc"
    return 7


async def _call_cancelled_first(
    host: Host, call: asyncio.Task[bytes | None], handle: int, cleaning: asyncio.Event
) -> None:
    call.cancel()
    await cleaning.wait()
    await host.stream_close(handle)


async def _closed_first(
    host: Host, call: asyncio.Task[bytes | None], handle: int, cleaning: asyncio.Event
) -> None:
    closing = asyncio.create_task(host.stream_close(handle))
    await cleaning.wait()
    call.cancel()
    await closing


@pytest.mark.parametrize("release", [_call_cancelled_first, _closed_first])
async def test_a_released_pull_lets_the_producer_finish_its_cleanup(
    release: Callable[[Host, asyncio.Task[bytes | None], int, asyncio.Event], Awaitable[None]],
) -> None:
    host = Host(Engine())
    producer = _Producer()
    handle = await _hooked(host, producer)
    call = asyncio.create_task(host.next_chunk(handle))
    await asyncio.sleep(0)

    await release(host, call, handle, producer.cleaning)

    assert producer.cleaning.is_set()
    assert producer.events == ["cleaned", "exit hook"]
    with pytest.raises(asyncio.CancelledError):
        await call
