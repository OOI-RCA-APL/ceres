import asyncio
from collections.abc import AsyncGenerator
from typing import cast

import pytest

import ceres.rtsp
from ceres.rtsp import _FragmentSplicer, rtsp


def box(box_type: bytes, payload: bytes) -> bytes:
    """Build an ISO BMFF box from its type and payload."""
    return (8 + len(payload)).to_bytes(4, "big") + box_type + payload


def full_box(box_type: bytes, version: int, payload: bytes) -> bytes:
    """Build a full box, whose payload starts with a version byte and three flag bytes."""
    return box(box_type, bytes([version, 0, 0, 0]) + payload)


def mfhd(sequence_number: int) -> bytes:
    return full_box(b"mfhd", 0, sequence_number.to_bytes(4, "big"))


def tfhd(track_id: int) -> bytes:
    return full_box(b"tfhd", 0, track_id.to_bytes(4, "big"))


def tfdt(base_time: int, *, version: int = 0) -> bytes:
    width = 8 if version == 1 else 4
    return full_box(b"tfdt", version, base_time.to_bytes(width, "big"))


def traf(track_id: int, base_time: int, *, version: int = 0) -> bytes:
    return box(b"traf", tfhd(track_id) + tfdt(base_time, version=version))


def moof(sequence_number: int, *trafs: bytes) -> bytes:
    return box(b"moof", mfhd(sequence_number) + b"".join(trafs))


def ftyp() -> bytes:
    return box(b"ftyp", b"isom\x00\x00\x02\x00isomiso2")


def moov() -> bytes:
    return box(b"moov", b"\x00" * 24)


def mdat(data: bytes = b"frame") -> bytes:
    return box(b"mdat", data)


def test_first_session_passes_through_byte_identical() -> None:
    splicer = _FragmentSplicer()
    data = ftyp() + moov() + moof(1, traf(1, 0)) + mdat() + moof(2, traf(1, 3000)) + mdat(b"two")
    middle = len(data) // 2
    output = splicer.feed(data[:middle]) + splicer.feed(data[middle:])
    assert output == data


def test_first_session_passes_through_fed_byte_by_byte() -> None:
    splicer = _FragmentSplicer()
    data = ftyp() + moov() + moof(1, traf(1, 0)) + mdat()
    output = b"".join(splicer.feed(data[index : index + 1]) for index in range(len(data)))
    assert output == data


def test_respawned_session_drops_init_segment() -> None:
    splicer = _FragmentSplicer()
    splicer.feed(ftyp() + moov() + moof(1, traf(1, 0)) + mdat())
    splicer.start_new_session()
    output = splicer.feed(ftyp() + moov() + moof(1, traf(1, 0)) + mdat())
    assert output == moof(2, traf(1, 0)) + mdat()


def test_respawned_session_continues_timeline() -> None:
    splicer = _FragmentSplicer()
    splicer.feed(moof(1, traf(1, 0)) + mdat() + moof(2, traf(1, 3000)) + mdat())
    splicer.start_new_session()
    output = splicer.feed(moof(1, traf(1, 0)) + mdat() + moof(2, traf(1, 3000)) + mdat())
    assert output == moof(3, traf(1, 6000)) + mdat() + moof(4, traf(1, 9000)) + mdat()


def test_timeline_stays_monotonic_across_three_sessions() -> None:
    splicer = _FragmentSplicer()
    splicer.feed(moof(1, traf(1, 0)) + moof(2, traf(1, 3000)))
    splicer.start_new_session()
    assert splicer.feed(moof(1, traf(1, 0)) + moof(2, traf(1, 3000))) == moof(
        3, traf(1, 6000)
    ) + moof(4, traf(1, 9000))
    splicer.start_new_session()
    assert splicer.feed(moof(1, traf(1, 0))) == moof(5, traf(1, 12000))


def test_single_fragment_session_accepts_overlap() -> None:
    splicer = _FragmentSplicer()
    splicer.feed(moof(1, traf(1, 5000)))
    splicer.start_new_session()
    # With only one fragment ever seen, its duration is unknown, so the new session starts at
    # the old fragment's time and the small overlap is accepted.
    assert splicer.feed(moof(1, traf(1, 0))) == moof(2, traf(1, 5000))


