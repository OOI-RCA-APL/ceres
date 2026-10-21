"""Exporters write stored records to files, the archive a component produces.

A file is the archive and the product, and the database is the working copy that produces it.
Automatic writes add and update rows in a file and never remove one, only a run with `replace`
removes rows.
"""

import csv
import io
import json
import math
import os
import re
import tempfile
import types
from abc import abstractmethod
from asyncio import CancelledError, Lock, Task, create_task
from collections import deque
from collections.abc import AsyncIterable, AsyncIterator, Iterable, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from string import Formatter
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Literal,
    Union,
    cast,
    get_args,
    get_origin,
    override,
)
from uuid import UUID

import anyio
from pydantic import Field

from ceres.__internal__.manager import BaseComponentManager
from ceres.concurrency import cancel, sleep, spawn
from ceres.config import ExporterPeriod
from ceres.data import DataObject, DateTime, Name, StrEnum, replace, uuid4
from ceres.data import dump as _dump
from ceres.directory import Directory
from ceres.entity import EntityType
from ceres.error import trace
from ceres.event import (
    ExportRunCompletedEvent,
    ExportRunFailedEvent,
    ExportRunProgressEvent,
    ExportRunStartedEvent,
)

if TYPE_CHECKING:
    from apscheduler.job import Job as InternalJob
    from apscheduler.schedulers.base import BaseScheduler

    from ceres.__internal__.protocols import ComponentSource
    from ceres.alert import Alert
    from ceres.config import ExporterConfig
    from ceres.logs import LogEntry
    from ceres.message import Message
    from ceres.particle import Particle

type ExportRecord = Message | Particle[Any] | Alert | LogEntry
"""A stored record of any kind an exporter writes."""

type ExportKey = tuple[datetime, UUID]
"""The `(timestamp, id)` pair that orders the records of every keyed file."""

__all__ = [
    "CsvFormat",
    "ExportColumn",
    "ExportFileError",
    "ExportKey",
    "ExportPath",
    "ExportRecord",
    "ExportRunRecord",
    "ExportRunState",
    "ExportSchema",
    "ExporterManager",
    "Format",
    "JsonLinesFormat",
    "LineFormat",
    "RawFormat",
    "atomic_write",
]

_CHUNK_SIZE = 1 << 20
"""Bytes read or buffered per file operation, large enough that thread hops stay rare."""

_RUN_RING_SIZE = 20
"""Runs each `ExporterManager` remembers, oldest dropped first."""

_EPOCH = datetime(2000, 1, 1, tzinfo=UTC)
"""Fixed start of the sample periods a path template is checked against."""

_ORDER = ["timestamp:asc", "id:asc"]

_RECORD_COLUMNS: dict[EntityType, tuple[str, ...]] = {
    EntityType.MESSAGE: ("timestamp", "id", "address", "connection", "direction", "data"),
    EntityType.PARTICLE: ("timestamp", "id", "address", "connection", "type"),
    EntityType.ALERT: ("timestamp", "id", "address", "level", "type", "data"),
    EntityType.LOG_ENTRY: ("timestamp", "id", "address", "level", "content"),
}


class ExportFileError(Exception):
    """Raised when an existing export file cannot take part in a merge."""


@dataclass(frozen=True, slots=True)
class ExportColumn:
    """One column of an export file and where its value sits in a record's JSON form."""

    name: str
    """Column name, nested fields joined with `.` and tuple items indexed."""

    path: tuple[str | int, ...]
    """Keys and indexes leading to the value in the record's JSON form."""

    def get(self, data: Any) -> Any:
        """Return this column's value from a record's JSON form, `None` when absent."""
        for segment in self.path:
            if isinstance(segment, int):
                if not isinstance(data, list) or segment >= len(cast("list[Any]", data)):
                    return None

                data = cast("list[Any]", data)[segment]
            elif isinstance(data, dict):
                data = cast("dict[str, Any]", data).get(segment)
            else:
                return None

        return data


