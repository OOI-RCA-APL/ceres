from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, override
from uuid import UUID

import pytest

from ceres import Bound, Component, Mount
from ceres.__internal__.playback import (
    PlaybackLevel,
    PlaybackRangeError,
    PlaybackRecord,
    PlaybackState,
)
from ceres.address import Address
from ceres.component import listener, sieve
from ceres.config import ComponentConfig
from ceres.data import validate
from ceres.error import AlreadyExistsError
from ceres.event import ParticleEvent, PlaybackProgressEvent
from ceres.message import Message, MessageDirection
from ceres.particle import Particle, ParticleData
from ceres.timing import utc
from tests.testing import wait_for_condition

if TYPE_CHECKING:
    from pathlib import Path

START = datetime(2026, 1, 1, tzinfo=UTC)


class CountData(ParticleData):
    value: int


class Count(Particle[CountData]):
    type = "test/count"


class OtherData(ParticleData):
    note: str


class Other(Particle[OtherData]):
    type = "test/other"


class Counter(Component):
    output: Bound[Mount] = Mount.Field(...)

    @sieve
    def count(self, message: Message) -> Count:
        # The particle's timestamp defaults to `utc()`, which a playback sets to the message's.
        return Count(
            type=Count.type, address=message.address, data=CountData(value=len(message.data))
        )


class Untyped(Component):
    @sieve
    def count(self, message: Message):  # noqa: ANN201
        return None


def at(minutes: float) -> datetime:
    return START + timedelta(minutes=minutes)


def message(minutes: float, data: bytes = b"ab", id: int = 1) -> Message:
    return Message(
        id=UUID(int=id),
        address=Address("@counter"),
        timestamp=at(minutes),
        direction=MessageDirection.RECEIVE,
        data=data,
    )


def count(minutes: float, address: str = "@counter") -> Count:
    return Count(
        type=Count.type, address=Address(address), timestamp=at(minutes), data=CountData(value=9)
    )


def other(minutes: float) -> Other:
    return Other(
        type=Other.type,
        address=Address("@counter"),
        timestamp=at(minutes),
        data=OtherData(note="a"),
    )


def counter(root: Path, **exporter: Any) -> Counter:
    exporters = [{"name": "counts", "exports": "particle", **exporter}] if exporter else []
    config = validate(
        ComponentConfig,
        {
            "name": "counter",
            "class": Counter,
            "arguments": {"output": "."},
            "exporters": exporters,
        },
    )
    return Counter(output=Mount(root), __with_name__="counter", __with_config__=config)  # type: ignore[reportCallIssue]


async def store(component: Component, *records: Message | Particle) -> None:
    for record in records:
        if isinstance(record, Message):
            await component.system.messages._insert(record)
        else:
            await component.system.particles._insert(record)


async def stored(component: Component, address: str | None = None) -> list[tuple[str, datetime]]:
    query: Any = component.system.particles.where(
        order=["timestamp:asc"], address=Address(address or "@counter").all()
    )
    async with query as results:
        return [(f"{found.address} {found.type}", found.timestamp) async for found in results]


async def play(component: Component, **options: Any) -> PlaybackRecord:
    """Replay from the oldest stored message, at minute 10, through minute 60."""
    return await component.system.playbacks.run(at(10), at(60), **options)


async def test_playback_replaces_particles_from_stored_messages(tmp_path: Path) -> None:
    component = counter(tmp_path)
    await store(
        component,
        message(10, b"abc", id=1),
        message(20, b"abcd", id=2),
        count(15),
        count(90),
        other(15),
        count(15, address="@counter.child"),
    )

    run = await play(component)

    assert run.state == PlaybackState.COMPLETED, run.exception
    assert (run.deleted, run.messages, run.particles) == (1, 2, 2)
    assert await stored(component) == [
        ("@counter test/count", at(10)),
        ("@counter test/other", at(15)),
        ("@counter.child test/count", at(15)),
        ("@counter test/count", at(20)),
        ("@counter test/count", at(90)),
    ]


async def test_playback_loses_hand_stored_particles_of_a_replayed_type(tmp_path: Path) -> None:
    component = counter(tmp_path)
    await store(component, message(10), count(30))

    await play(component)

    assert await stored(component) == [("@counter test/count", at(10))]


async def test_playback_refuses_a_sieve_without_a_particle_type(tmp_path: Path) -> None:
    component = Untyped(__with_name__="untyped")  # type: ignore[reportCallIssue]

    with pytest.raises(ValueError, match="Sieve 'count' declares no particle type"):
        await component.system.playbacks.start(START, at(60))