def test_version_1_tfdt_patched() -> None:
    splicer = _FragmentSplicer()
    base = 2**33
    splicer.feed(moof(1, traf(1, base, version=1)) + moof(2, traf(1, base + 6000, version=1)))
    splicer.start_new_session()
    output = splicer.feed(moof(1, traf(1, 0, version=1)))
    assert output == moof(3, traf(1, base + 12000, version=1))


def test_tracks_tracked_independently() -> None:
    splicer = _FragmentSplicer()
    splicer.feed(moof(1, traf(1, 0), traf(2, 0)) + moof(2, traf(1, 3000), traf(2, 1024)))
    splicer.start_new_session()
    output = splicer.feed(moof(1, traf(1, 0), traf(2, 0)))
    assert output == moof(3, traf(1, 6000), traf(2, 2048))


def test_size_zero_box_switches_to_passthrough() -> None:
    splicer = _FragmentSplicer()
    prefix = ftyp()
    unbounded = (0).to_bytes(4, "big") + b"mdat" + b"anything goes from here"
    assert splicer.feed(prefix + unbounded) == prefix + unbounded
    assert splicer.feed(b"still raw") == b"still raw"


def test_oversized_box_switches_to_passthrough() -> None:
    splicer = _FragmentSplicer()
    oversized = (64 * 1024 * 1024).to_bytes(4, "big") + b"mdat" + b"tiny start of a huge box"
    assert splicer.feed(oversized) == oversized
    assert splicer.feed(b"still raw") == b"still raw"


def test_largesize_box_passes_through() -> None:
    splicer = _FragmentSplicer()
    payload = b"large payload"
    largesize = (1).to_bytes(4, "big") + b"mdat" + (16 + len(payload)).to_bytes(8, "big") + payload
    # Split inside the 16-byte header to prove the largesize is buffered correctly.
    output = splicer.feed(largesize[:10]) + splicer.feed(largesize[10:])
    assert output == largesize


class FakeStdout:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)

    async def read(self, size: int = -1) -> bytes:
        if self._chunks:
            return self._chunks.pop(0)

        return b""


class FakeProcess:
    def __init__(self, chunks: list[bytes]) -> None:
        self.stdout = FakeStdout(chunks)
        self.killed = False

    def kill(self) -> None:
        self.killed = True


def install_fake_ffmpeg(
    monkeypatch: pytest.MonkeyPatch, sessions: list[list[bytes] | Exception]
) -> list[FakeProcess]:
    """Replace subprocess spawning with a factory replaying scripted stdout sessions.

    Each entry in `sessions` is either the chunks one spawned process emits before EOF, or an
    exception the spawn itself raises. Spawning more times than scripted fails the test.

    Returns:
        The list of processes spawned so far, appended to live.
    """
    spawned: list[FakeProcess] = []
    remaining = list(sessions)

    async def create(*command: str, **kwargs: object) -> FakeProcess:
        assert remaining, "`ffmpeg` respawned more times than the test scripted"
        session = remaining.pop(0)
        if isinstance(session, Exception):
            raise session

        process = FakeProcess(session)
        spawned.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    return spawned


def install_instant_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Make the module's `sleep` return immediately, recording each requested delay."""
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(ceres.rtsp, "sleep", fake_sleep)
    return delays


def install_fake_clock(monkeypatch: pytest.MonkeyPatch, times: list[float]) -> None:
    """Make the module's `monotonic` return scripted times, repeating the last one."""
    iterator = iter(times)
    monkeypatch.setattr(ceres.rtsp, "monotonic", lambda: next(iterator, times[-1]))


async def start_stream(*, reconnect: bool = True) -> AsyncGenerator[bytes]:
    output = await rtsp("rtsp://camera.test/stream", ffmpeg="ffmpeg", reconnect=reconnect)
    stream = output.stream
    assert callable(stream)
    return cast("AsyncGenerator[bytes]", stream())