@dataclass(frozen=True, slots=True)
class ExportSchema:
    """The columns of one exporter's files, derived from its kind and particle class."""

    exports: EntityType
    """Record kind the exporter writes."""

    columns: tuple[ExportColumn, ...]
    """Columns in file order, the key columns `timestamp` and `id` first."""

    @classmethod
    def create(
        cls,
        exports: EntityType,
        particle: type[Particle[Any]] | None = None,
    ) -> ExportSchema:
        """Derive the columns for records of `exports`, flattening the particle data class.

        Args:
            exports: Record kind the exporter writes.
            particle: Particle class whose data fields become columns, `None` for one `data`
                column holding each particle's whole data object.

        Raises:
            ValueError: If a data field's column name collides with another column.
        """
        columns = [ExportColumn(name, (name,)) for name in _RECORD_COLUMNS[exports]]
        if exports == EntityType.PARTICLE:
            if particle is None:
                columns.append(ExportColumn("data", ("data",)))
            else:
                columns.extend(_data_columns(particle.Data, (), ("data",)))

        seen: set[str] = set()
        for column in columns:
            if column.name in seen:
                raise ValueError(f"data field '{column.name}' collides with another column")

            seen.add(column.name)

        return cls(exports, tuple(columns))

    @property
    def names(self) -> list[str]:
        """Column names in file order."""
        return [column.name for column in self.columns]

    def row(self, record: ExportRecord) -> list[Any]:
        """Return a record's values in column order, in the JSON form the API serves."""
        data = _dump(record, mode="json")
        return [column.get(data) for column in self.columns]


def _strip_optional(annotation: Any) -> Any:
    if get_origin(annotation) in (Union, types.UnionType):
        arguments = [argument for argument in get_args(annotation) if argument is not type(None)]
        if len(arguments) == 1:
            return arguments[0]

    return annotation


def _data_columns(
    cls: type,
    names: tuple[str, ...],
    path: tuple[str | int, ...],
) -> Iterator[ExportColumn]:
    fields: dict[str, Any] = getattr(cls, "__pydantic_fields__", {})
    for name, field in fields.items():
        yield from _field_columns(field.annotation, (*names, name), (*path, name))


def _field_columns(
    annotation: Any,
    names: tuple[str, ...],
    path: tuple[str | int, ...],
) -> Iterator[ExportColumn]:
    # Nested objects and fixed tuples flatten to one column per leaf, while ragged lists and
    # mappings stay whole since their width varies from record to record.
    annotation = _strip_optional(annotation)
    arguments = get_args(annotation)
    if isinstance(annotation, type) and hasattr(annotation, "__pydantic_fields__"):
        yield from _data_columns(annotation, names, path)
    elif get_origin(annotation) is tuple and arguments and Ellipsis not in arguments:
        for index, argument in enumerate(arguments):
            yield from _field_columns(argument, (*names, str(index)), (*path, index))
    else:
        yield ExportColumn(".".join(names), path)


def _record_key(record: ExportRecord) -> ExportKey:
    return record.timestamp, record.id


def _parse_key(timestamp: bytes, id: bytes) -> ExportKey:
    return datetime.fromisoformat(timestamp.decode()), UUID(id.decode())


def _compact(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _finite(value: Any) -> Any:
    # JSON has no NaN or infinity, so a non-finite float becomes `null` as the API serves it.
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, list):
        return [_finite(item) for item in cast("list[Any]", value)]
    if isinstance(value, dict):
        return {key: _finite(item) for key, item in cast("dict[str, Any]", value).items()}

    return value


class _Output:
    """Buffered binary file writer that hops to a thread once per chunk."""

    __slots__ = ("__buffer", "__file")

    def __init__(self, file: anyio.AsyncFile[bytes]) -> None:
        self.__file = file
        self.__buffer = bytearray()

    async def write(self, data: bytes) -> None:
        self.__buffer += data
        if len(self.__buffer) >= _CHUNK_SIZE:
            await self.flush()

    async def flush(self) -> None:
        if self.__buffer:
            await self.__file.write(bytes(self.__buffer))
            self.__buffer.clear()


@asynccontextmanager
async def _output(path: Path, mode: Literal["wb", "ab"] = "wb") -> AsyncIterator[_Output]:
    async with await anyio.open_file(path, mode) as file:
        output = _Output(file)
        yield output
        await output.flush()


async def _physical_lines(path: Path) -> AsyncIterator[bytes]:
    # A final line without its newline is a torn append, so it counts as absent.
    async with await anyio.open_file(path, "rb") as file:
        pending = b""
        while chunk := await file.read(_CHUNK_SIZE):
            pending += chunk
            end = pending.rfind(b"\n") + 1
            if end:
                for line in pending[:end].splitlines(keepends=True):
                    yield line

                pending = pending[end:]


