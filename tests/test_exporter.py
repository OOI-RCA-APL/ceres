import csv
import io
import sys
from asyncio import Event, create_task, sleep
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, ClassVar, Self, override
from uuid import UUID

import pytest

from ceres import Bound, Component
from ceres.__internal__.database.writer import FlushSummary, Writer
from ceres.__internal__.entity import DeleteExecutor
from ceres.__internal__.pending_exports import (
    PENDING_EXPORTS_FILE,
    PendingExport,
    drain_pending_exports,
    export_pending,
)
from ceres.address import Address
from ceres.alert import Alert
from ceres.config import ComponentConfig, ExporterConfig, MessagePrunerConfig
from ceres.data import from_json, replace, to_json, validate
from ceres.entity import EntityType
from ceres.error import AlreadyExistsError, DatabaseUnreachableError
from ceres.event import (
    ExportRunCompletedEvent,
    ExportRunProgressEvent,
    ExportRunStartedEvent,
    LogEvent,
)
from ceres.exporter import (
    CsvFormat,
    ExportKey,
    ExportRecord,
    ExportRunRecord,
    ExportRunState,
    ExportSchema,
    JsonLinesFormat,
    LineFormat,
    _Live,
)
from ceres.level import Level
from ceres.logs import LogEntry
from ceres.message import Message, MessageDirection
from ceres.mount import Mount
from ceres.particle import Particle
from tests.testing import wait_for_condition

if TYPE_CHECKING:
    from pathlib import Path

START = datetime(2026, 1, 1, tzinfo=UTC)

RECENT = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=3)
"""A closed hour near now, since a live exporter checks only recent periods when it starts."""


class Archive(Component):
    output: Bound[Mount] = Mount.Field(...)
    shelf: Bound[Mount] = Mount.Field(writable=False)


def config(**exporter: Any) -> ComponentConfig:
    return validate(
        ComponentConfig,
        {
            "name": "archive",
            "class": Archive,
            "arguments": {"output": "."},
            "exporters": [
                {
                    "name": "messages",
                    "exports": "message",
                    "format": "csv",
                    "period": "hour",
                    "path": "{yyyy}/{MM}/{dd}/{HH}",
                    **exporter,
                }
            ],
        },
    )


def refusal(**exporter: Any) -> str:
    with pytest.raises(ValueError) as error:
        config(**exporter)

    return str(error.value)


def message(minutes: float, data: bytes = b"ab", id: int = 1) -> Message:
    return Message(
        id=UUID(int=id),
        address=Address("@archive"),
        timestamp=START + timedelta(minutes=minutes),
        direction=MessageDirection.RECEIVE,
        data=data,
    )


@dataclass
class Exported:
    component: Archive
    root: Path

    @classmethod
    def create(
        cls, root: Path, *, layout: str | None = None, zone: str | None = None, **exporter: Any
    ) -> Self:
        component = Archive(
            output=Mount(root, layout=layout, zone=zone),
            __with_name__="archive",
            __with_config__=config(**exporter),
        )  # type: ignore[reportCallIssue]
        return cls(component, root)

    async def store(self, *records: ExportRecord) -> None:
        system = self.component.system
        for record in records:
            match record:
                case Message():
                    await system.messages._insert(record)
                case Particle():
                    await system.particles._insert(record)
                case Alert():
                    await system.alerts._insert(record)
                case LogEntry():
                    await system.log._insert(record)

    async def delete(self, *records: Message) -> None:
        await self.component.system.messages.where(id=[record.id for record in records]).delete()

    async def run(
        self, hours: int = 3, replace: bool = False, after: datetime = START
    ) -> ExportRunRecord:
        exporters = self.component.system.exporters
        return await exporters.run(
            self.exporter.name, after, after + timedelta(hours=hours), replace=replace
        )

    @property
    def exporter(self) -> ExporterConfig:
        (exporter,) = self.component.system.exporters.get_all()
        return exporter

    def start(self) -> ExportRunRecord:
        return self.component.system.exporters.start("messages", START, START + timedelta(hours=3))

    def state(self, run: ExportRunRecord) -> ExportRunRecord:
        runs = self.component.system.exporters.get_runs("messages")
        return next(current for current in runs if current.id == run.id)

    async def settled(self, *runs: ExportRunRecord) -> list[ExportRunRecord]:
        await wait_for_condition(
            "every run ends",
            lambda: all(self.state(run).state != ExportRunState.RUNNING for run in runs),
            30,
        )
        return [self.state(run) for run in runs]

    def files(self) -> dict[str, bytes]:
        return {
            str(path.relative_to(self.root)): path.read_bytes()
            for path in sorted(self.root.rglob("*"))
            if path.is_file()
        }


