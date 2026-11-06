"""The custom writer contract `docs/exporters.md` documents, through the writers it shows."""

import inspect
import json
import re
from collections.abc import AsyncIterable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar, override
from uuid import UUID

import anyio
import pytest

from ceres import (
    Address,
    EntityType,
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
from ceres.exporter import ExportConflict, ExportRunState
from tests.test_exporter import RECENT, START, Exported, Live

GUIDE = Path(__file__).parent.parent / "docs" / "exporters.md"


class ReadingData(ParticleData):
    celsius: float
    label: str = ""


class Reading(Particle[ReadingData]):
    type = "reading"
    data: ReadingData


# The guide's writers. `test_the_guide_shows_these_writers` holds them equal to the guide.


class TabWriter(ExportLineWriter):
    """Tab separated values, optionally with a header line."""

    extension: ClassVar[str] = ".tsv"
    resumable: ClassVar[bool] = True

    header_line: bool = False

    @staticmethod
    def cell(value: object) -> str:
        # A tab or line break inside a value would split its cell or its line.
        text = "" if value is None else str(value)
        return text.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n")

    @override
    def header(self, schema: ExportSchema) -> bytes:
        names = (self.cell(name) for name in schema.names)
        return ("\t".join(names) + "\n").encode() if self.header_line else b""

    @override
    def encode(self, schema: ExportSchema, record: ExportRecord) -> bytes:
        return ("\t".join(self.cell(value) for value in schema.row(record)) + "\n").encode()

    @override
    def key(self, line: bytes) -> ExportKey:
        timestamp, id = line.rstrip(b"\n").split(b"\t", 2)[:2]
        return datetime.fromisoformat(timestamp.decode()), UUID(id.decode())


class SummaryWriter(ExportWriter):
    """One JSON document per file holding every record's row."""

    extension: ClassVar[str] = ".json"

    @override
    async def write(
        self, path: Path, schema: ExportSchema, records: AsyncIterable[ExportRecord]
    ) -> None:
        # Writes each row as it arrives, so a file of any size holds one row in memory.
        async with await anyio.open_file(path, "w") as file:
            await file.write(f'{{"columns": {json.dumps(schema.names)}, "rows": [')
            separator = ""
            async for record in records:
                row = dict(zip(schema.names, schema.row(record), strict=True))
                await file.write(separator + json.dumps(row))
                separator = ", "

            await file.write("]}")


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


def readings(writer: type[ExportWriter] | str, **exporter: Any) -> dict[str, Any]:
    arguments = exporter.pop("arguments", None)
    format: Any = writer
    if not isinstance(writer, str):
        format = {"class": f"{__name__}.{writer.__name__}", "arguments": arguments or {}}

    return {
        "name": "readings",
        "exports": "particle",
        "type": f"{__name__}.Reading",
        "format": format,
        "path": "{yyyy}{MM}{dd}{HH}",
        **exporter,
    }


def reading(
    minutes: float, celsius: float = 1.5, *, id: int, at: datetime = START, **data: Any
) -> Reading:
    return Reading(
        type="reading",
        id=UUID(int=id),
        address=Address("@archive"),
        timestamp=at + timedelta(minutes=minutes),
        data=ReadingData(celsius=celsius, **data),
    )


def text(exported: Exported) -> dict[str, str]:
    return {path: data.decode() for path, data in exported.files().items()}


def stamp(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def test_the_guide_shows_these_writers() -> None:
    blocks = re.findall(r"```python\n(.*?)```", GUIDE.read_text(), re.DOTALL)
    for writer in (TabWriter, SummaryWriter):
        source = inspect.getsource(writer)
        assert any(source in block for block in blocks), f"the guide's {writer.__name__} differs"


async def test_the_guide_writer_takes_arguments_and_fields(tmp_path: Path) -> None:
    exported = Exported.create(
        tmp_path,
        **readings(
            TabWriter,
            arguments={"header_line": True},
            live=False,
            fields={"timestamp": "timestamp", "id": "id", "t": "celsius"},
        ),
    )
    await exported.store(reading(20, 2.5, id=2), reading(10, id=1))

    await exported.run(hours=1)

    assert text(exported) == {
        "2026010100.tsv": (
            "timestamp\tid\tt\n"
            f"{stamp(START + timedelta(minutes=10))}\t{UUID(int=1)}\t1.5\n"
            f"{stamp(START + timedelta(minutes=20))}\t{UUID(int=2)}\t2.5\n"
        )
    }


async def test_the_guide_line_writer_resumes_after_a_header_with_escaped_names(
    tmp_path: Path,
) -> None:
    writer = TabWriter(header_line=True)
    fields = [("timestamp", "timestamp"), ("id", "id"), ("a\tb\nc", "label")]
    schema = ExportSchema.create(EntityType.PARTICLE, Reading, "readings", fields)

    async def records() -> AsyncIterable[ExportRecord]:
        yield reading(10, id=1, label="x\ty")

    path = tmp_path / "readings.tsv"
    await writer.write(path, schema, records())

    assert path.read_text().splitlines()[0] == "timestamp\tid\ta\\tb\\nc"
    assert await writer.tail(path, schema) == (
        (START + timedelta(minutes=10), UUID(int=1)),
        path.stat().st_size,
    )


def test_the_guide_line_writer_escapes_tabs_and_line_breaks() -> None:
    assert TabWriter.cell("a\tb\nc\\d") == "a\\tb\\nc\\\\d"
    assert TabWriter.cell(None) == ""


async def test_a_whole_file_writer_overwrites_keeps_and_purges(tmp_path: Path) -> None:
    exported = Exported.create(tmp_path, **readings(SummaryWriter, live=False))
    # Stored history reaching the file's start lets `overwrite` rewrite it.
    await exported.store(reading(0, id=1))

    await exported.run(hours=2)
    written = json.loads((tmp_path / "2026010100.json").read_text())
    assert [row["celsius"] for row in written["rows"]] == [1.5]
    assert written["columns"][:2] == ["timestamp", "id"]

    await exported.store(reading(20, 2.5, id=2))
    skipped = await exported.run(hours=2, on_conflict=ExportConflict.SKIP)
    assert skipped.kept == 1
    assert len(json.loads((tmp_path / "2026010100.json").read_text())["rows"]) == 1

    await exported.run(hours=2)
    assert len(json.loads((tmp_path / "2026010100.json").read_text())["rows"]) == 2

    (tmp_path / "2026010101.json").write_text("stale")
    purged = await exported.run(hours=2, on_conflict=ExportConflict.PURGE)
    assert purged.removed == 1
    assert list(exported.files()) == ["2026010100.json"]


async def test_a_failing_writer_keeps_the_old_file_and_leaves_no_temporary(
    tmp_path: Path,
) -> None:
    (tmp_path / "2026010100.json").write_text("old")
    exported = Exported.create(tmp_path, **readings(Failing, live=False))
    await exported.store(reading(10, id=1))

    run = await exported.run(hours=1, on_conflict=ExportConflict.PURGE)

    assert run.state == ExportRunState.FAILED
    assert run.exception is not None and "disk full" in run.exception
    assert text(exported) == {"2026010100.json": "old"}


@pytest.mark.parametrize(
    ("header", "fields"),
    [(False, None), (True, ["timestamp", "id"])],
    ids=["every-column", "key-columns-with-header"],
)
async def test_a_resumable_line_writer_heals_a_torn_line_on_start(
    tmp_path: Path, header: bool, fields: list[str] | None
) -> None:
    exporter = readings(
        TabWriter,
        arguments={"header_line": header},
        **({} if fields is None else {"fields": fields}),
    )
    exported = Live.create(tmp_path, interval=1, **exporter)
    await exported.store(reading(10, id=1, at=RECENT))
    await exported.run(hours=1, after=RECENT)
    path = f"{RECENT:%Y%m%d%H}.tsv"
    (tmp_path / path).write_text((tmp_path / path).read_text() + f"{stamp(RECENT)}\t000")
    await exported.store(reading(20, 2.5, id=2, at=RECENT))

    await exported.begin()
    try:
        lines = await exported.lines(path, 2 + header)
    finally:
        await exported.component.system.stop()

    assert [UUID(line.split(b"\t")[1].decode()).int for line in lines[header:]] == [1, 2]


async def test_an_encode_only_line_writer_never_reads_its_files(tmp_path: Path) -> None:
    (tmp_path / f"{RECENT:%Y%m%d%H}.txt").write_text("abc\n")
    live = await Live.started(tmp_path, **readings(Notes))
    try:
        await live.write(reading(20, id=2, at=RECENT))
        lines = await live.lines(f"{RECENT:%Y%m%d%H}.txt", 2)
    finally:
        await live.component.system.stop()

    assert lines == [b"abc", str(UUID(int=2)).encode()]


async def test_a_component_writes_computed_particles_with_a_writer(tmp_path: Path) -> None:
    # The guide's component example: a writer over particles the component never stored.
    schema = ExportSchema.create(EntityType.PARTICLE, Reading, "daily")

    async def computed() -> AsyncIterable[ExportRecord]:
        for record in (reading(10, id=1), reading(20, 2.5, id=2, label="a\tb")):
            yield record

    target = Mount(tmp_path) / "summary.json"
    async with atomic_write(target) as temporary:
        await SummaryWriter().write(temporary, schema, computed())

    written = json.loads(target.path.read_text())
    assert [row["celsius"] for row in written["rows"]] == [1.5, 2.5]
    assert written["rows"][1]["label"] == "a\tb"
    assert [path.name for path in tmp_path.iterdir()] == ["summary.json"]


async def test_a_column_change_appends_to_a_headerless_file_undetected(tmp_path: Path) -> None:
    # A known limit the guide states: headerless files hold nothing to compare columns with.
    path = f"{RECENT:%Y%m%d%H}.csv"
    (tmp_path / path).write_text(f"{stamp(RECENT)},{UUID(int=1)},1.5\n")
    live = await Live.started(tmp_path, **readings("csv"))
    try:
        await live.write(reading(20, 2.5, id=2, at=RECENT))
        lines = await live.lines(path, 2)
    finally:
        await live.component.system.stop()

    assert [len(line.split(b",")) for line in lines] == [3, 7]


def test_a_writer_class_must_subclass_export_writer() -> None:
    with pytest.raises(ValueError, match="subclass of `ceres.exporter.ExportWriter`"):
        Exported.create(Path(), **readings("csv", format={"class": "tests.test_exporter.Archive"}))
