import sys
from asyncio import Event
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

import pytest

from ceres import Component
from ceres.address import Address
from ceres.config import ComponentConfig
from ceres.data import replace, validate
from ceres.directory import Directory
from ceres.error import AlreadyExistsError
from ceres.event import ExportRunCompletedEvent, ExportRunProgressEvent, ExportRunStartedEvent
from ceres.exporter import CsvFormat, ExportRunRecord, ExportRunState
from ceres.message import Message, MessageDirection
from tests.testing import wait_for_condition

if TYPE_CHECKING:
    from pathlib import Path

START = datetime(2026, 1, 1, tzinfo=UTC)


class Archive(Component):
    output: Directory


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
                    "path": "%Y/%m/%d/%H",
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
    def create(cls, root: Path, **exporter: Any) -> Exported:
        component = Archive(
            output=Directory(root), __with_name__="archive", __with_config__=config(**exporter)
        )  # type: ignore[reportCallIssue]
        return cls(component, root)

    async def store(self, *records: Message) -> None:
        for record in records:
            await self.component.system.messages._insert(record)

    async def delete(self, *records: Message) -> None:
        await self.component.system.messages.where(id=[record.id for record in records]).delete()

    async def run(self, hours: int = 3, replace: bool = False) -> ExportRunRecord:
        exporters = self.component.system.exporters
        return await exporters.run(
            "messages", START, START + timedelta(hours=hours), replace=replace
        )

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


def test_config_refuses_a_path_two_periods_share() -> None:
    assert "to one file '2000/01/01.csv'" in refusal(path="%Y/%m/%d")
    assert "to one file '2000/01/00.csv'" in refusal(path="%Y/%m/%H")
    assert "to one file '2000-01-01T12.csv'" in refusal(path="%Y-%m-%dT%I")
    assert "to one file '01.csv'" in refusal(period="month", path="%m")
    assert "to one file '001.csv'" in refusal(period="day", path="%j")
    assert "to one file '2000-01.csv'" in refusal(period="day", path="%Y-%U")
    assert "to one file '2000-01-01 AM.csv'" in refusal(path="%Y-%m-%d %p")


def test_config_refuses_a_two_digit_year() -> None:
    assert "2000-01-01T00:00:00+00:00 and 2100-01-01T00:00:00+00:00" in refusal(
        period="day", path="%y-%m-%d"
    )


def test_config_refuses_a_path_ending_in_an_extension() -> None:
    assert "the format adds `.csv`, so the path must not end in `.csv`" in refusal(
        path="%Y-%m-%dT%H.csv"
    )


def test_config_refuses_a_path_leaving_the_directory() -> None:
    assert "must name a file inside the directory" in refusal(path="../%Y-%m-%dT%H")
    assert "must name a file inside the directory" in refusal(path="/%Y-%m-%dT%H")


def test_config_refuses_unknown_placeholders() -> None:
    assert "got `{name}`" in refusal(path="{name}/%Y-%m-%dT%H")


def test_config_refuses_connection_without_a_pinned_connection() -> None:
    assert "needs a filter that pins one connection" in refusal(path="{connection}/%Y-%m-%dT%H")
    config(path="{connection}/%Y-%m-%dT%H", filter={"connection": "a"})


def test_config_refuses_time_directives_in_a_whole_period() -> None:
    assert "takes no time directives" in refusal(period="all", path="%Y")
    config(period="all", path="all-100%%")


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


def test_config_refuses_a_missing_directory_field() -> None:
    assert "which is not a `Directory` field of `Archive`" in refusal(directory="missing")