@pytest.mark.parametrize("format", ["csv", "jsonl"])
async def test_reruns_write_equal_bytes(tmp_path: Path, format: str) -> None:
    exported = Exported.create(tmp_path, format=format)
    later = replace(message(5, id=4), timestamp=START + timedelta(minutes=5, microseconds=1))
    await exported.store(message(5, id=3), message(5, id=2), later, message(70, id=1))

    await exported.run()
    first = exported.files()
    await exported.run()

    assert exported.files() == first
    assert list(first) == [f"2026/01/01/00.{format}", f"2026/01/01/01.{format}"]


async def test_csv_sorts_records_by_timestamp_then_id(tmp_path: Path) -> None:
    exported = Exported.create(tmp_path)
    await exported.store(message(5, b"c", id=3), message(5, b"b", id=2), message(1, b"a", id=9))

    await exported.run()

    assert exported.files()["2026/01/01/00.csv"].decode().splitlines() == [
        "timestamp,id,address,connection,direction,data",
        f"2026-01-01T00:01:00Z,{UUID(int=9)},@archive,,receive,a",
        f"2026-01-01T00:05:00Z,{UUID(int=2)},@archive,,receive,b",
        f"2026-01-01T00:05:00Z,{UUID(int=3)},@archive,,receive,c",
    ]


async def test_jsonl_writes_one_object_per_record(tmp_path: Path) -> None:
    exported = Exported.create(tmp_path, format="jsonl")
    await exported.store(message(5, b"a\nb"))

    await exported.run()

    assert exported.files()["2026/01/01/00.jsonl"] == (
        b'{"timestamp":"2026-01-01T00:05:00Z","id":"00000000-0000-0000-0000-000000000001",'
        b'"address":"@archive","connection":null,"direction":"receive","data":"a\\nb"}\n'
    )


@pytest.mark.parametrize("format", ["csv", "jsonl"])
async def test_merge_keeps_records_the_database_lost(tmp_path: Path, format: str) -> None:
    exported = Exported.create(tmp_path / "merged", format=format)
    lost = message(10, b"x\ny", id=1)
    await exported.store(lost, message(20, id=2))
    await exported.run()

    await exported.delete(lost)
    await exported.store(message(5, id=3), message(30, id=4))
    await exported.run()

    whole = Exported.create(tmp_path / "whole", format=format)
    await whole.delete(message(5, id=3), message(30, id=4), message(20, id=2))
    await whole.store(lost, message(5, id=3), message(20, id=2), message(30, id=4))
    await whole.run()
    assert exported.files() == whole.files()


async def test_merge_lets_the_database_win_on_a_key(tmp_path: Path) -> None:
    exported = Exported.create(tmp_path)
    await exported.store(message(10, b"old"))
    await exported.run()

    await exported.component.system.messages.where(id=UUID(int=1)).update({"data": b"new"})
    await exported.run()

    assert exported.files()["2026/01/01/00.csv"].endswith(b",receive,new\n")


async def test_merge_keeps_the_file_of_a_period_with_no_records(tmp_path: Path) -> None:
    exported = Exported.create(tmp_path)
    kept = message(10)
    await exported.store(kept)
    await exported.run()
    archived = exported.files()

    await exported.delete(kept)
    run = await exported.run()

    assert exported.files() == archived
    assert (run.count, run.files) == (0, [])


async def test_replace_drops_lost_records_and_removes_empty_files(tmp_path: Path) -> None:
    exported = Exported.create(tmp_path)
    lost = message(10, id=1)
    await exported.store(lost, message(20, id=2), message(70, id=3))
    await exported.run()

    await exported.delete(lost, message(70, id=3))
    run = await exported.run(replace=True)

    assert list(exported.files()) == ["2026/01/01/00.csv"]
    assert exported.files()["2026/01/01/00.csv"].count(b"\n") == 2
    assert (run.count, run.files) == (1, ["2026/01/01/00.csv"])


async def test_merge_refuses_a_file_with_another_header(tmp_path: Path) -> None:
    exported = Exported.create(tmp_path)
    await exported.store(message(10))
    (tmp_path / "2026/01/01").mkdir(parents=True)
    (tmp_path / "2026/01/01/00.csv").write_bytes(b"a,b\n")

    run = await exported.run()

    assert run.state == ExportRunState.FAILED
    assert run.exception is not None and "another header" in run.exception
    assert exported.files()["2026/01/01/00.csv"] == b"a,b\n"


