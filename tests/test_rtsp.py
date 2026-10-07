"""`rtsp` read against the `ceres-rtsp-server` test server, run as a subprocess."""

import asyncio
import json
import struct
import subprocess
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import override

import pytest

from ceres import Component, listener, query
from ceres.component import StreamingOutput
from ceres.event import (
    Event,
    StreamLostEvent,
    StreamReconnectedEvent,
    StreamReconnectScheduledEvent,
)
from ceres.rtsp import rtsp


@cache
def rtsp_server_executable() -> str:
    """Build the test server once per process, returning the path cargo reports for it."""
    messages = subprocess.run(
        ["cargo", "build", "-p", "ceres-rtsp-server", "--message-format=json"],
        cwd=Path(__file__).parents[1] / "rust",
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return next(
        message["executable"]
        for message in map(json.loads, messages.splitlines())
        if message.get("reason") == "compiler-artifact"
        and message["target"]["name"] == "ceres-rtsp-server"
    )


@asynccontextmanager
async def rtsp_server(*flags: str) -> AsyncIterator[str]:
    """Serve test clips over RTSP on a free port with `flags`, yielding the stream URL."""
    process = await asyncio.create_subprocess_exec(
        *(rtsp_server_executable(), "--port", "0", *flags),
        stdout=asyncio.subprocess.PIPE,
    )
    try:
        assert process.stdout is not None
        line = await asyncio.wait_for(process.stdout.readline(), 30)
        yield line.decode().strip()
    finally:
        process.kill()
        await process.wait()


def boxes(data: bytes) -> Iterator[tuple[bytes, bytes]]:
    """The complete MP4 boxes in `data` as type and payload, stopping at a partial one."""
    offset = 0
    while offset + 8 <= len(data):
        size, kind = struct.unpack_from(">I4s", data, offset)
        if size < 8 or offset + size > len(data):
            return
        yield kind, data[offset + 8 : offset + size]
        offset += size


@dataclass
class Movie:
    """The fragmented MP4 a client read, in the order it arrived."""

    data: bytes = b""

    def kinds(self) -> list[bytes]:
        return [kind for kind, _ in boxes(self.data)]

    def codec(self) -> bytes:
        moov = next(payload for kind, payload in boxes(self.data) if kind == b"moov")
        return next(codec for codec in (b"avc1", b"hvc1", b"hev1") if codec in moov)

    def decode_times(self) -> list[int]:
        """Each fragment's `tfdt` base decode time."""
        return [
            struct.unpack_from(">Q" if tfdt[0] else ">I", tfdt, 4)[0]
            for kind, moof in boxes(self.data)
            if kind == b"moof"
            for traf_kind, traf in boxes(moof)
            if traf_kind == b"traf"
            for tfdt_kind, tfdt in boxes(traf)
            if tfdt_kind == b"tfdt"
        ]


async def watch(
    url: str,
    *,
    fragments: int,
    copy: bool = True,
    reconnect: bool = True,
    stall_timeout: float | None = 10.0,
    transport: str = "tcp",
) -> Movie:
    """Read `rtsp(url)` until `fragments` fragments arrive or the stream ends."""
    output = await rtsp(
        url, copy=copy, reconnect=reconnect, stall_timeout=stall_timeout, transport=transport
    )
    movie = Movie()
    async with asyncio.timeout(60), output:
        async for chunk in output:
            movie.data += chunk
            if movie.kinds().count(b"moof") >= fragments:
                break
    return movie


def assert_one_timeline(movie: Movie, fragments: int) -> None:
    """One init segment, then `fragments` fragments whose decode times only increase."""
    assert movie.kinds().count(b"moov") == 1
    times = movie.decode_times()
    assert len(times) >= fragments
    assert times == sorted(set(times))


async def test_streams_h264_as_fragmented_mp4() -> None:
    async with rtsp_server() as url:
        movie = await watch(url, fragments=10)
    assert movie.kinds()[:2] == [b"ftyp", b"moov"]
    assert movie.codec() == b"avc1"
    assert_one_timeline(movie, 10)


async def test_streams_h265_tagged_for_safari() -> None:
    async with rtsp_server("--clip", "h265") as url:
        movie = await watch(url, fragments=10)
    assert movie.codec() == b"hvc1"
    assert_one_timeline(movie, 10)


# Each fault lands about a second into the session, and 40 fragments of 50 ms
# or more need the reconnected session to deliver the rest.
@pytest.mark.parametrize(
    "flags",
    [
        ("--drop-after", "1"),
        ("--stall-after", "1"),
        ("--restart-after", "1", "--restart-downtime", "1"),
    ],
    ids=["drop", "stall", "restart"],
)
async def test_lost_camera_continues_one_timeline(flags: tuple[str, ...]) -> None:
    async with rtsp_server(*flags) as url:
        movie = await watch(url, fragments=40, stall_timeout=1.0)
    assert_one_timeline(movie, 40)


async def test_lost_camera_without_reconnect_ends_the_stream() -> None:
    async with rtsp_server("--drop-after", "1") as url:
        movie = await watch(url, fragments=1000, reconnect=False)
    assert 0 < len(movie.decode_times()) < 1000


async def test_missing_stream_without_reconnect_is_an_error() -> None:
    async with rtsp_server() as url:
        with pytest.raises(ConnectionError, match="404"):
            await watch(url.replace("/stream", "/missing"), fragments=1, reconnect=False)


async def test_unknown_transport_is_an_error() -> None:
    with pytest.raises(ValueError, match="transport"):
        await watch("rtsp://127.0.0.1:1/stream", fragments=1, transport="http")


async def test_reencodes_h265_as_h264_across_a_lost_camera() -> None:
    async with rtsp_server("--clip", "h265", "--drop-after", "1") as url:
        movie = await watch(url, fragments=40, copy=False, stall_timeout=1.0)
    assert movie.codec() == b"avc1"
    assert_one_timeline(movie, 40)


async def test_streams_of_one_camera_share_its_session() -> None:
    async with rtsp_server("--max-sessions", "1") as url:
        first, second = await asyncio.gather(watch(url, fragments=20), watch(url, fragments=20))
    assert_one_timeline(first, 20)
    assert_one_timeline(second, 20)


class Camera(Component):
    """A camera whose stream reports how it fares."""

    @override
    def __setup__(self) -> None:
        super().__setup__()
        self.url = ""
        self.emitted: list[Event] = []

    @listener(local=True)
    def on__event(self, event: Event) -> None:
        if event.type.startswith("stream-"):
            self.emitted.append(event)

    @query(media="video/mp4")
    async def video(self) -> StreamingOutput:
        return await rtsp(self.url, stall_timeout=1.0)


async def read_for(output: StreamingOutput, fragments: int) -> None:
    movie = Movie()
    async with asyncio.timeout(60), output:
        async for chunk in output:
            movie.data += chunk
            if movie.kinds().count(b"moof") >= fragments:
                break


@pytest.fixture
async def camera() -> AsyncIterator[Camera]:
    camera = Camera()
    camera.system.start()
    yield camera
    await camera.system.stop()


async def test_a_returned_stream_reports_a_lost_camera_on_its_component(camera: Camera) -> None:
    async with rtsp_server("--restart-after", "1", "--restart-downtime", "1") as url:
        camera.url = url
        output = await camera.system.call("video", {})
        assert isinstance(output, StreamingOutput)
        await read_for(output, 60)
    await camera.system.settle()
    kinds = [type(event) for event in camera.emitted]
    assert kinds == [StreamLostEvent, StreamReconnectScheduledEvent, StreamReconnectedEvent]
    assert all(getattr(event, "procedure", None) == "video" for event in camera.emitted)
    reconnected = camera.emitted[-1]
    assert isinstance(reconnected, StreamReconnectedEvent)
    assert reconnected.attempts >= 1
    assert reconnected.outage.total_seconds() >= 0.5


async def test_a_stream_reports_on_the_component_it_was_given(camera: Camera) -> None:
    async with rtsp_server("--drop-after", "1") as url:
        output = await rtsp(url, component=camera)
        await read_for(output, 40)
    await camera.system.settle()
    assert StreamLostEvent in [type(event) for event in camera.emitted]
    assert all(getattr(event, "procedure", "") is None for event in camera.emitted)


async def test_an_unbound_stream_reports_nothing(camera: Camera) -> None:
    async with rtsp_server("--drop-after", "1") as url:
        await read_for(await rtsp(url), 40)
    await camera.system.settle()
    assert camera.emitted == []
