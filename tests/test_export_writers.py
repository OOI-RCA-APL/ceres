"""The custom writer contract `docs/exporters.md` documents, through the writers it shows."""

import json
from collections.abc import AsyncIterable, AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar, override
from uuid import UUID

import pytest

from ceres import (
    Address,
    Bound,
    Component,
    ExportKey,
    ExportLineWriter,
    ExportRecord,
    ExportSchema,
    ExportWriter,
    Mount,
    Particle,
    ParticleData,
    atomic_write,
)
from ceres.config import ComponentConfig
from ceres.data import validate
from ceres.entity import EntityType
from ceres.exporter import ExportConflict, ExportRunState
from tests.testing import wait_for_condition

START = datetime(2026, 1, 1, tzinfo=UTC)

RECENT = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=3)


class ReadingData(ParticleData):
    celsius: float
    humidity: float


class Reading(Particle[ReadingData]):
    type = "reading"
    data: ReadingData


# The guide's writers, kept word for word with `docs/exporters.md`.


class TabWriter(ExportLineWriter):
    """Tab separated values, optionally with a header line."""

    extension: ClassVar[str] = ".tsv"
    resumable: ClassVar[bool] = True

    header_line: bool = False

    @override
    def header(self, schema: ExportSchema) -> bytes:
        return ("\t".join(schema.names) + "\n").encode() if self.header_line else b""

    @override
    def encode(self, schema: ExportSchema, record: ExportRecord) -> bytes:
        cells = ("" if value is None else str(value) for value in schema.row(record))
        return ("\t".join(cells) + "\n").encode()

    @override
    def key(self, line: bytes) -> ExportKey:
        timestamp, id = line.split(b"\t", 2)[:2]
        return datetime.fromisoformat(timestamp.decode()), UUID(id.decode())


class SummaryWriter(ExportWriter):
    """One JSON document per file holding every record's row."""

    extension: ClassVar[str] = ".json"

    indent: int | None = None

    @override
    async def write(
        self, path: Path, schema: ExportSchema, records: AsyncIterable[ExportRecord]
    ) -> None:
        rows = [
            dict(zip(schema.names, schema.row(record), strict=True)) async for record in records
        ]
        path.write_text(json.dumps({"columns": schema.names, "rows": rows}, indent=self.indent))


# Writers the contract tests need beyond the guide's.


class Notes(ExportLineWriter):
    """Encodes only, so its files hold no keys."""

    extension: ClassVar[str] = ".txt"

    @override
    def encode(self, schema: ExportSchema, record: ExportRecord) -> bytes:
        return f"{record.id}\n".encode()


class Failing(ExportWriter):
    """Writes part of a file, then fails."""

    extension: ClassVar[str] = ".json"

    @override
    async def write(
        self, path: Path, schema: ExportSchema, records: AsyncIterable[ExportRecord]
    ) -> None:
        path.write_text("partial")
        raise RuntimeError("disk full")


class Station(Component):
    output: Bound[Mount] = Mount.Field(...)


def station(root: Path, **exporter: Any) -> Station:
    config = validate(
        ComponentConfig,
        {
            "name": "station",
            "class": Station,
            "arguments": {"output": "."},
            "exporters": [
                {
                    "name": "readings",
                    "exports": "particle",
                    "type": f"{__name__}.Reading",
                    "period": "hour",
                    "path": "{yyyy}{MM}{dd}{HH}",
                    **exporter,
                }
            ],
        },
    )
    return Station(output=Mount(root), __with_name__="station", __with_config__=config)  # type: ignore[reportCallIssue]


def reading(minutes: float, celsius: float, *, id: int, at: datetime = START) -> Reading:
    return Reading(
        type="reading",
        id=UUID(int=id),
        address=Address("@station"),
        timestamp=at + timedelta(minutes=minutes),
        data=ReadingData(celsius=celsius, humidity=50.0),
    )


async def store(component: Station, *records: Reading) -> None:
    for record in records:
        await component.system.particles._insert(record)