async def test_merge_skips_a_torn_final_line(tmp_path: Path) -> None:
    exported = Exported.create(tmp_path)
    await exported.store(message(10))
    await exported.run()
    path = tmp_path / "2026/01/01/00.csv"
    clean = path.read_bytes()
    path.write_bytes(clean + clean.splitlines(keepends=True)[1][:20])

    await exported.run()

    assert path.read_bytes() == clean


async def test_merge_refuses_a_file_out_of_key_order(tmp_path: Path) -> None:
    exported = Exported.create(tmp_path)
    await exported.store(message(10, id=1), message(20, id=2))
    await exported.run()
    path = tmp_path / "2026/01/01/00.csv"
    header, first, second = path.read_bytes().splitlines(keepends=True)
    path.write_bytes(header + second + first)

    run = await exported.run()

    assert run.exception is not None and "is not sorted by key" in run.exception
    assert path.read_bytes() == header + second + first


@pytest.mark.parametrize(
    ("format", "written"), [("csv", ",receive,ÿ\n"), ("jsonl", '"data":"ÿ"}\n')]
)
async def test_formats_write_each_byte_as_one_latin1_character(
    tmp_path: Path, format: str, written: str
) -> None:
    exported = Exported.create(tmp_path, format=format)
    await exported.store(message(10, b"\xff"))

    await exported.run()

    assert exported.files()[f"2026/01/01/00.{format}"].decode().endswith(written)


async def test_raw_concatenates_message_data(tmp_path: Path) -> None:
    exported = Exported.create(tmp_path, format="raw")
    await exported.store(message(20, b"\x00\xff", id=2), message(10, b"ab\n"))

    await exported.run(replace=True)

    assert exported.files() == {"2026/01/01/00.bin": b"ab\n\x00\xff"}


async def test_raw_refuses_a_merge(tmp_path: Path) -> None:
    exported = Exported.create(tmp_path, format="raw")

    with pytest.raises(ValueError, match="`raw` cannot merge, so the run must replace"):
        await exported.run()


async def test_run_emits_events_and_logs(tmp_path: Path) -> None:
    exported = Exported.create(tmp_path)
    await exported.store(message(10), message(70, id=2))
    events = exported.component.system.events.every(
        ExportRunStartedEvent, ExportRunProgressEvent, ExportRunCompletedEvent
    )
    with events.read() as reader:
        run = await exported.run()
        emitted: list[Any] = reader.clear()

    assert [type(event) for event in emitted] == [
        ExportRunStartedEvent,
        ExportRunProgressEvent,
        ExportRunProgressEvent,
        ExportRunCompletedEvent,
    ]
    assert [(event.path, event.count) for event in emitted[1:3]] == [
        ("2026/01/01/00.csv", 1),
        ("2026/01/01/01.csv", 1),
    ]
    assert (run.state, run.count) == (ExportRunState.COMPLETED, 2)


async def test_run_ring_keeps_the_last_twenty(tmp_path: Path) -> None:
    exported = Exported.create(tmp_path)
    runs = [await exported.run(hours=1) for _ in range(21)]

    kept = exported.component.system.exporters.get_runs("messages")

    assert [run.id for run in kept] == [run.id for run in reversed(runs[1:])]


async def test_a_third_pending_run_is_refused(tmp_path: Path) -> None:
    exported = Exported.create(tmp_path)
    await exported.store(message(10))
    first, second = exported.start(), exported.start()

    with pytest.raises(AlreadyExistsError):
        exported.start()

    settled = await exported.settled(first, second)
    assert [run.state for run in settled] == [ExportRunState.COMPLETED] * 2


async def test_re_adding_an_exporter_keeps_its_pending_runs(tmp_path: Path) -> None:
    exported = Exported.create(tmp_path)
    runs = exported.start(), exported.start()

    exporters = exported.component.system.exporters
    exporters.add(config().exporters[0])
    with pytest.raises(AlreadyExistsError):
        exported.start()

    await exported.settled(*runs)


async def test_stopping_the_component_fails_its_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def stall(self: CsvFormat, path: Path, *_: Any) -> None:
        path.write_bytes(b"partial")
        await Event().wait()

    monkeypatch.setattr(CsvFormat, "write", stall)
    exported = Exported.create(tmp_path)
    await exported.store(message(10))
    exported.component.system.start()
    await wait_for_condition("the component runs", lambda: exported.component.system.running, 30)
    run = exported.start()
    await wait_for_condition("the run writes", lambda: any(tmp_path.rglob("*.tmp")), 30)

    await exported.component.system.stop()

    stopped = exported.state(run)
    assert (stopped.state, stopped.exception) == (ExportRunState.FAILED, "component stopped")
    assert not any(tmp_path.rglob("*.tmp"))