async def collect(stream: AsyncGenerator[bytes], length: int) -> bytes:
    """Pull from `stream` until at least `length` bytes arrive, then close it."""
    collected = bytearray()
    try:
        async for chunk in stream:
            collected += chunk
            if len(collected) >= length:
                break
    finally:
        await stream.aclose()

    return bytes(collected)


async def test_stream_splices_across_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    session_one = (
        ftyp() + moov() + moof(1, traf(1, 0)) + mdat() + moof(2, traf(1, 3000)) + mdat(b"two")
    )
    session_two = ftyp() + moov() + moof(1, traf(1, 0)) + mdat(b"three")
    spawned = install_fake_ffmpeg(
        monkeypatch,
        [[session_one[:20], session_one[20:]], [session_two]],
    )
    install_instant_sleep(monkeypatch)

    expected = session_one + moof(3, traf(1, 6000)) + mdat(b"three")
    stream = await start_stream()
    output = await collect(stream, len(expected))

    assert output == expected
    assert len(spawned) == 2
    assert all(process.killed for process in spawned)


async def test_closing_consumer_kills_ffmpeg_and_stops_respawning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = ftyp() + moov() + moof(1, traf(1, 0)) + mdat()
    spawned = install_fake_ffmpeg(monkeypatch, [[data, data]])
    install_instant_sleep(monkeypatch)

    stream = await start_stream()
    assert await anext(stream) == data
    await stream.aclose()

    assert len(spawned) == 1
    assert spawned[0].killed


async def test_reconnect_false_preserves_single_session(monkeypatch: pytest.MonkeyPatch) -> None:
    data = ftyp() + moov() + moof(1, traf(1, 0)) + mdat()
    spawned = install_fake_ffmpeg(monkeypatch, [[data]])
    delays = install_instant_sleep(monkeypatch)

    stream = await start_stream(reconnect=False)
    collected = bytearray()
    async for chunk in stream:
        collected += chunk

    assert bytes(collected) == data
    assert len(spawned) == 1
    assert spawned[0].killed
    # Only event-loop yields happen, never a backoff wait.
    assert all(delay == 0 for delay in delays)


async def test_reconnect_false_spawn_failure_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_ffmpeg(monkeypatch, [OSError("boom")])
    install_instant_sleep(monkeypatch)

    stream = await start_stream(reconnect=False)
    with pytest.raises(OSError, match="boom"):
        await anext(stream)


async def test_spawn_failure_respawns(monkeypatch: pytest.MonkeyPatch) -> None:
    data = moof(1, traf(1, 0)) + mdat()
    spawned = install_fake_ffmpeg(monkeypatch, [OSError("boom"), [data]])
    delays = install_instant_sleep(monkeypatch)

    stream = await start_stream()
    assert await anext(stream) == data
    await stream.aclose()

    assert len(spawned) == 1
    assert [delay for delay in delays if delay > 0] == [0.5]


async def test_backoff_doubles_to_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    data = moof(1, traf(1, 0)) + mdat()
    empty_sessions: list[list[bytes] | Exception] = [[] for _ in range(7)]
    install_fake_ffmpeg(monkeypatch, [*empty_sessions, [data]])
    delays = install_instant_sleep(monkeypatch)

    stream = await start_stream()
    assert await anext(stream) == data
    await stream.aclose()

    assert [delay for delay in delays if delay > 0] == [0.5, 1.0, 2.0, 4.0, 8.0, 10.0, 10.0]


async def test_healthy_session_resets_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    data = moof(1, traf(1, 0)) + mdat()
    sessions: list[list[bytes] | Exception] = [[], [], [data], [], [data]]
    install_fake_ffmpeg(monkeypatch, sessions)
    delays = install_instant_sleep(monkeypatch)
    # Start and end times per session, making only the third session last past the healthy
    # threshold.
    install_fake_clock(monkeypatch, [0, 1, 1, 2, 2, 9, 9, 10, 10])

    stream = await start_stream()
    await anext(stream)
    await anext(stream)
    await stream.aclose()

    assert [delay for delay in delays if delay > 0] == [0.5, 1.0, 0.5, 1.0]