class Format(DataObject, abstract=True):
    """Base class of an export file format.

    Records reach every method as typed entities sorted by `timestamp` then `id`, and columns
    come from the exporter's `ExportSchema`, never from the records observed.
    """

    extension: ClassVar[str]
    """File extension the exporter appends to every rendered path, such as `.csv`."""

    appendable: ClassVar[bool] = False
    """Whether `append` adds records to an existing file without rewriting it."""

    schema_bound: ClassVar[bool] = False
    """Whether a particle exporter must name its particle class so the columns are fixed."""

    keyed: ClassVar[bool] = False
    """Whether files keep records sorted by key, which `merge` and `keys` need."""

    exports: ClassVar[frozenset[EntityType] | None] = None
    """Record kinds the format can write, `None` for every kind."""

    @abstractmethod
    async def write(
        self,
        path: Path,
        schema: ExportSchema,
        records: AsyncIterable[ExportRecord],
    ) -> None:
        """Write a complete file holding `records` at `path`."""
        ...

    async def append(
        self,
        path: Path,
        schema: ExportSchema,
        records: AsyncIterable[ExportRecord],
    ) -> None:
        """Add `records` to the end of the file at `path`, creating it when missing."""
        raise NotImplementedError(f"`{type(self).__name__}` cannot append")

    async def merge(
        self,
        path: Path,
        schema: ExportSchema,
        records: AsyncIterable[ExportRecord],
        into: Path,
    ) -> None:
        """Write the file at `path` merged with `records` to `into`, `records` winning on a key.

        Raises:
            ExportFileError: If the file at `path` cannot be merged into.
        """
        raise NotImplementedError(f"`{type(self).__name__}` cannot merge")

    def keys(self, path: Path, schema: ExportSchema) -> AsyncIterator[ExportKey]:
        """Yield the key of every record in the file at `path`, in file order."""
        raise NotImplementedError(f"`{type(self).__name__}` has no keys")