@pytest.mark.skipif(sys.platform == "win32", reason="Windows files have no POSIX mode")
async def test_files_take_the_umask_and_keep_their_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("ceres.exporter._UMASK", 0o022)
    exported = Exported.create(tmp_path)
    await exported.store(message(10))
    path = tmp_path / "2026/01/01/00.csv"

    await exported.run()
    created = path.stat().st_mode & 0o777
    path.chmod(0o640)
    await exported.run()

    assert (created, path.stat().st_mode & 0o777) == (0o644, 0o640)


def start_refusal(root: Path, layout: str | None = None, **exporter: Any) -> str:
    with pytest.raises(ValueError) as error:
        Exported.create(root, layout=layout, **exporter)

    return str(error.value)


def test_a_path_two_periods_share_is_refused(tmp_path: Path) -> None:
    assert "to one file '2000/01/01.csv'" in start_refusal(tmp_path, path="{yyyy}/{MM}/{dd}")
    assert "to one file '2000/01/00.csv'" in start_refusal(tmp_path, path="{yyyy}/{MM}/{HH}")
    assert "to one file '01.csv'" in start_refusal(tmp_path, period="month", path="{MM}")
    assert "to one file '001.csv'" in start_refusal(tmp_path, period="day", path="{DDD}")


def test_a_two_digit_year_is_refused(tmp_path: Path) -> None:
    assert "2000-01-01T00:00:00+00:00 and 2100-01-01T00:00:00+00:00" in start_refusal(
        tmp_path, period="day", path="{yy}-{MM}-{dd}"
    )


def test_a_name_unique_only_beside_the_layout_is_accepted(tmp_path: Path) -> None:
    Exported.create(tmp_path, layout="{yyyy}/{MM}/{dd}", path="{exporter}_{HH}")
    assert "to one file '2000/01/01/messages.csv'" in start_refusal(
        tmp_path, layout="{yyyy}/{MM}/{dd}", path="{exporter}"
    )


def test_a_layout_finer_than_the_period_is_refused(tmp_path: Path) -> None:
    assert "layout '{yyyy}/{MM}/{dd}/{HH}' splits finer than period 'day'" in start_refusal(
        tmp_path, layout="{yyyy}/{MM}/{dd}/{HH}", period="day"
    )


def test_config_refuses_a_path_ending_in_an_extension() -> None:
    assert "the format adds `.csv`, so the path must not end in `.csv`" in refusal(
        path="{yyyy}{MM}{dd}T{HH}.csv"
    )


def test_config_refuses_a_path_leaving_the_mount() -> None:
    assert "renders an empty, '.', or '..' segment" in refusal(path="../{yyyy}{MM}{dd}T{HH}")
    assert "is absolute" in refusal(path="/{yyyy}{MM}{dd}T{HH}")


def test_config_refuses_unknown_atoms() -> None:
    assert "{name}" in refusal(path="{name}/{yyyy}{MM}{dd}T{HH}")


def test_config_refuses_connection_without_a_pinned_connection() -> None:
    assert "needs a filter that pins one connection" in refusal(path="{connection}/{yyyy}{HH}")
    config(path="{connection}/{yyyy}/{MM}/{dd}/{HH}", filter={"connection": "a"})


def test_config_refuses_time_atoms_in_a_whole_period() -> None:
    assert "takes no time atoms" in refusal(period="all", path="{yyyy}")
    config(period="all", path="all-100%")


def test_config_refuses_filter_order() -> None:
    assert "cannot set `order`" in refusal(filter={"order": "id"})
    assert "cannot set `limit`" in refusal(filter={"and": [{"limit": 1}]})


def test_config_refuses_lookback_without_schedule() -> None:
    assert "`lookback` needs a `schedule`" in refusal(lookback=2)


def test_config_refuses_raw_particles_and_schedules() -> None:
    assert "cannot export particle records" in refusal(exports="particle", format="raw")
    assert "cannot run on a schedule" in refusal(format="raw", schedule="0 * * * *")


def test_config_refuses_csv_particles_without_a_type() -> None:
    assert "needs a particle `type`" in refusal(exports="particle")


def test_config_refuses_a_builtin_format_class() -> None:
    assert "name the built-in format as `format: csv`" in refusal(
        format={"class": "ceres.exporter.CsvFormat"}
    )


def test_config_resolves_a_builtin_format_by_its_short_name() -> None:
    exporter = config(format={"class": "jsonl"}).exporters[0]
    assert isinstance(exporter.create_format(), JsonLinesFormat)
    assert exporter.format_name == "jsonl"
    assert "unexpected" in refusal(format={"class": "csv", "arguments": {"unexpected": 1}})