async def test_playback_refuses_a_range_older_than_the_stored_messages(tmp_path: Path) -> None:
    component = counter(tmp_path)
    with pytest.raises(ValueError, match="no stored messages") as refusal:
        await component.system.playbacks.start(START, at(60))
    assert not isinstance(refusal.value, PlaybackRangeError)

    await store(component, message(10, id=1), message(20, id=2))
    with pytest.raises(
        PlaybackRangeError, match="only from 2026-01-01T00:10:00\\+00:00 to .*00:20:00"
    ):
        await component.system.playbacks.start(START - timedelta(minutes=1), at(60))


class Faulty(Component):
    @sieve
    def count(self, message: Message) -> Count:
        if message.data == b"bad":
            raise RuntimeError("abc")

        return Count(type=Count.type, address=message.address, data=CountData(value=1))


async def test_a_sieve_raising_mid_replay_fails_the_playback(tmp_path: Path) -> None:
    component = Faulty(__with_name__="counter")  # type: ignore[reportCallIssue]
    await store(component, message(10, id=1), message(20, b"bad", id=2), message(30, id=3))

    run = await play(component)

    assert (run.state, run.exception, run.messages) == (PlaybackState.FAILED, "abc", 2)
    assert utc() > START + timedelta(days=1)


async def test_a_second_playback_is_refused_while_one_runs(tmp_path: Path) -> None:
    component = counter(tmp_path)
    await store(component, message(10))
    playbacks = component.system.playbacks

    first = await playbacks.start(at(10), at(60))
    with pytest.raises(AlreadyExistsError):
        await playbacks.start(at(10), at(60))

    await wait_for_condition(
        "the first playback ends",
        lambda: playbacks.get_runs()[0].state != PlaybackState.RUNNING,
        30,
    )
    second = await play(component)
    assert [run.id for run in playbacks.get_runs()] == [second.id, first.id]


@pytest.mark.parametrize(
    ("level", "events"), [(PlaybackLevel.PARTICLES, 0), (PlaybackLevel.FULL, 2)]
)
async def test_only_a_full_playback_emits_particle_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, level: PlaybackLevel, events: int
) -> None:
    component = counter(tmp_path)
    await store(component, message(10, id=1), message(20, id=2))
    emitted = emissions(component, monkeypatch)

    await play(component, level=level)

    assert [cls for cls, _ in emitted].count(ParticleEvent) == events


async def test_playback_events_take_the_real_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    component = counter(tmp_path)
    await store(component, message(10))
    emitted = emissions(component, monkeypatch)

    run = await play(component)

    assert [now >= run.started for cls, now in emitted if cls is PlaybackProgressEvent] == [True]


def emissions(component: Component, monkeypatch: pytest.MonkeyPatch) -> list[tuple[type, datetime]]:
    """Record each event the component emits with the time its clock read then."""
    emitted: list[tuple[type, datetime]] = []
    manager = type(component.system.events)
    emit = manager.emit

    def record(self: Any, cls: type, /, **fields: Any) -> Any:
        emitted.append((cls, utc()))
        return emit(self, cls, **fields)

    monkeypatch.setattr(manager, "emit", record)
    return emitted


class Listening(Counter):
    @override
    def __setup__(self) -> None:
        self.heard: list[datetime] = []

    @listener(local=True)
    def on__particle(self, event: ParticleEvent) -> None:
        self.heard.append(utc())


async def test_a_full_playback_leaves_listeners_on_the_real_clock(tmp_path: Path) -> None:
    component = Listening(output=Mount(tmp_path), __with_name__="counter")  # type: ignore[reportCallIssue]
    await store(component, message(10))
    component.system.start()
    try:
        await play(component, level=PlaybackLevel.FULL)
        await wait_for_condition(
            "the listener hears the particle", lambda: bool(component.heard), 30
        )
    finally:
        await component.system.stop()

    assert component.heard[0] > START + timedelta(days=1)


async def test_playback_rewrites_the_files_of_replayed_exporters(tmp_path: Path) -> None:
    component = counter(
        tmp_path, format="jsonl", type=f"{__name__}.Count", period="all", path="counts"
    )
    await store(component, message(10, b"abc"))

    run = await play(component)

    assert run.state == PlaybackState.COMPLETED, run.exception
    assert len(run.export_runs) == 1
    assert '"value":3' in (tmp_path / "counts.jsonl").read_text()