class LineFormat(Format, abstract=True):
    """Format whose file is an optional header followed by one encoded line per record.

    Subclasses provide `header`, `encode` and `key`. A merge passes the lines it keeps through
    as bytes and parses only their keys.
    """

    appendable: ClassVar[bool] = True
    keyed: ClassVar[bool] = True

    def header(self, schema: ExportSchema) -> bytes:
        """Return the bytes that open every file, empty for none."""
        return b""

    @abstractmethod
    def encode(self, schema: ExportSchema, record: ExportRecord) -> bytes:
        """Return one record's line, including its line terminator."""
        ...

    def key(self, line: bytes) -> ExportKey:
        """Parse the key out of one line `encode` wrote."""
        raise NotImplementedError(f"`{type(self).__name__}` has no keys")

    def split(self, lines: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
        """Group a file's physical lines into records, one line per record by default."""
        return lines

    async def lines(
        self,
        path: Path,
        schema: ExportSchema,
    ) -> AsyncIterator[tuple[ExportKey, bytes]]:
        """Yield the key and bytes of every complete record in the file at `path`.

        Raises:
            ExportFileError: If the file's header differs from the one `schema` gives.
        """
        header = self.header(schema)
        records = aiter(self.split(_physical_lines(path)))
        if header:
            first = await anext(records, None)
            if first is not None and first != header:
                raise ExportFileError(f"'{path}' has another header, so a run must replace it")

        async for line in records:
            yield self.key(line), line

    @override
    async def write(
        self,
        path: Path,
        schema: ExportSchema,
        records: AsyncIterable[ExportRecord],
    ) -> None:
        async with _output(path) as output:
            await output.write(self.header(schema))
            async for record in records:
                await output.write(self.encode(schema, record))

    @override
    async def append(
        self,
        path: Path,
        schema: ExportSchema,
        records: AsyncIterable[ExportRecord],
    ) -> None:
        file = anyio.Path(path)
        empty = not await file.exists() or (await file.stat()).st_size == 0
        async with _output(path, "ab") as output:
            if empty:
                await output.write(self.header(schema))
            async for record in records:
                await output.write(self.encode(schema, record))

    @override
    async def merge(
        self,
        path: Path,
        schema: ExportSchema,
        records: AsyncIterable[ExportRecord],
        into: Path,
    ) -> None:
        if not self.keyed:
            return await super().merge(path, schema, records, into)

        lines = aiter(self.lines(path, schema))

        async def next_line(current: tuple[ExportKey, bytes]) -> tuple[ExportKey, bytes] | None:
            line = await anext(lines, None)
            if line is not None and line[0] <= current[0]:
                raise ExportFileError(f"'{path}' is not sorted by key, so a run must replace it")

            return line

        async with _output(into) as output:
            await output.write(self.header(schema))
            kept = await anext(lines, None)
            previous: ExportKey | None = None
            async for record in records:
                key = _record_key(record)
                if previous is not None and key <= previous:
                    raise ExportFileError("records arrived out of key order")

                previous = key
                while kept is not None and kept[0] < key:
                    await output.write(kept[1])
                    kept = await next_line(kept)

                if kept is not None and kept[0] == key:
                    kept = await next_line(kept)

                await output.write(self.encode(schema, record))

            while kept is not None:
                await output.write(kept[1])
                kept = await next_line(kept)

    @override
    async def keys(self, path: Path, schema: ExportSchema) -> AsyncIterator[ExportKey]:
        async for key, _ in self.lines(path, schema):
            yield key


class CsvFormat(LineFormat):
    """Comma separated values, one column per schema column under a header row.

    Nested values are JSON text, an absent value is an empty cell, and a non-finite float is
    `nan`, `inf` or `-inf`.
    """

    extension: ClassVar[str] = ".csv"
    schema_bound: ClassVar[bool] = True

    @staticmethod
    def __cell(value: Any) -> Any:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, float) and not math.isfinite(value):
            return "nan" if math.isnan(value) else ("inf" if value > 0 else "-inf")
        if isinstance(value, (list, dict, float)):
            return _compact(value)

        return value

    @staticmethod
    def __line(cells: Iterable[Any]) -> bytes:
        buffer = io.StringIO()
        csv.writer(buffer, lineterminator="\n").writerow(cells)
        return buffer.getvalue().encode()

    @override
    def header(self, schema: ExportSchema) -> bytes:
        return self.__line(schema.names)

    @override
    def encode(self, schema: ExportSchema, record: ExportRecord) -> bytes:
        return self.__line(self.__cell(value) for value in schema.row(record))

    @override
    def key(self, line: bytes) -> ExportKey:
        timestamp, id, _ = line.split(b",", 2)
        return _parse_key(timestamp, id)

    @override
    async def split(self, lines: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
        # A quoted cell may hold newlines, so a record ends only where its quotes balance.
        pending = b""
        async for line in lines:
            pending += line
            if pending.count(b'"') % 2 == 0:
                yield pending
                pending = b""


class JsonLinesFormat(LineFormat):
    """One compact JSON object per line, keyed by the schema's column names in order.

    A non-finite float is `null`, since JSON has no form for it.
    """

    extension: ClassVar[str] = ".jsonl"

    _KEY: ClassVar[re.Pattern[bytes]] = re.compile(rb'^\{"timestamp":"([^"]+)","id":"([^"]+)"')

    @override
    def encode(self, schema: ExportSchema, record: ExportRecord) -> bytes:
        values = dict(zip(schema.names, _finite(schema.row(record)), strict=True))
        return (_compact(values) + "\n").encode()

    @override
    def key(self, line: bytes) -> ExportKey:
        match = self._KEY.match(line)
        if match is None:
            raise ExportFileError(f"line has no leading key: {line[:80]!r}")

        return _parse_key(match[1], match[2])


class RawFormat(LineFormat):
    """The data bytes of each message, concatenated in key order with nothing between them.

    Records carry no key in the file, so a run must replace the file it rewrites.
    """

    extension: ClassVar[str] = ".bin"
    keyed: ClassVar[bool] = False
    exports: ClassVar[frozenset[EntityType] | None] = frozenset({EntityType.MESSAGE})

    @override
    def encode(self, schema: ExportSchema, record: ExportRecord) -> bytes:
        return cast("Message", record).data


BUILTIN_FORMATS: dict[str, type[Format]] = {
    "csv": CsvFormat,
    "jsonl": JsonLinesFormat,
    "raw": RawFormat,
}
"""The formats an exporter names with a bare string, such as `format: csv`."""


def _fsync(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _commit(temporary: Path, final: Path) -> None:
    _fsync(temporary)
    os.replace(temporary, final)
    # The rename lives in the directory entry, so the directory needs its own sync.
    _fsync(final.parent)


@asynccontextmanager
async def atomic_write(directory: Directory | Path, path: str | Path) -> AsyncIterator[Path]:
    """Yield a temporary sibling of `directory / path` that replaces it when the block exits.

    Readers see the old file or the new one, never a partial write. The temporary file is
    removed when the block raises.

    Args:
        directory: Directory the file lives under.
        path: File path relative to `directory`.

    Raises:
        ValueError: If `path` leads outside `directory`.
    """
    root = Path(directory).resolve()
    final = (root / path).resolve()
    if not final.is_relative_to(root) or final == root:
        raise ValueError(f"'{path}' leads outside '{root}'")

    await anyio.Path(final.parent).mkdir(parents=True, exist_ok=True)
    descriptor, name = await spawn(
        tempfile.mkstemp,
        dir=final.parent,
        prefix=f".{final.name}.",
        suffix=".tmp",
    )
    os.close(descriptor)
    temporary = Path(name)
    try:
        yield temporary
        await spawn(_commit, temporary, final)
    finally:
        await anyio.Path(temporary).unlink(missing_ok=True)


def period_start(period: ExporterPeriod, moment: datetime) -> datetime:
    """Return the UTC start of the `period` holding `moment`."""
    moment = moment.astimezone(UTC)
    match period:
        case ExporterPeriod.HOUR:
            return moment.replace(minute=0, second=0, microsecond=0)
        case ExporterPeriod.DAY:
            return moment.replace(hour=0, minute=0, second=0, microsecond=0)
        case ExporterPeriod.MONTH:
            return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        case ExporterPeriod.ALL:
            return datetime.min.replace(tzinfo=UTC)


def period_shift(period: ExporterPeriod, start: datetime, count: int) -> datetime:
    """Return the start of the period `count` periods after the one starting at `start`."""
    match period:
        case ExporterPeriod.HOUR:
            return start + timedelta(hours=count)
        case ExporterPeriod.DAY:
            return start + timedelta(days=count)
        case ExporterPeriod.MONTH:
            months = start.year * 12 + start.month - 1 + count
            return start.replace(year=months // 12, month=months % 12 + 1)
        case ExporterPeriod.ALL:
            return start


def periods(
    period: ExporterPeriod,
    after: datetime,
    before: datetime,
) -> Iterator[tuple[datetime | None, datetime | None]]:
    """Yield the `(start, end)` of every period overlapping `[after, before)`, `None` for all."""
    if period == ExporterPeriod.ALL:
        yield None, None
        return

    start = period_start(period, after)
    while start < before:
        end = period_shift(period, start, 1)
        yield start, end
        start = end


@dataclass(frozen=True, slots=True)
class ExportPath:
    """An exporter's path template, checked to give each period its own file."""

    template: str
    """`strftime` template of the period's UTC start, with `{exporter}` and `{connection}`."""

    period: ExporterPeriod
    """Time one file covers."""

    exporter: str
    """Exporter name `{exporter}` renders to."""

    connection: str | None
    """Connection name `{connection}` renders to, `None` when the filter pins none."""

    extension: str
    """Format extension appended to every rendered path."""

    @classmethod
    def create(
        cls,
        template: str,
        period: ExporterPeriod,
        exporter: str,
        connection: str | None,
        extension: str,
    ) -> ExportPath:
        """Check `template` and return the path it describes.

        Raises:
            ValueError: If the template uses an unknown placeholder, leaves the directory,
                ends in a format extension, or renders one file for two periods.
        """
        for _, field, spec, conversion in Formatter().parse(template):
            if field is None:
                continue
            if field not in ("exporter", "connection") or spec or conversion:
                raise ValueError(
                    f"path placeholders are `{{exporter}}` and `{{connection}}`, got `{{{field}}}`"
                )
            if field == "connection" and connection is None:
                raise ValueError("`{connection}` needs a filter that pins one connection")

        if period == ExporterPeriod.ALL and re.search("%[^%]", template.replace("%%", "")):
            raise ValueError("a `period: all` path takes no time directives")

        path = cls(template, period, exporter, connection, extension)
        sample = path.render(_EPOCH)[: -len(extension)]
        parts = PurePosixPath(sample).parts
        if sample.startswith("/") or sample.endswith("/") or ".." in parts or "." in parts:
            raise ValueError(f"path '{template}' must name a file inside the directory")

        for known in sorted(
            {extension, *(format.extension for format in BUILTIN_FORMATS.values())}
        ):
            if sample.lower().endswith(known):
                raise ValueError(
                    f"the format adds `{extension}`, so the path must not end in `{known}`"
                )

        if period != ExporterPeriod.ALL:
            path.__check_collisions()

        return path

    def render(self, start: datetime | None) -> str:
        """Return the file path for the period starting at `start`, relative to the directory."""
        text = (start or _EPOCH).strftime(self.template)
        return text.format(exporter=self.exporter, connection=self.connection) + self.extension

    def __check_collisions(self) -> None:
        seen: dict[str, datetime] = {}
        for start in self.__probes():
            rendered = self.render(start)
            earlier = seen.setdefault(rendered, start)
            if earlier != start:
                raise ValueError(
                    f"path '{self.template}' writes the periods starting {earlier.isoformat()} "
                    f"and {start.isoformat()} to one file '{rendered}'"
                )

    def __probes(self) -> Iterator[datetime]:
        # Each sweep varies one unit of the start, so a template missing that unit renders two
        # starts of one sweep alike. The shifted years catch a two-digit year.
        for years in (0, 100, 400):
            base = _EPOCH.replace(year=_EPOCH.year + years)
            if self.period == ExporterPeriod.HOUR:
                yield from (base + timedelta(hours=hours) for hours in range(48))
                yield from (base + timedelta(days=days) for days in range(367))
                continue

            start, stop = base, base + timedelta(days=367)
            while start < stop:
                yield start
                start = period_shift(self.period, start, 1)


class ExportRunState(StrEnum):
    """Where an export run stands."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ExportRunRecord(DataObject):
    """One export run over `[after, before)`, kept in its manager's ring of recent runs."""

    id: UUID
    """Run ID, returned when the run starts."""

    exporter: Name
    """Name of the exporter the run writes for."""

    after: DateTime
    """Inclusive start of the requested range."""

    before: DateTime
    """Exclusive end of the requested range."""

    replace: bool
    """Whether the run rewrites each period's file from the database alone."""

    state: ExportRunState = ExportRunState.RUNNING
    """Where the run stands."""

    started: DateTime
    """When the run started."""

    ended: DateTime | None = None
    """When the run completed or failed, `None` while it runs."""

    count: int = 0
    """Records written so far."""

    files: list[str] = Field(default_factory=list)
    """Files written so far, relative to the exporter's directory."""

    exception: str | None = None
    """Why the run failed, `None` unless it failed."""


class ExporterManager(BaseComponentManager):
    """Component-level manager that runs each registered exporter's re-runs and schedule.

    One lock per exporter serializes every write to that exporter's files.
    """

    __slots__ = (
        "__scheduler",
        "__exporters",
        "__locks",
        "__runs",
        "__tasks",
    )

    def __init__(self, source: ComponentSource, /) -> None:
        super().__init__(source)
        self.__scheduler = self.__create_scheduler()
        self.__exporters: dict[str, ExporterConfig] = {}
        self.__locks: dict[str, Lock] = {}
        self.__runs: deque[ExportRunRecord] = deque(maxlen=_RUN_RING_SIZE)
        self.__tasks: dict[UUID, Task[None]] = {}

    @classmethod
    def __create_scheduler(cls) -> BaseScheduler:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        return AsyncIOScheduler(timezone=UTC)

    @property
    def count(self) -> int:
        """Number of registered exporters."""
        return len(self.__exporters)

    async def __run__(self) -> None:
        try:
            self.__sync_schedules()
            self.__scheduler.start()
            await sleep(...)
        finally:
            if self.__scheduler.running:
                self.__scheduler.shutdown(wait=False)

            self.__scheduler = self.__create_scheduler()
            await cancel(*self.__tasks.values())

    def add(self, exporter: ExporterConfig) -> None:
        """Register an exporter, replacing any registered under the same name."""
        self.remove(exporter.name)
        self.__exporters[exporter.name] = exporter
        self.__locks[exporter.name] = Lock()
        self.__sync_schedules()

    def get(self, name: str) -> ExporterConfig | None:
        """Return the exporter registered under `name`, or `None`."""
        return self.__exporters.get(name)

    def get_all(self) -> list[ExporterConfig]:
        """Return every registered exporter."""
        return list(self.__exporters.values())

    def remove(self, name: str) -> ExporterConfig | None:
        """Unregister an exporter and cancel its schedule, leaving its running runs alone.

        Returns:
            The removed exporter, or `None` if none was registered under `name`.
        """
        from apscheduler.jobstores.base import JobLookupError

        try:
            self.__scheduler.remove_job(name)
        except JobLookupError:
            pass

        self.__locks.pop(name, None)
        return self.__exporters.pop(name, None)

    def clear(self) -> None:
        """Unregister every exporter and cancel every schedule."""
        for name in list(self.__exporters):
            self.remove(name)

    def get_next_fire_time(self, name: str) -> datetime | None:
        """Return when the named exporter's schedule next runs, `None` without one."""
        if not self.__scheduler.running:
            return None

        internal: InternalJob | None = self.__scheduler.get_job(name)
        return internal.next_run_time if internal is not None else None

    def get_runs(self, name: str | None = None) -> list[ExportRunRecord]:
        """Return the recent runs, newest first, of the named exporter or of every exporter."""
        return [run for run in reversed(self.__runs) if name is None or run.exporter == name]

    def start(
        self,
        name: str,
        after: datetime,
        before: datetime | None = None,
        *,
        replace: bool = False,
    ) -> ExportRunRecord:
        """Start a run writing the periods that overlap `[after, before)` and return its record.

        A run merges the database's records into each period's file, the database winning on a
        shared key, so a period with no stored records keeps its file. With `replace` it
        rewrites each period's file from the database alone and removes an empty period's file.

        Args:
            name: Name of the exporter to run.
            after: Inclusive start of the range.
            before: Exclusive end of the range, defaulting to now.
            replace: Whether to rewrite each file from the database alone.

        Raises:
            KeyError: If no exporter is registered under `name`.
            ValueError: If `after` does not precede `before`, or the format cannot merge and
                `replace` is false.
        """
        exporter = self.__exporters.get(name)
        if exporter is None:
            raise KeyError(name)

        after = after.astimezone(UTC)
        before = (before or datetime.now(UTC)).astimezone(UTC)
        if after >= before:
            raise ValueError("`after` must precede `before`")

        format = exporter.create_format()
        if not replace and not format.keyed:
            raise ValueError(f"`{exporter.format_name}` cannot merge, so the run must replace")

        run = ExportRunRecord(
            id=uuid4(),
            exporter=name,
            after=after,
            before=before,
            replace=replace,
            started=datetime.now(UTC),
        )
        self.__runs.append(run)
        task = create_task(self.__export(exporter, format, run))
        self.__tasks[run.id] = task
        task.add_done_callback(lambda _: self.__tasks.pop(run.id, None))
        return run

    async def run(
        self,
        name: str,
        after: datetime,
        before: datetime | None = None,
        *,
        replace: bool = False,
    ) -> ExportRunRecord:
        """Run like `start` and return the run's record once it completes or fails."""
        run = self.start(name, after, before, replace=replace)
        task = self.__tasks.get(run.id)
        if task is not None:
            await task

        return next((current for current in self.__runs if current.id == run.id), run)

    def __sync_schedules(self) -> None:
        from ceres.job import _get_trigger_adapter_class

        TriggerAdapter = _get_trigger_adapter_class()
        for name, exporter in self.__exporters.items():
            if exporter.schedule is None or self.__scheduler.get_job(name) is not None:
                continue

            self.__scheduler.add_job(
                self.__scheduled,
                args=[name],
                trigger=TriggerAdapter(exporter.schedule.create_trigger()),
                name=name,
                id=name,
            )

    async def __scheduled(self, name: str) -> None:
        exporter = self.__exporters.get(name)
        if exporter is None:
            return

        now = datetime.now(UTC)
        lookback = exporter.lookback or 0
        after = period_shift(exporter.period, period_start(exporter.period, now), -lookback)
        self.start(name, after, now)

    def __update(self, run: ExportRunRecord, **changes: Any) -> ExportRunRecord:
        updated = replace(run, **changes)
        for index, current in enumerate(self.__runs):
            if current.id == run.id:
                self.__runs[index] = updated

        return updated

    def __records(self, exporter: ExporterConfig) -> Any:
        match exporter.exports:
            case EntityType.MESSAGE:
                return self.__system__.messages
            case EntityType.PARTICLE:
                return self.__system__.particles
            case EntityType.ALERT:
                return self.__system__.alerts
            case EntityType.LOG_ENTRY:
                return self.__system__.log

    def __query(
        self, exporter: ExporterConfig, start: datetime | None, end: datetime | None
    ) -> Any:
        # Range keywords would override the user filter's own bounds, so the range is a
        # filter of its own, joined with `&`.
        Filter: Any = exporter.filter_class()
        bounds: Any = Filter(after=start, before=end, order=_ORDER)
        filter: Any = bounds if exporter.filter is None else bounds & exporter.filter
        particle = exporter.particle_class()
        if particle is not None:
            return self.__records(exporter).where(filter, cls=particle)

        return self.__records(exporter).where(filter)

    def __directory(self, exporter: ExporterConfig) -> Directory:
        directory = getattr(self.__component__, exporter.directory, None)
        if not isinstance(directory, Directory):
            raise ValueError(f"`{exporter.directory}` is not a `Directory` of this component")

        return directory

    async def __export(
        self, exporter: ExporterConfig, format: Format, run: ExportRunRecord
    ) -> None:
        events = self.__system__.events
        events.emit(
            ExportRunStartedEvent,
            exporter=run.exporter,
            run=run.id,
            after=run.after,
            before=run.before,
            replace=run.replace,
        )
        try:
            directory = self.__directory(exporter)
            schema = exporter.create_schema()
            path = exporter.create_path()
            lock = self.__locks.setdefault(exporter.name, Lock())
            async with lock:
                for start, end in periods(exporter.period, run.after, run.before):
                    relative = path.render(start)
                    count = await self.__export_period(
                        exporter, format, schema, directory, relative, start, end, run.replace
                    )
                    if count is None:
                        continue

                    run = self.__update(run, count=run.count + count, files=[*run.files, relative])
                    events.emit(
                        ExportRunProgressEvent,
                        exporter=run.exporter,
                        run=run.id,
                        period=start,
                        count=count,
                        path=relative,
                    )
        except CancelledError:
            self.__fail(run, RuntimeError("component stopped"))
            raise
        except Exception as exception:
            self.__fail(run, exception)
            return

        run = self.__update(run, state=ExportRunState.COMPLETED, ended=datetime.now(UTC))
        events.emit(
            ExportRunCompletedEvent,
            exporter=run.exporter,
            run=run.id,
            count=run.count,
            files=run.files,
            after=run.after,
            before=run.before,
        )
        shown = ", ".join(run.files[:5]) + (
            f" and {len(run.files) - 5} more" if len(run.files) > 5 else ""
        )
        self.__system__.log.info(
            f"Exporter '{run.exporter}' wrote {run.count} records over "
            f"[{run.after.isoformat()}, {run.before.isoformat()}) to {len(run.files)} files"
            + (f": {shown}" if shown else "")
        )

    def __fail(self, run: ExportRunRecord, exception: BaseException) -> None:
        run = self.__update(
            run,
            state=ExportRunState.FAILED,
            ended=datetime.now(UTC),
            exception=str(exception) or type(exception).__name__,
        )
        self.__system__.events.emit(
            ExportRunFailedEvent,
            exporter=run.exporter,
            run=run.id,
            exception=trace(exception),
        )

    async def __export_period(
        self,
        exporter: ExporterConfig,
        format: Format,
        schema: ExportSchema,
        directory: Directory,
        relative: str,
        start: datetime | None,
        end: datetime | None,
        replace: bool,
    ) -> int | None:
        # Returns the records written, or `None` when the period's file stays untouched.
        final = anyio.Path(directory / relative)
        async with self.__query(exporter, start, end) as results:
            stream = _Counted(results)
            first = await anext(stream, None)
            if first is None:
                if replace:
                    await final.unlink(missing_ok=True)

                return None

            records = _prepend(first, stream)
            exists = await final.exists()
            async with atomic_write(directory, relative) as temporary:
                if exists and not replace:
                    await format.merge(Path(final), schema, records, temporary)
                else:
                    await format.write(temporary, schema, records)

        return stream.count


class _Counted[T]:
    __slots__ = ("__iterator", "count")

    def __init__(self, iterable: AsyncIterable[T]) -> None:
        self.__iterator = aiter(iterable)
        self.count = 0

    def __aiter__(self) -> _Counted[T]:
        return self

    async def __anext__(self) -> T:
        item = await anext(self.__iterator)
        self.count += 1
        return item


async def _prepend[T](first: T, rest: AsyncIterator[T]) -> AsyncIterator[T]:
    yield first
    async for item in rest:
        yield item