def test_config_refuses_a_missing_or_read_only_mount() -> None:
    assert "mount 'missing', which no `Mount.Field` of `Archive` declares" in refusal(
        mount="missing"
    )
    assert "mount 'shelf', which is read-only" in refusal(mount="shelf")


def test_files_default_to_the_period_in_the_layout_folder(tmp_path: Path) -> None:
    exported = Exported.create(tmp_path, layout="{yyyy}/{MM}", path=None)
    file = exported.component.system.exporters.get_current_file("messages")
    assert file == datetime.now(UTC).strftime("%Y/%m/messages_%Y%m%dT%H.csv")


async def test_files_render_in_utc_whatever_the_mount_zone(tmp_path: Path) -> None:
    exported = Exported.create(
        tmp_path, layout="{yyyy}/{MM}/{dd}", zone="America/Los_Angeles", path="{exporter}_{HH}"
    )
    await exported.store(message(10))

    await exported.run()

    assert list(exported.files()) == ["2026/01/01/messages_00.csv"]


async def test_a_whole_period_file_sits_at_the_mount_root(tmp_path: Path) -> None:
    exported = Exported.create(tmp_path, layout="{yyyy}/{MM}", period="all", path=None)
    await exported.store(message(10))

    await exported.run()

    assert list(exported.files()) == ["messages.csv"]


@pytest.mark.parametrize(
    "field",
    ["subsample_every", "subsample", "subsample_select", "timespan", "max_age", "min_age"],
)
def test_config_refuses_filters_that_depend_on_the_query(field: str) -> None:
    value = {"subsample": 2, "subsample_select": "first"}.get(field, "PT1H")
    window = {"after": "2026-01-01T00:00:00Z", "before": "2026-01-02T00:00:00Z"}
    assert f"cannot set `{field}`" in refusal(filter={field: value, **window})


def test_config_refuses_a_nested_filter_that_depends_on_the_query() -> None:
    assert "cannot set `max_age`" in refusal(
        filter={"or": [{"connection": "a"}, {"max_age": "PT1H"}]}
    )


def recent(minutes: float, data: bytes = b"ab", id: int = 1) -> Message:
    return replace(message(0, data, id), timestamp=RECENT + timedelta(minutes=minutes))


RECENT_FILE = f"{RECENT:%Y/%m/%d/%H}.csv"


@dataclass
class Live(Exported):
    @classmethod
    async def started(cls, root: Path, **exporter: Any) -> Live:
        live = cls.create(root, interval=1, **exporter)
        await live.begin()
        return live

    async def begin(self) -> None:
        system = self.component.system
        system.start()
        await wait_for_condition("the component runs", lambda: system.running, 30)
        if any(exporter.is_live for exporter in system.exporters.get_all()):
            await wait_for_condition("the start check ends", self.checked, 30)

    def checked(self) -> bool:
        held = self.component.system.exporters.get_written_through(self.exporter.exports)
        return held is not None and held[1] > datetime.min.replace(tzinfo=UTC)

    async def write(self, *records: ExportRecord) -> None:
        for record in records:
            self.component.system.store(record)

        await self.component.system.flush()

    async def lines(self, path: str, count: int) -> list[bytes]:
        header = 1 if path.endswith(".csv") else 0

        def written() -> bool:
            file = self.root / path
            return file.exists() and file.read_bytes().count(b"\n") == count + header

        await wait_for_condition(f"{path} holds {count} records", written, 30)
        return (self.root / path).read_bytes().splitlines()[header:]


def ids(lines: list[bytes]) -> list[int]:
    return [UUID(line.split(b",")[1].decode()).int for line in lines]


@pytest.mark.parametrize("format", ["csv", "jsonl"])
async def test_live_export_equals_a_rerun(tmp_path: Path, format: str) -> None:
    live = await Live.started(tmp_path / "live", format=format)
    path = f"{RECENT:%Y/%m/%d/%H}.{format}"
    await live.write(recent(10, id=1), recent(30, id=3))
    await live.lines(path, 2)
    await live.write(recent(20, id=2), recent(70, id=5))
    await live.write(recent(40, id=4))
    await live.lines(path, 4)

    rerun = Exported.create(tmp_path / "rerun", format=format)
    await rerun.delete(*(recent(0, id=id) for id in range(1, 6)))
    await rerun.store(*[recent(m, id=i) for i, m in enumerate((10, 20, 30, 40, 70), 1)])
    await rerun.run(after=RECENT)

    await wait_for_condition("both files match", lambda: live.files() == rerun.files(), 30)
    await live.component.system.stop()


