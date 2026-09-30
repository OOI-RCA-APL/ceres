"""`rtsp` read against the `ceres dev rtsp-server` test server, run as a subprocess."""

import asyncio
import struct
import sys
from collections.abc import AsyncGenerator, AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import cast

import pytest

from ceres.rtsp import rtsp


@asynccontextmanager
async def rtsp_server(*flags: str) -> AsyncIterator[str]:
    """Serve test clips over RTSP on a free port with `flags`, yielding the stream URL."""
    process = await asyncio.create_subprocess_exec(
        *(sys.executable, "-m", "ceres", "dev", "rtsp-server", "--port", "0", *flags),
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
    reconnect: bool = True,
    stall_timeout: float | None = 10.0,
    transport: str = "tcp",
) -> Movie:
    """Read `rtsp(url)` until `fragments` fragments arrive or the stream ends."""
    output = await rtsp(url, reconnect=reconnect, stall_timeout=stall_timeout, transport=transport)
    assert callable(output.stream)
    stream = cast("AsyncGenerator[bytes]", output.stream())
    movie = Movie()
    try:
        async with asyncio.timeout(60):
            async for chunk in stream:
                movie.data += chunk
                if movie.kinds().count(b"moof") >= fragments:
                    break
    finally:
        await stream.aclose()
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


async def test_reencoding_is_not_available() -> None:
    with pytest.raises(NotImplementedError):
        await rtsp("rtsp://127.0.0.1:1/stream", copy=False)