def files(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): path.read_text()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def at(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


async def test_the_guide_writer_takes_arguments_and_fields(tmp_path: Path) -> None:
    component = station(
        tmp_path,
        format={"class": f"{__name__}.TabWriter", "arguments": {"header_line": True}},
        fields={"timestamp": "timestamp", "id": "id", "temperature": "celsius"},
    )
    await store(component, reading(20, 2.5, id=2), reading(10, 1.5, id=1))

    await component.system.exporters.run("readings", START, START + timedelta(hours=1))

    first, second = (UUID(int=1), UUID(int=2))
    assert files(tmp_path) == {
        "2026010100.tsv": (
            "timestamp\tid\ttemperature\n"
            f"{at(START + timedelta(minutes=10))}\t{first}\t1.5\n"
            f"{at(START + timedelta(minutes=20))}\t{second}\t2.5\n"
        )
    }


async def test_a_whole_file_writer_overwrites_keeps_and_purges(tmp_path: Path) -> None:
    component = station(tmp_path, format={"class": f"{__name__}.SummaryWriter"})
    exporters = component.system.exporters
    after, before = START, START + timedelta(hours=2)
    # Stored history reaching the file's start lets `overwrite` rewrite it.
    await store(component, reading(0, 1.5, id=1))

    await exporters.run("readings", after, before)
    written = json.loads((tmp_path / "2026010100.json").read_text())
    assert [row["celsius"] for row in written["rows"]] == [1.5]
    assert written["columns"][:2] == ["timestamp", "id"]

    await store(component, reading(20, 2.5, id=2))
    skipped = await exporters.run("readings", after, before, on_conflict=ExportConflict.SKIP)
    assert skipped.kept == 1
    assert len(json.loads((tmp_path / "2026010100.json").read_text())["rows"]) == 1

    await exporters.run("readings", after, before)
    assert len(json.loads((tmp_path / "2026010100.json").read_text())["rows"]) == 2

    (tmp_path / "2026010101.json").write_text("stale")
    purged = await exporters.run("readings", after, before, on_conflict=ExportConflict.PURGE)
    assert purged.removed == 1
    assert list(files(tmp_path)) == ["2026010100.json"]


async def test_a_failing_writer_keeps_the_old_file_and_leaves_no_temporary(
    tmp_path: Path,
) -> None:
    (tmp_path / "2026010100.json").write_text("old")
    component = station(tmp_path, format={"class": f"{__name__}.Failing"})
    await store(component, reading(10, 1.5, id=1))

    run = await component.system.exporters.run(
        "readings", START, START + timedelta(hours=1), on_conflict=ExportConflict.PURGE
    )

    assert run.state == ExportRunState.FAILED
    assert run.exception is not None and "disk full" in run.exception
    assert files(tmp_path) == {"2026010100.json": "old"}


async def test_a_resumable_line_writer_heals_a_torn_line_on_start(tmp_path: Path) -> None:
    component = station(tmp_path, format={"class": f"{__name__}.TabWriter"}, interval=1)
    await store(component, reading(10, 1.5, id=1, at=RECENT))
    await component.system.exporters.run("readings", RECENT, RECENT + timedelta(hours=1))
    path = tmp_path / f"{RECENT:%Y%m%d%H}.tsv"
    path.write_text(path.read_text() + f"{at(RECENT)}\t000")
    await store(component, reading(20, 2.5, id=2, at=RECENT))

    async with running(component):
        await wait_for_lines(path, 2)

    ids = [UUID(line.split("\t")[1]).int for line in path.read_text().splitlines()]
    assert ids == [1, 2]


async def test_an_encode_only_line_writer_never_reads_its_files(tmp_path: Path) -> None:
    component = station(tmp_path, format={"class": f"{__name__}.Notes"}, interval=1)
    path = tmp_path / f"{RECENT:%Y%m%d%H}.txt"
    path.write_text("abc\n")

    async with running(component):
        component.system.store(reading(20, 2.5, id=2, at=RECENT))
        await component.system.flush()
        await wait_for_lines(path, 2)

    assert path.read_text() == f"abc\n{UUID(int=2)}\n"


async def test_a_component_writes_computed_particles_with_a_writer(tmp_path: Path) -> None:
    # The guide's component example: a writer over particles the component never stored.
    schema = ExportSchema.create(EntityType.PARTICLE, Reading, "daily")
    computed = [reading(10, 1.5, id=1), reading(20, 2.5, id=2)]

    async def records() -> AsyncIterable[ExportRecord]:
        for record in computed:
            yield record

    target = Mount(tmp_path) / "summary.json"
    async with atomic_write(target) as temporary:
        await SummaryWriter(indent=2).write(temporary, schema, records())

    written = json.loads(target.path.read_text())
    assert [row["celsius"] for row in written["rows"]] == [1.5, 2.5]
    assert list(files(tmp_path)) == ["summary.json"]


async def test_a_column_change_appends_to_a_headerless_file_undetected(tmp_path: Path) -> None:
    # A known limit the guide states: headerless files hold nothing to compare columns with.
    path = tmp_path / f"{RECENT:%Y%m%d%H}.csv"
    path.write_text(f"{at(RECENT)},{UUID(int=1)},1.5\n")
    component = station(tmp_path, format="csv", interval=1)

    async with running(component):
        component.system.store(reading(20, 2.5, id=2, at=RECENT))
        await component.system.flush()
        await wait_for_lines(path, 2)

    widths = [len(line.split(",")) for line in path.read_text().splitlines()]
    assert widths == [3, 7]


@asynccontextmanager
async def running(component: Station) -> AsyncIterator[None]:
    system = component.system
    system.start()
    live = system.exporters._ExporterManager__live  # type: ignore[attr-defined]
    await wait_for_condition(
        "the start check ends",
        lambda: system.running and "readings" in live and live["readings"].checked,
        30,
    )
    try:
        yield
    finally:
        await system.stop()


async def wait_for_lines(path: Path, count: int) -> None:
    await wait_for_condition(
        f"{path.name} holds {count} lines",
        lambda: path.exists() and path.read_bytes().count(b"\n") == count,
        30,
    )


def test_a_writer_class_must_subclass_export_writer() -> None:
    with pytest.raises(ValueError, match="subclass of `ceres.exporter.ExportWriter`"):
        station(Path(), format={"class": f"{__name__}.Station"})