async def test_a_late_record_lands_in_key_order_at_the_next_wake(tmp_path: Path) -> None:
    live = await Live.started(tmp_path)
    await live.write(recent(10, id=1), recent(30, id=3))
    await live.lines(RECENT_FILE, 2)

    await live.write(recent(20, id=2))

    assert ids(await live.lines(RECENT_FILE, 3)) == [1, 2, 3]
    await live.component.system.stop()


async def test_in_order_records_append_to_the_file(tmp_path: Path) -> None:
    live = await Live.started(tmp_path)
    await live.write(recent(10, id=1))
    await live.lines(RECENT_FILE, 1)
    inode = (tmp_path / RECENT_FILE).stat().st_ino

    await live.write(recent(20, id=2))

    assert ids(await live.lines(RECENT_FILE, 2)) == [1, 2]
    assert (tmp_path / RECENT_FILE).stat().st_ino == inode
    await live.component.system.stop()


async def test_a_requeued_batch_reaches_the_file_once_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = await Live.started(tmp_path)
    write = Writer._write_natively

    async def unreachable(*_: Any) -> bool:
        monkeypatch.setattr(Writer, "_write_natively", write)
        raise DatabaseUnreachableError(reason="refused")

    monkeypatch.setattr(Writer, "_write_natively", unreachable)
    with pytest.raises(DatabaseUnreachableError):
        await live.write(recent(10, id=1))

    await live.write(recent(20, id=2))

    assert ids(await live.lines(RECENT_FILE, 2)) == [1, 2]
    await live.component.system.stop()


async def test_stopping_the_component_unsubscribes_it(tmp_path: Path) -> None:
    live = await Live.started(tmp_path)
    writer: Writer = live.component.system._Node__writer  # type: ignore[attr-defined]
    assert len(writer._subscribers) == 1

    await live.component.system.stop()

    assert writer._subscribers == []


async def test_a_restart_heals_a_torn_append(tmp_path: Path) -> None:
    exported = Exported.create(tmp_path / "torn")
    await exported.store(recent(10, id=1))
    await exported.run(after=RECENT)
    path = tmp_path / "torn" / RECENT_FILE
    path.write_bytes(path.read_bytes() + b"2026-01-01T00:20:00Z,0000")
    await exported.store(recent(20, id=2))

    live = Live(exported.component, exported.root)
    await live.begin()

    assert ids(await live.lines(RECENT_FILE, 2)) == [1, 2]
    await live.write(recent(30, id=3))
    assert ids(await live.lines(RECENT_FILE, 3)) == [1, 2, 3]
    await live.component.system.stop()


async def test_a_prune_leaves_the_file(tmp_path: Path) -> None:
    live = await Live.started(tmp_path)
    await live.write(recent(10, id=1))
    await live.lines(RECENT_FILE, 1)

    await live.delete(recent(10, id=1))
    await live.write(recent(20, id=2))

    assert ids(await live.lines(RECENT_FILE, 2)) == [1, 2]
    await live.component.system.stop()


def pruner(**fields: Any) -> MessagePrunerConfig:
    return validate(
        MessagePrunerConfig, {"name": "old", "schedule": "0 0 * * *", "filter": {}, **fields}
    )


async def prune(exported: Exported, config: MessagePrunerConfig) -> int:
    await exported.component.system.pruners._PrunerManager__run(config)  # type: ignore[attr-defined]
    return await exported.component.system.messages.count()


async def test_the_pruner_waits_for_the_exporter_to_write(tmp_path: Path) -> None:
    exported = Exported.create(tmp_path)
    await exported.store(recent(10, id=1))
    assert await prune(exported, pruner()) == 1

    live = Live(exported.component, exported.root)
    await live.begin()

    assert ids(await live.lines(RECENT_FILE, 1)) == [1]
    assert await prune(exported, pruner()) == 0
    await live.component.system.stop()


async def test_a_pruner_may_skip_waiting_for_exports(tmp_path: Path) -> None:
    exported = Exported.create(tmp_path)
    await exported.store(recent(10, id=1))

    assert await prune(exported, pruner(wait_for_exports=False)) == 0


async def test_flush_subscribers_hear_keys_by_kind_and_address(tmp_path: Path) -> None:
    system = (await Live.started(tmp_path, live=False)).component.system
    heard: list[FlushSummary] = []
    unsubscribe = system.__subscribe_flushes__(heard.append)
    record = message(10)
    entry = LogEntry(address=Address("@archive"), level=Level.INFO, content="a")

    system.store(record)
    system.store(entry)
    await system.flush()
    unsubscribe()
    unsubscribe()
    system.store(message(20, id=2))
    await system.flush()

    keys = {(*kind, key) for summary in heard for kind, keys in summary.items() for key in keys}
    archive = Address("@archive")
    assert (EntityType.MESSAGE, archive, (record.timestamp, record.id)) in keys
    assert (EntityType.LOG_ENTRY, archive, (entry.timestamp, entry.id)) in keys
    assert (EntityType.MESSAGE, archive, (START + timedelta(minutes=20), UUID(int=2))) not in keys
    await system.stop()


async def test_a_failing_flush_subscriber_never_fails_the_flush(tmp_path: Path) -> None:
    system = (await Live.started(tmp_path, live=False)).component.system

    def fail(_: FlushSummary) -> None:
        raise ValueError("subscriber")

    system.__subscribe_flushes__(fail)
    system.store(message(10))
    await system.flush()

    assert await system.messages.count() == 1
    await system.stop()


def test_a_writer_without_subscribers_skips_summarizing() -> None:
    class Unreadable:
        def __iter__(self) -> Any:
            raise AssertionError("summarized")

    Writer(lambda: None)._notify(Unreadable())  # type: ignore[arg-type]


class Plain(LineFormat):
    extension: ClassVar[str] = ".txt"

    @override
    def encode(self, schema: ExportSchema, record: ExportRecord) -> bytes:
        return f"{record.timestamp.isoformat()} {record.id}\n".encode()

    @override
    def key(self, line: bytes) -> ExportKey:
        timestamp, id = line.split()
        return datetime.fromisoformat(timestamp.decode()), UUID(id.decode())


async def test_a_custom_format_class_merges(tmp_path: Path) -> None:
    exported = Exported.create(tmp_path, format={"class": f"{__name__}.Plain"}, live=False)
    await exported.store(message(20, id=2))
    await exported.run()
    await exported.store(message(10, id=1))

    await exported.run()

    assert exported.files() == {
        "2026/01/01/00.txt": (
            f"{(START + timedelta(minutes=10)).isoformat()} {UUID(int=1)}\n"
            f"{(START + timedelta(minutes=20)).isoformat()} {UUID(int=2)}\n"
        ).encode()
    }


@pytest.mark.parametrize(
    ("record", "exporter", "written"),
    [
        (
            Particle(address=Address("@archive"), type="sample", data={"a": 1}, timestamp=START),
            {"exports": "particle", "format": "jsonl"},
            b'"connection":null,"type":"sample","data":{"a":1}}\n',
        ),
        (
            Alert(
                address=Address("@archive"), level=Level.ERROR, type="hot", data={}, timestamp=START
            ),
            {"exports": "alert"},
            b",error,hot,{}\n",
        ),
        (
            LogEntry(
                address=Address("@archive"), level=Level.INFO, content="hello", timestamp=START
            ),
            {"exports": "log-entry"},
            b",hello\n",
        ),
    ],
    ids=["particle", "alert", "log-entry"],
)
async def test_every_record_kind_exports(
    tmp_path: Path, record: ExportRecord, exporter: dict[str, Any], written: bytes
) -> None:
    exported = Exported.create(tmp_path, **exporter)
    await exported.store(record)

    await exported.run()

    (file,) = exported.files().values()
    assert file.endswith(written)


async def test_a_prune_waits_for_a_flush_in_flight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = await Live.started(tmp_path)
    await live.write(recent(10, id=1), recent(30, id=3))
    await live.lines(RECENT_FILE, 2)
    committed, release = Event(), Event()
    write = Writer._write_natively

    async def stalled(*arguments: Any) -> bool:
        written = await write(*arguments)
        committed.set()
        await release.wait()
        return written

    monkeypatch.setattr(Writer, "_write_natively", stalled)
    flushing = create_task(live.write(recent(20, id=2)))
    await committed.wait()
    pruning = create_task(prune(live, pruner()))
    await sleep(0.2)
    release.set()
    await flushing
    await pruning

    assert ids(await live.lines(RECENT_FILE, 3)) == [1, 2, 3]
    await live.component.system.stop()


async def test_a_paged_prune_keeps_a_late_record_flushed_between_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = await Live.started(tmp_path)
    system = live.component.system
    await live.write(*(recent(minutes, id=minutes) for minutes in range(1, 7)))
    await live.lines(RECENT_FILE, 6)
    late = recent(0.5, id=7)
    delete = DeleteExecutor._await

    async def first_page(self: DeleteExecutor[Any, Any]) -> int:
        monkeypatch.setattr(DeleteExecutor, "_await", delete)
        deleted = await delete(self)
        system.store(late)
        create_task(system.flush())
        await sleep(0)
        return deleted

    monkeypatch.setattr("ceres.pruner._PRUNE_PAGE", 2)
    monkeypatch.setattr(DeleteExecutor, "_await", first_page)
    await prune(live, pruner())

    assert ids(await live.lines(RECENT_FILE, 7)) == [7, 1, 2, 3, 4, 5, 6]
    await live.component.system.stop()


def csv_ids(path: Path) -> list[int]:
    rows = list(csv.reader(io.StringIO(path.read_text())))[1:]
    return [UUID(row[1]).int for row in rows]


async def test_an_append_heals_a_record_torn_inside_a_quoted_cell(tmp_path: Path) -> None:
    exported = Exported.create(tmp_path)
    await exported.store(recent(10, b"a\nb", id=1), recent(20, b"c\nd", id=2))
    await exported.run(after=RECENT)
    path = tmp_path / RECENT_FILE
    whole = path.read_bytes()
    path.write_bytes(whole[: whole.index(b"c\n") + 2])
    await exported.delete(recent(20, id=2))

    live = Live(exported.component, exported.root)
    await live.begin()
    await live.write(recent(30, id=3))

    await wait_for_condition("the file holds 1 and 3", lambda: csv_ids(path) == [1, 3], 30)
    await live.component.system.stop()


async def test_a_raw_exporter_names_the_rerun_for_records_it_missed(tmp_path: Path) -> None:
    current = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    exported = Exported.create(tmp_path, format="raw")
    await exported.store(replace(message(0), timestamp=current))

    live = Live(exported.component, exported.root)
    with exported.component.system.events.every(LogEvent).read() as reader:
        await live.begin()
        logged: list[Any] = reader.clear()

    warning = f"lacks records stored before it started in '{current:%Y/%m/%d/%H}.bin'"
    assert any(warning in event.entry.content for event in logged)
    await live.component.system.stop()


async def test_live_export_hears_only_records_the_component_selects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    heard: list[ExportKey] = []
    notify = _Live.notify

    def spy(self: _Live, period: Any, keys: Any) -> None:
        heard.extend(keys)
        notify(self, period, keys)

    monkeypatch.setattr(_Live, "notify", spy)
    live = await Live.started(tmp_path)
    outside = replace(recent(10, id=1), address=Address("@other"))
    inside = replace(recent(20, id=2), address=Address("@archive.child"))

    await live.write(outside)
    await live.write(inside)

    assert ids(await live.lines(RECENT_FILE, 1)) == [2]
    assert heard == [(inside.timestamp, inside.id)]
    await live.component.system.stop()


@dataclass
class Loading:
    """An engine double running one component, keeping each line it logs."""

    component: Component
    lines: list[str]

    def get_components(self, **_: Any) -> list[Component]:
        return [self.component]

    @property
    def log(self) -> Self:
        return self

    def info(self, line: str) -> None:
        self.lines.append(line)

    warning = info


def pending(kind: str, address: str, first: float, last: float) -> str:
    return to_json(
        {
            "kind": kind,
            "address": address,
            "first": START + timedelta(minutes=first),
            "last": START + timedelta(minutes=last),
        }
    )


async def test_an_engine_exports_what_loads_left_pending(tmp_path: Path) -> None:
    exported = Exported.create(tmp_path / "output")
    await exported.store(message(5, id=1), message(70, id=2))
    state = tmp_path / ".ceres"
    state.mkdir()
    lines = [pending("message", "@archive", 5, 5), "abc", pending("alert", "@archive", 5, 5)]
    (state / PENDING_EXPORTS_FILE).write_text("\n".join(lines))
    engine = Loading(exported.component, [])

    await drain_pending_exports(engine, state)  # type: ignore[reportArgumentType]

    assert list(exported.files()) == ["2026/01/01/00.csv"]
    assert list(state.iterdir()) == []
    assert "Skipping line 2" in engine.lines[0]
    assert "through '@archive' 'messages'" in engine.lines[1]
    assert "No exporter takes the loaded alert records" in engine.lines[2]


async def test_a_load_outside_the_component_exports_nothing(tmp_path: Path) -> None:
    exported = Exported.create(tmp_path)
    await exported.store(message(5))
    engine = Loading(exported.component, [])
    entry = validate(PendingExport, from_json(pending("message", "@other", 5, 5)))

    await export_pending(engine, [entry])  # type: ignore[reportArgumentType]

    assert exported.files() == {}
