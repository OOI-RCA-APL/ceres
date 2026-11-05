"""Exporters write stored records to files, the archive a component produces.

A file is the archive and the product, and the database is the working copy that produces it.
A run never merges into a file. It writes a whole file from the database, keeps the file, or
removes it, as its conflict mode decides.
"""

import csv
import dataclasses
import functools
import io
import json
import math
import os
import re
import tempfile
import types
from abc import abstractmethod
from asyncio import CancelledError, Lock, Task, create_task
from asyncio import Event as AsyncEvent
from collections import deque
from collections.abc import (
    AsyncIterable,
    AsyncIterator,
    Awaitable,
    Callable,
    Iterable,
    Iterator,
    Mapping,
    Sequence,
)
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Final,
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
from ceres.entity import EntityType
from ceres.error import AlreadyExistsError, trace
from ceres.event import (
    ExportRunCompletedEvent,
    ExportRunFailedEvent,
    ExportRunProgressEvent,
    ExportRunStartedEvent,
)
from ceres.mount import Mount
from ceres.paths import PathTemplate

if TYPE_CHECKING:
    from apscheduler.job import Job as InternalJob
    from apscheduler.schedulers.base import BaseScheduler
    from pydantic.fields import FieldInfo

    from ceres.__internal__.database.writer import FlushSummary
    from ceres.__internal__.manager import BaseDatabaseManager
    from ceres.__internal__.netcdf import NetCDFTable, NetCDFVariable
    from ceres.__internal__.protocols import ComponentSource
    from ceres.address import Address, AddressSelector
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
    "ExportConflict",
    "ExportConflictError",
    "ExportFileAction",
    "ExportFileError",
    "ExportFilePlan",
    "ExportKeepReason",
    "ExportKey",
    "ExportPath",
    "ExportPlan",
    "ExportRangeMode",
    "ExportRecord",
    "ExportRunRecord",
    "ExportRunState",
    "ExportRunSummary",
    "ExportSchema",
    "ExportSpan",
    "ExporterManager",
    "Format",
    "JsonLinesFormat",
    "LineFormat",
    "NetCDFFormat",
    "RawFormat",
    "atomic_write",
    "effective_span",
]

_CHUNK_SIZE = 1 << 20
"""Bytes read or buffered per file operation, large enough that thread hops stay rare."""

_RUN_RING_SIZE = 20
"""Runs each `ExporterManager` remembers, oldest dropped first."""

_PENDING_RUNS = 2
"""Runs of one exporter that may run or wait at once, so repeated starts cannot pile up."""

_EPOCH = datetime(2000, 1, 1, tzinfo=UTC)
"""Fixed start of the sample periods a path template is checked against."""

_ORDER = ["timestamp:asc", "id:asc"]

_REVERSE_ORDER = ["timestamp:desc", "id:desc"]

TICK = timedelta(microseconds=1)
"""The finest step between two timestamps, which turns an inclusive bound exclusive."""

_START_CHECKS = 100
"""Periods a live exporter checks at start, newest first, so a long outage starts in bounded time."""

_SHOWN_FILES = 5
"""Files a run's completion log line names before it counts the rest."""

# Reading the umask means setting it, so the process reads it once while nothing else writes.
_UMASK = os.umask(0)
os.umask(_UMASK)

_RECORD_COLUMNS: dict[EntityType, tuple[str, ...]] = {
    EntityType.MESSAGE: ("timestamp", "id", "address", "connection", "direction", "data"),
    EntityType.PARTICLE: ("timestamp", "id", "address", "connection", "type"),
    EntityType.ALERT: ("timestamp", "id", "address", "level", "type", "data"),
    EntityType.LOG_ENTRY: ("timestamp", "id", "address", "level", "content"),
}


class ExportFileError(Exception):
    """Raised when a live exporter cannot read where an existing file ends."""


class ExportConflictError(ValueError):
    """Raised when a run with `on_conflict: error` finds files it would write already there."""

    def __init__(self, paths: Sequence[str]) -> None:
        shown = ", ".join(f"'{path}'" for path in paths[:_SHOWN_FILES])
        more = f" and {len(paths) - _SHOWN_FILES} more" if len(paths) > _SHOWN_FILES else ""
        super().__init__(f"Files already exist: {shown}{more}")
        self.paths = list(paths)


@dataclass(frozen=True, slots=True)
class ExportColumn:
    """One column of an export file and where its value sits in a record's JSON form."""

    name: str
    """Column name, the field's own name unless the exporter's `fields` renames it."""

    path: tuple[str | int, ...]
    """Keys and indexes leading to the value in the record's JSON form."""

    field: str
    """Field the column holds, nested fields joined with `.` and tuple items indexed."""

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
class ExportField:
    """One field of a particle's data class, with the fields of a nested data object."""

    name: str
    """Field name in its data class."""

    annotation: Any
    """Field type with `None` stripped from an optional."""

    info: FieldInfo
    """The field's pydantic definition, which holds its metadata and JSON schema extras."""

    fields: tuple[ExportField, ...]
    """Fields of the nested data object the field holds, empty for any other type."""


@dataclass(frozen=True, slots=True)
class ExportSchema:
    """The columns of one exporter's files, derived from its kind and particle class."""

    exports: EntityType
    """Record kind the exporter writes."""

    columns: tuple[ExportColumn, ...]
    """Columns in file order, the key columns `timestamp` and `id` first."""

    particle: type[Particle[Any]] | None = None
    """Particle class whose data the schema flattens, `None` for any other kind or for none."""

    fields: tuple[ExportField, ...] = ()
    """Fields of the particle class's data, empty without a particle class."""

    exporter: str | None = None
    """Name of the exporter writing the files, which a format may record in them."""

    address: Address | None = None
    """Address of the component whose exporter writes the files."""

    selection: tuple[tuple[str, str], ...] = ()
    """The exporter's `fields` as ordered `(alias, field)` pairs, empty for every column."""

    @classmethod
    def create(
        cls,
        exports: EntityType,
        particle: type[Particle[Any]] | None = None,
        exporter: str | None = None,
        fields: Sequence[tuple[str, str]] = (),
    ) -> ExportSchema:
        """Derive the columns for records of `exports`, flattening the particle data class.

        Args:
            exports: Record kind the exporter writes.
            particle: Particle class whose data fields become columns, `None` for one `data`
                column holding each particle's whole data object.
            exporter: Name of the exporter writing the files.
            fields: Ordered `(alias, field)` pairs choosing and renaming the columns, every
                column under its own name when empty. A field that holds nested or tuple
                columns selects all of them, each renamed under the alias.

        Raises:
            ValueError: If a data field's column name collides with another column, or
                `fields` names a field the records lack.
        """
        columns = [ExportColumn(name, (name,), name) for name in _RECORD_COLUMNS[exports]]
        data: tuple[ExportField, ...] = ()
        if exports == EntityType.PARTICLE:
            if particle is None:
                columns.append(ExportColumn("data", ("data",), "data"))
            else:
                data = _data_fields(particle.Data)
                for field in data:
                    columns.extend(_data_columns(field, (), ("data",)))

        if fields:
            columns = _select_columns(columns, fields)

        seen: set[str] = set()
        for column in columns:
            if column.name in seen:
                raise ValueError(f"data field '{column.name}' collides with another column")

            seen.add(column.name)

        return cls(exports, tuple(columns), particle, data, exporter, selection=tuple(fields))

    @property
    def names(self) -> list[str]:
        """Column names in file order."""
        return [column.name for column in self.columns]

    @property
    def keyed(self) -> bool:
        """Whether the first two columns hold each record's `timestamp` and `id` under their own
        names, where a resuming live exporter reads a line's key."""
        return [(column.name, column.field) for column in self.columns[:2]] == [
            ("timestamp", "timestamp"),
            ("id", "id"),
        ]

    def row(self, record: ExportRecord) -> list[Any]:
        """Return a record's values in column order, in the JSON form the API serves."""
        data = _dump(record, mode="json")
        return [column.get(data) for column in self.columns]


def _select_columns(
    columns: Sequence[ExportColumn], fields: Sequence[tuple[str, str]]
) -> list[ExportColumn]:
    selected: list[ExportColumn] = []
    for alias, field in fields:
        matches = [
            column
            for column in columns
            if column.field == field or column.field.startswith(f"{field}.")
        ]
        if not matches:
            known = ", ".join(f"`{column.field}`" for column in columns)
            raise ValueError(f"no field `{field}` to export, the fields are {known}")

        for column in matches:
            name = alias + column.field[len(field) :]
            if any(other.name == name for other in selected):
                raise ValueError(f"two fields export as column `{name}`")

            selected.append(ExportColumn(name, column.path, column.field))

    return selected


def _strip_optional(annotation: Any) -> Any:
    if get_origin(annotation) in (Union, types.UnionType):
        arguments = [argument for argument in get_args(annotation) if argument is not type(None)]
        if len(arguments) == 1:
            return arguments[0]

    return annotation


def _data_fields(cls: type) -> tuple[ExportField, ...]:
    infos: dict[str, FieldInfo] = getattr(cls, "__pydantic_fields__", {})
    fields: list[ExportField] = []
    for name, info in infos.items():
        annotation = _strip_optional(info.annotation)
        nested = isinstance(annotation, type) and hasattr(annotation, "__pydantic_fields__")
        fields.append(
            ExportField(name, annotation, info, _data_fields(annotation) if nested else ())
        )

    return tuple(fields)


def _data_columns(
    field: ExportField,
    names: tuple[str, ...],
    path: tuple[str | int, ...],
) -> Iterator[ExportColumn]:
    names, path = (*names, field.name), (*path, field.name)
    if field.fields:
        for inner in field.fields:
            yield from _data_columns(inner, names, path)
    else:
        yield from _field_columns(field.annotation, names, path)


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
        for field in _data_fields(annotation):
            yield from _data_columns(field, names, path)
    elif get_origin(annotation) is tuple and arguments and Ellipsis not in arguments:
        for index, argument in enumerate(arguments):
            yield from _field_columns(argument, (*names, str(index)), (*path, index))
    else:
        name = ".".join(names)
        yield ExportColumn(name, path, name)


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
            # Only `\n` ends a line, so a bare `\r` inside a CSV field stays in its line.
            start = 0
            while (newline := pending.find(b"\n", start)) >= 0:
                yield pending[start : newline + 1]
                start = newline + 1

            pending = pending[start:]


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

    exports: ClassVar[frozenset[EntityType] | None] = None
    """Record kinds the format can write, `None` for every kind."""

    selects: ClassVar[bool] = True
    """Whether the format writes columns, which the exporter's `fields` chooses and renames."""

    def check(self, schema: ExportSchema) -> tuple[str, ...]:
        """Return the dotted paths of the data fields that files for `schema` leave out.

        Raises:
            ValueError: If the format cannot write files for `schema`.
        """
        return ()

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


class LineFormat(Format, abstract=True):
    """Format whose file is an optional header followed by one encoded line per record.

    Subclasses provide `header` and `encode`, and `key` when lines carry their record's key.
    """

    appendable: ClassVar[bool] = True

    resumable: ClassVar[bool] = True
    """Whether `key` reads a line's key, so a live exporter resumes after a file's last line."""

    def resumes(self, schema: ExportSchema) -> bool:
        """Return whether a live exporter can resume after the last line of a file for `schema`,
        which needs the line's key in the columns the exporter's `fields` keep."""
        return self.resumable and schema.keyed

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
                raise ExportFileError(f"'{path}' has another header")

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

    async def tail(self, path: Path, schema: ExportSchema) -> tuple[ExportKey | None, int]:
        """Return the last key in the file at `path` and the length of its complete records.

        A file longer than that length ends in a torn record.

        Raises:
            ExportFileError: If the file's header differs from the one `schema` gives.
        """
        last: ExportKey | None = None
        length = 0
        async for key, line in self.lines(path, schema):
            last = key
            length += len(line)

        header = len(self.header(schema))
        if last is not None or (await anyio.Path(path).stat()).st_size >= header:
            length += header

        return last, length


class CsvFormat(LineFormat):
    """Comma separated values, one column per schema column.

    Nested values are JSON text, an absent value is an empty cell, and a non-finite float is
    `nan`, `inf` or `-inf`.
    """

    extension: ClassVar[str] = ".csv"
    schema_bound: ClassVar[bool] = True

    header_row: bool = Field(default=False, alias="header")
    """Whether each file opens with a row of the column names."""

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
        return self.__line(schema.names) if self.header_row else b""

    @override
    def encode(self, schema: ExportSchema, record: ExportRecord) -> bytes:
        return self.__line(self.__cell(value) for value in schema.row(record))

    @override
    def key(self, line: bytes) -> ExportKey:
        timestamp, id = line.rstrip(b"\r\n").split(b",", 2)[:2]
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

    Records carry no key in the file, so a live exporter cannot tell where a file it finds
    at start ends.
    """

    extension: ClassVar[str] = ".bin"
    resumable: ClassVar[bool] = False
    selects: ClassVar[bool] = False
    exports: ClassVar[frozenset[EntityType] | None] = frozenset({EntityType.MESSAGE})

    @override
    def encode(self, schema: ExportSchema, record: ExportRecord) -> bytes:
        return cast("Message", record).data


class NetCDFFormat(Format):
    """NetCDF-4 file of one particle class, a variable per data field over a `time` dimension.

    `time` holds seconds since the epoch and `id` each particle's ID as 36 characters.
    `connection` indexes the names in `connection_name`, and is `-1` for no connection. The
    global attributes name the exporter, its component's `address`, and the `particle_type`.
    The whole file is rewritten on every write, so a period's rows sit in memory while it is.
    """

    extension: ClassVar[str] = ".nc"
    schema_bound: ClassVar[bool] = True
    exports: ClassVar[frozenset[EntityType] | None] = frozenset({EntityType.PARTICLE})

    attributes: Mapping[str, Mapping[str, str]] = Field(default_factory=dict)
    """Attributes of each data variable by name, beside the `units` a `Unit()` gives."""

    global_attributes: Mapping[str, str] = Field(default_factory=dict)
    """Attributes of the file, beside the ones it always carries."""

    def variables(self, schema: ExportSchema) -> tuple[NetCDFVariable, ...]:
        """Return the data variables of the files for `schema`, the exporter's `fields` choosing
        and renaming them. `time`, `id` and `connection` stay whatever `fields` names."""
        return _netcdf_selected(schema.particle, schema.selection)

    @override
    def check(self, schema: ExportSchema) -> tuple[str, ...]:
        """Return the fields the built-in layout leaves out, whatever `variables` returns."""
        _netcdf_selected(schema.particle, schema.selection)
        return _netcdf_layout(schema.particle)[1]

    def file_attributes(self, schema: ExportSchema) -> dict[str, str]:
        """Return the global attributes of the files for `schema`."""
        from ceres.particle import _get_cls_particle_type

        attributes: dict[str, str] = {}
        if schema.exporter is not None:
            attributes["exporter"] = schema.exporter
        if schema.address is not None:
            attributes["address"] = str(schema.address)
        if schema.particle is not None and (kind := _get_cls_particle_type(schema.particle)):
            attributes["particle_type"] = kind

        return {**attributes, **self.global_attributes}

    @override
    async def write(
        self,
        path: Path,
        schema: ExportSchema,
        records: AsyncIterable[ExportRecord],
    ) -> None:
        from ceres.__internal__.netcdf import write_table

        variables = self.variables(schema)
        table = await self.__collect(variables, records)
        await spawn(
            write_table, path, table, variables, self.attributes, self.file_attributes(schema)
        )

    @staticmethod
    async def __collect(
        variables: tuple[NetCDFVariable, ...], records: AsyncIterable[ExportRecord]
    ) -> NetCDFTable:
        from ceres.__internal__.netcdf import NetCDFRows

        rows = NetCDFRows(variables)
        async for record in records:
            rows.add(cast("Particle[Any]", record))

        table = rows.finish()
        if not table.sorted():
            raise ExportFileError("records arrived out of key order")

        return table


BUILTIN_FORMATS: dict[str, type[Format]] = {
    "csv": CsvFormat,
    "jsonl": JsonLinesFormat,
    "netcdf": NetCDFFormat,
    "raw": RawFormat,
}
"""The formats an exporter names with a bare string, such as `format: csv`."""


# Each live tick writes through the layout, so it is derived once per particle class, which
# bounds the cache by the classes a process defines.
@functools.cache
def _netcdf_layout(
    particle: type[Particle[Any]] | None,
) -> tuple[tuple[NetCDFVariable, ...], tuple[str, ...]]:
    from ceres.__internal__.netcdf import netcdf_variables

    return netcdf_variables(_data_fields(particle.Data) if particle is not None else ())


@functools.cache
def _netcdf_selected(
    particle: type[Particle[Any]] | None, selection: tuple[tuple[str, str], ...]
) -> tuple[NetCDFVariable, ...]:
    variables = _netcdf_layout(particle)[0]
    if not selection:
        return variables

    selected: list[NetCDFVariable] = []
    for alias, field in selection:
        if field in _RECORD_COLUMNS[EntityType.PARTICLE]:
            continue

        segments = tuple(field.split("."))
        matches = [variable for variable in variables if variable.path[: len(segments)] == segments]
        if not matches:
            raise ValueError(f"no data field `{field}` that netcdf can write")

        for variable in matches:
            name = "_".join((alias, *variable.path[len(segments) :]))
            if any(other.name == name for other in selected):
                raise ValueError(f"two fields export as variable `{name}`")

            selected.append(dataclasses.replace(variable, name=name))

    return tuple(selected)


def _fsync(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _create_temporary(final: Path) -> Path:
    descriptor, name = tempfile.mkstemp(dir=final.parent, prefix=f".{final.name}.", suffix=".tmp")
    try:
        # `mkstemp` creates the file 0600 and the rename keeps that mode, which would hide the
        # archive from every other user. A rewrite keeps the mode an operator gave the file.
        try:
            mode = final.stat().st_mode & 0o777
        except FileNotFoundError:
            mode = 0o666 & ~_UMASK

        os.chmod(name, mode)
    finally:
        os.close(descriptor)

    return Path(name)


def _commit(temporary: Path, final: Path) -> None:
    _fsync(temporary)
    os.replace(temporary, final)
    # The rename lives in the directory entry, so the directory needs its own sync.
    _fsync(final.parent)


@asynccontextmanager
async def atomic_write(target: Mount) -> AsyncIterator[Path]:
    """Yield a temporary sibling of `target` that replaces it when the block exits.

    Readers see the old file or the new one, never a partial write. The temporary file is
    removed when the block raises. Missing parent directories are created.

    Raises:
        PermissionError: If the mount is read-only.
    """
    await target.parent.aio().mkdir()
    final = target.path
    temporary = await spawn(_create_temporary, final)
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


class ExportRangeMode(StrEnum):
    """How a run aligns its requested range with the exporter's file boundaries."""

    EXPAND = "expand"
    """Widen the range to the whole files it touches."""

    EXACT = "exact"
    """Keep the requested range, so a file at either end may take part of its records."""

    SHRINK = "shrink"
    """Narrow the range to the whole files inside it, nothing when none fits."""


class ExportConflict(StrEnum):
    """What a run does with a file it would write that already exists."""

    ERROR = "error"
    """Refuse the run before it writes anything."""

    SKIP = "skip"
    """Leave the file as it is."""

    OVERWRITE = "overwrite"
    """Write the file from the database, unless that could lose records only the file holds."""

    PURGE = "purge"
    """Write the file from the database, and remove it when the database holds none of its
    records, losing any records only the file holds."""


@dataclass(frozen=True, slots=True)
class ExportSpan:
    """A range of time, either bound `None` for open."""

    after: datetime | None
    """Inclusive start, `None` for the start of time."""

    before: datetime | None
    """Exclusive end, `None` for the end of time."""


def effective_span(
    period: ExporterPeriod, mode: ExportRangeMode, after: datetime, before: datetime
) -> ExportSpan | None:
    """Return the range a run over `[after, before)` covers under `mode`, `None` for nothing.

    A `period: all` file covers all time, so `expand` covers all time and `shrink` nothing.
    """
    if period == ExporterPeriod.ALL:
        match mode:
            case ExportRangeMode.EXPAND:
                return ExportSpan(None, None)
            case ExportRangeMode.EXACT:
                return ExportSpan(after, before)
            case ExportRangeMode.SHRINK:
                return None

    first, last = period_start(period, after), period_start(period, before)
    match mode:
        case ExportRangeMode.EXPAND:
            end = last if last == before else period_shift(period, last, 1)
            return ExportSpan(first, end)
        case ExportRangeMode.EXACT:
            return ExportSpan(after, before)
        case ExportRangeMode.SHRINK:
            start = first if first == after else period_shift(period, first, 1)
            return ExportSpan(start, last) if start < last else None


def span_files(period: ExporterPeriod, span: ExportSpan) -> Iterator[tuple[ExportSpan, ExportSpan]]:
    """Yield each file's whole range and the part of it `span` selects, in time order.

    A `period: all` exporter has one file, whose whole range is open at both ends.
    """
    if period == ExporterPeriod.ALL or span.after is None or span.before is None:
        yield ExportSpan(None, None), span
        return

    for start, end in periods(period, span.after, span.before):
        assert start is not None and end is not None
        yield ExportSpan(start, end), ExportSpan(max(start, span.after), min(end, span.before))


_DEFAULT_PATHS: Final[Mapping[ExporterPeriod, str]] = {
    ExporterPeriod.HOUR: "{exporter}_{yyyy}{MM}{dd}T{HH}",
    ExporterPeriod.DAY: "{exporter}_{yyyy}{MM}{dd}",
    ExporterPeriod.MONTH: "{exporter}_{yyyy}{MM}",
    ExporterPeriod.ALL: "{exporter}",
}


@dataclass(frozen=True, slots=True)
class ExportPath:
    """An exporter's file name, checked to give each period its own file on a mount."""

    template: PathTemplate
    """File name of a period, its extension included, rendered at the period's UTC start."""

    period: ExporterPeriod
    """Time one file covers."""

    values: Mapping[str, str]
    """Values of `{exporter}`, and of `{connection}` when the filter pins one."""

    @classmethod
    def create(
        cls,
        source: str | None,
        period: ExporterPeriod,
        exporter: str,
        connection: str | None,
        extension: str,
    ) -> ExportPath:
        """Check the file name `source` and return the path it describes.

        Args:
            source: `PathTemplate` of the file name without its extension, with `{exporter}`.
                `None` takes the period's default, such as `{exporter}_{yyyy}{MM}{dd}`.
            period: Time one file covers.
            exporter: Exporter name `{exporter}` renders to.
            connection: Connection name `{connection}` renders to, `None` when the filter pins
                none.
            extension: Format extension the name ends in.

        Raises:
            ValueError: If the template is invalid, ends in a format extension, uses
                `{connection}` without a pinned connection, or reads the time under
                `period: all`.
        """
        source = _DEFAULT_PATHS[period] if source is None else source
        for known in sorted(
            {extension, *(format.extension for format in BUILTIN_FORMATS.values())}
        ):
            if source.lower().endswith(known):
                raise ValueError(
                    f"the format adds `{extension}`, so the path must not end in `{known}`"
                )

        template = PathTemplate(source + extension, atoms=("exporter",))
        if "connection" in template.atoms and connection is None:
            raise ValueError("`{connection}` needs a filter that pins one connection")

        if period == ExporterPeriod.ALL and template.dated:
            raise ValueError("a `period: all` path takes no time atoms")

        values = {"exporter": exporter}
        if connection is not None:
            values["connection"] = connection

        return cls(template, period, values)

    def file(self, mount: Mount, start: datetime | None) -> Mount:
        """Return the file for the period starting at `start` on `mount`, without creating its
        folder.

        A file of `period: all` sits at the mount's root, every other in the layout's folder.
        """
        if start is None:
            return mount / mount.render(self.template, _EPOCH, self.values)

        return mount.place(self.template, start, self.values)

    def render(self, mount: Mount, start: datetime | None) -> str:
        """Return the file path for the period starting at `start`, relative to `mount`."""
        return self.file(mount, start).relative.as_posix()

    def check(self, mount: Mount) -> None:
        """Check that the periods take files of their own in `mount`'s layout.

        Raises:
            ValueError: If the layout splits folders finer than a period, or two periods
                render one file.
        """
        if self.period == ExporterPeriod.ALL:
            return

        layout = mount.layout
        if layout is not None and layout.splits_finer_than(self.period.value):
            raise ValueError(f"layout '{layout}' splits finer than period '{self.period.value}'")

        seen: dict[str, datetime] = {}
        for start in self.__probes():
            rendered = self.render(mount, start)
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

    on_conflict: ExportConflict
    """What the run does with a file it would write that already exists."""

    range_mode: ExportRangeMode
    """How the run aligns the requested range with the exporter's files."""

    effective_after: DateTime | None
    """Inclusive start of the range the run covers, `None` for the start of time."""

    effective_before: DateTime | None
    """Exclusive end of the range the run covers, `None` for the end of time."""

    state: ExportRunState = ExportRunState.RUNNING
    """Where the run stands."""

    started: DateTime
    """When the run started."""

    ended: DateTime | None = None
    """When the run completed or failed, `None` while it runs."""

    count: int = 0
    """Records written so far."""

    files: list[str] = Field(default_factory=list)
    """Files written so far, relative to the exporter's mount."""

    kept: int = 0
    """Existing files the run left as they were."""

    removed: int = 0
    """Existing files the run removed, since the database holds none of their records."""

    periods: int
    """Files the run covers, 0 when the range mode leaves none."""

    periods_done: int = 0
    """Files finished so far, written, kept, removed or found empty."""

    exception: str | None = None
    """Why the run failed, `None` unless it failed."""

    def summary(self) -> ExportRunSummary:
        """Return the run without its file list, which grows with every period it writes."""
        return ExportRunSummary(
            id=self.id,
            after=self.after,
            before=self.before,
            on_conflict=self.on_conflict,
            range_mode=self.range_mode,
            effective_after=self.effective_after,
            effective_before=self.effective_before,
            state=self.state,
            started=self.started,
            ended=self.ended,
            count=self.count,
            file_count=len(self.files),
            kept=self.kept,
            removed=self.removed,
            periods=self.periods,
            periods_done=self.periods_done,
            exception=self.exception,
        )


class ExportRunSummary(DataObject):
    """An export run's state and counts, small enough to poll while it goes."""

    id: UUID
    """Run ID."""

    after: DateTime
    """Inclusive start of the requested range."""

    before: DateTime
    """Exclusive end of the requested range."""

    on_conflict: ExportConflict
    """What the run does with a file it would write that already exists."""

    range_mode: ExportRangeMode
    """How the run aligns the requested range with the exporter's files."""

    effective_after: DateTime | None
    """Inclusive start of the range the run covers, `None` for the start of time."""

    effective_before: DateTime | None
    """Exclusive end of the range the run covers, `None` for the end of time."""

    state: ExportRunState
    """Where the run stands."""

    started: DateTime
    """When the run started."""

    ended: DateTime | None
    """When the run completed or failed, `None` while it runs."""

    count: int
    """Records written so far."""

    file_count: int
    """Files written so far."""

    kept: int
    """Existing files the run left as they were."""

    removed: int
    """Existing files the run removed."""

    periods: int
    """Files the run covers."""

    periods_done: int
    """Files finished so far."""

    exception: str | None
    """Why the run failed, `None` unless it failed."""


class ExportFileAction(StrEnum):
    """What a run does with one file."""

    CREATE = "create"
    """Write a file where none exists."""

    OVERWRITE = "overwrite"
    """Write an existing file again from the database."""

    KEEP = "keep"
    """Leave an existing file as it is."""

    REMOVE = "remove"
    """Remove an existing file the database holds none of the records of."""

    NONE = "none"
    """Nothing, since no file exists and the database holds no records for one."""


class ExportKeepReason(StrEnum):
    """Why a run leaves an existing file as it is."""

    SKIP = "skip"
    """The run's conflict mode is `skip`."""

    HISTORY = "history"
    """The file starts before the oldest record the database holds, so it may hold older
    records the database no longer does."""

    PARTIAL = "partial"
    """The run's range covers only part of the file, so writing it would drop the rest."""

    EMPTY = "empty"
    """The database holds none of the file's records."""


class ExportFilePlan(DataObject):
    """What a run does with one file and why."""

    path: str
    """File path relative to the exporter's mount."""

    after: DateTime | None
    """Inclusive start of the time the file covers, `None` for the start of time."""

    before: DateTime | None
    """Exclusive end of the time the file covers, `None` for the end of time."""

    selected_after: DateTime | None
    """Inclusive start of the records the run selects for the file."""

    selected_before: DateTime | None
    """Exclusive end of the records the run selects for the file."""

    exists: bool
    """Whether the file exists."""

    action: ExportFileAction
    """What the run does with the file."""

    reason: ExportKeepReason | None = None
    """Why the run keeps an existing file, `None` unless it keeps one."""

    records: int
    """Stored records the run selects for the file, written unless it keeps the file."""


class ExportPlan(DataObject):
    """What a run of one exporter would do, file by file, without writing anything."""

    exporter: Name
    """Name of the exporter."""

    after: DateTime
    """Inclusive start of the requested range."""

    before: DateTime
    """Exclusive end of the requested range."""

    on_conflict: ExportConflict
    """What the run does with a file it would write that already exists."""

    range_mode: ExportRangeMode
    """How the run aligns the requested range with the exporter's files."""

    effective_after: DateTime | None
    """Inclusive start of the range the run covers, `None` for the start of time."""

    effective_before: DateTime | None
    """Exclusive end of the range the run covers, `None` for the end of time."""

    covered: bool
    """Whether the range mode leaves any range to cover."""

    files: list[ExportFilePlan]
    """Each file the run covers, in time order."""

    count: int
    """Records the run would write."""


class _Exporter:
    """A registered exporter's config beside the parts of it every run uses."""

    __slots__ = ("config", "format", "path", "schema")

    def __init__(self, config: ExporterConfig, address: Address) -> None:
        self.config = config
        self.format = config.create_format()
        self.schema = dataclasses.replace(config.create_schema(), address=address)
        self.path = config.create_path()


type _KeyRange = tuple[ExportKey, ExportKey]
"""The lowest and highest key of some records, both inclusive."""


class _Live:
    """A live exporter's place in its stream, kept in memory only.

    Notified keys wait as one range per period so a late record never widens the query of
    another period. The cursor starts at the start time of the check a live exporter runs
    when it starts, since that check makes every file complete through then and a record
    flushed afterward with an older key lowers `written_through` through `pending`. A record
    too late to append stays in the database alone and holds `written_through` through `late`
    until a run writes its period's file.
    """

    __slots__ = ("cursor", "last", "late", "owned", "pending", "task", "wake", "working")

    def __init__(self) -> None:
        self.wake = AsyncEvent()
        self.task: Task[None] | None = None
        # Ranges notified and not yet written, and those the current wake is writing.
        self.pending: dict[datetime, _KeyRange] = {}
        self.working: dict[datetime, _KeyRange] = {}
        # The last key of each period written since the last wake, `None` for an empty file.
        # A period missing here reads its last key from its file.
        self.last: dict[datetime, ExportKey | None] = {}
        # The oldest late record of each period, bounded by the periods holding one, since a
        # run writing a period's file drops its entry.
        self.late: dict[datetime, datetime] = {}
        # Periods whose whole file this exporter wrote from the database, so a whole-file
        # format may write them again. Kept like `last`, for the periods one interval touches.
        self.owned: set[datetime] = set()
        self.cursor: datetime | None = None

    def notify(self, period: ExporterPeriod, keys: Iterable[ExportKey]) -> None:
        """Add the keys a flush wrote to the pending range of each period holding one."""
        for key in keys:
            start = period_start(period, key[0])
            found = self.pending.get(start)
            self.pending[start] = (
                (key, key) if found is None else (min(found[0], key), max(found[1], key))
            )

        self.wake.set()

    def restore(self) -> None:
        """Return the ranges a failed wake was writing to `pending`."""
        for start, (first, last) in self.working.items():
            found = self.pending.get(start)
            self.pending[start] = (
                (first, last) if found is None else (min(found[0], first), max(found[1], last))
            )

        self.working = {}

    @property
    def written_through(self) -> datetime:
        """The time before which every stored record the exporter selects is in its files."""
        if self.cursor is None:
            return datetime.min.replace(tzinfo=UTC)

        return min(
            [self.cursor]
            + [first[0] for first, _ in self.pending.values()]
            + [first[0] for first, _ in self.working.values()]
            + list(self.late.values())
        )


@dataclass(frozen=True, slots=True)
class _Muted:
    # A range of one address's records that live export leaves to a playback.
    kind: EntityType
    address: Address
    after: datetime
    before: datetime


def _before_history(whole: ExportSpan, history: datetime | None) -> bool:
    # A file covering all time starts before any record, and a database holding no record
    # leaves nothing to compare.
    if whole.after is None:
        return True

    return history is not None and whole.after < history


def decide(
    on_conflict: ExportConflict,
    path: str,
    *,
    exists: bool,
    records: bool,
    partial: bool,
    before_history: bool,
) -> tuple[ExportFileAction, ExportKeepReason | None]:
    """Return what a run does with one file and why it keeps the file when it does.

    Args:
        on_conflict: The run's conflict mode.
        path: The file's path relative to its mount, which an error names.
        exists: Whether the file exists.
        records: Whether the database holds records the run selects for the file.
        partial: Whether the run selects only part of the file's time.
        before_history: Whether the file starts before the oldest record the database holds.

    Raises:
        ExportConflictError: If the file exists and `on_conflict` is `error`.
    """
    if not exists:
        return (ExportFileAction.CREATE if records else ExportFileAction.NONE), None

    match on_conflict:
        case ExportConflict.ERROR:
            raise ExportConflictError([path])
        case ExportConflict.SKIP:
            return ExportFileAction.KEEP, ExportKeepReason.SKIP
        case ExportConflict.PURGE:
            return (ExportFileAction.OVERWRITE if records else ExportFileAction.REMOVE), None
        case ExportConflict.OVERWRITE:
            if not records:
                return ExportFileAction.KEEP, ExportKeepReason.EMPTY
            if partial:
                return ExportFileAction.KEEP, ExportKeepReason.PARTIAL
            if before_history:
                return ExportFileAction.KEEP, ExportKeepReason.HISTORY

            return ExportFileAction.OVERWRITE, None


def _exporter_scope(records: BaseDatabaseManager) -> Callable[[Address], bool]:
    """Return whether a record at an address can match a query of `records`.

    A query reads the same defaults (`ceres/__internal__/entity.py` `_get_filter_defaults`),
    and the exporter's own filter only narrows them since `__query` joins it with `&`.
    """
    defaults = records.__get_filter_defaults__()
    selector: AddressSelector | None = defaults.get("address")
    root: Address | None = defaults.get("root")
    if selector is None:
        return lambda _: True

    return lambda address: selector.matches(address, root)


class ExporterManager(BaseComponentManager):
    """Component-level manager that runs each registered exporter's re-runs and schedule.

    One lock per exporter serializes every write to that exporter's files.
    """

    __slots__ = (
        "__completed",
        "__scheduler",
        "__exporters",
        "__live",
        "__locks",
        "__muted",
        "__pending",
        "__runs",
        "__scope",
        "__tasks",
    )

    def __init__(self, source: ComponentSource, /) -> None:
        super().__init__(source)
        self.__scheduler = self.__create_scheduler()
        self.__exporters: dict[str, _Exporter] = {}
        # Keyed by every name ever registered, so a run of a replaced config and a run of its
        # successor share one lock and one bound.
        self.__locks: dict[str, Lock] = {}
        # One entry per playback in flight, which the playback manager runs one at a time.
        self.__muted: list[_Muted] = []
        self.__pending: dict[str, int] = {}
        # The latest `before` of a completed run, by exporter, kept as long as the lock.
        self.__completed: dict[str, datetime] = {}
        self.__live: dict[str, _Live] = {}
        self.__runs: deque[ExportRunRecord] = deque(maxlen=_RUN_RING_SIZE)
        self.__scope: Callable[[Address], bool] | None = None
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
        self.__scope = _exporter_scope(self)
        unsubscribe = self.__system__.__subscribe_flushes__(self.__flushed)
        try:
            self.__sync_schedules()
            self.__scheduler.start()
            self.__sync_live()
            await sleep(...)
        finally:
            unsubscribe()
            self.__scope = None
            if self.__scheduler.running:
                self.__scheduler.shutdown(wait=False)

            self.__scheduler = self.__create_scheduler()
            live, self.__live = self.__live, {}
            await cancel(
                *self.__tasks.values(), *(state.task for state in live.values() if state.task)
            )

    def add(self, exporter: ExporterConfig) -> None:
        """Register an exporter, replacing any registered under the same name."""
        self.remove(exporter.name)
        registered = _Exporter(exporter, self.__system__.address)
        registered.path.check(self.__mount(exporter))
        omitted = registered.format.check(registered.schema)
        if omitted:
            self.__system__.log.warning(
                f"Exporter '{exporter.name}' leaves out the fields its format cannot store: "
                + ", ".join(f"'{path}'" for path in omitted)
            )

        self.__exporters[exporter.name] = registered
        self.__locks.setdefault(exporter.name, Lock())
        self.__sync_schedules()
        self.__sync_live()

    def get(self, name: str) -> ExporterConfig | None:
        """Return the exporter registered under `name`, or `None`."""
        registered = self.__exporters.get(name)
        return registered.config if registered is not None else None

    def get_current_file(self, name: str) -> str | None:
        """Return the file the current period writes, relative to the exporter's mount.

        Returns:
            The path, or `None` when no exporter is registered under `name` or its mount is
            missing.
        """
        registered = self.__exporters.get(name)
        if registered is None or self.__system__.get_mount(registered.config.mount) is None:
            return None

        period = registered.config.period
        start = _bounds(period, period_start(period, datetime.now(UTC)))[0]
        return registered.path.render(self.__mount(registered.config), start)

    def get_all(self) -> list[ExporterConfig]:
        """Return every registered exporter."""
        return [registered.config for registered in self.__exporters.values()]

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

        live = self.__live.pop(name, None)
        if live is not None and live.task is not None:
            live.task.cancel()

        registered = self.__exporters.pop(name, None)
        return registered.config if registered is not None else None

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
        on_conflict: ExportConflict = ExportConflict.OVERWRITE,
        range_mode: ExportRangeMode = ExportRangeMode.EXPAND,
    ) -> ExportRunRecord:
        """Start a run writing the files that cover `[after, before)` and return its record.

        `range_mode` aligns the range with the exporter's files first. Each file the aligned
        range covers is written from the database alone, the records it selects and nothing
        else, and `on_conflict` decides what happens to a file that already exists. A run
        removes no database record.

        One run of an exporter writes at a time and one more waits for it.

        Args:
            name: Name of the exporter to run.
            after: Inclusive start of the range.
            before: Exclusive end of the range, defaulting to now.
            on_conflict: What to do with a file the run would write that already exists.
            range_mode: How to align the range with the exporter's files.

        Raises:
            KeyError: If no exporter is registered under `name`.
            ValueError: If `after` does not precede `before`.
            ExportConflictError: If `on_conflict` is `error` and files the run would write
                already exist. A file appearing after the check still fails the run.
            AlreadyExistsError: If one run of the exporter already waits for another.
        """
        registered, after, before = self.__resolve(name, after, before)
        if self.__pending.get(name, 0) >= _PENDING_RUNS:
            raise AlreadyExistsError(field="exporter", value=name)

        span = effective_span(registered.config.period, range_mode, after, before)
        files = [] if span is None else list(span_files(registered.config.period, span))
        if on_conflict == ExportConflict.ERROR:
            self.check_conflicts(name, after, before, range_mode)

        run = ExportRunRecord(
            id=uuid4(),
            exporter=name,
            after=after,
            before=before,
            on_conflict=on_conflict,
            range_mode=range_mode,
            effective_after=span.after if span is not None else None,
            effective_before=span.before if span is not None else None,
            started=datetime.now(UTC),
            periods=len(files),
        )
        self.__runs.append(run)
        self.__pending[name] = self.__pending.get(name, 0) + 1
        task = create_task(self.__export(registered, run, files))
        self.__tasks[run.id] = task

        def finish(_: Task[None]) -> None:
            self.__tasks.pop(run.id, None)
            self.__pending[name] -= 1

        task.add_done_callback(finish)
        return run

    async def run(
        self,
        name: str,
        after: datetime,
        before: datetime | None = None,
        *,
        on_conflict: ExportConflict = ExportConflict.OVERWRITE,
        range_mode: ExportRangeMode = ExportRangeMode.EXPAND,
    ) -> ExportRunRecord:
        """Run like `start` and return the run's record once it completes or fails."""
        run = self.start(name, after, before, on_conflict=on_conflict, range_mode=range_mode)
        task = self.__tasks.get(run.id)
        if task is not None:
            await task

        return next((current for current in self.__runs if current.id == run.id), run)

    async def plan(
        self,
        name: str,
        after: datetime,
        before: datetime | None = None,
        *,
        on_conflict: ExportConflict = ExportConflict.OVERWRITE,
        range_mode: ExportRangeMode = ExportRangeMode.EXPAND,
        adjust: Callable[[ExportSpan, int], Awaitable[int]] | None = None,
    ) -> ExportPlan:
        """Return what a run like `start` would do with each file, writing nothing.

        The plan reads the database as it stands, so records a flush stores before a later run
        can change what that run does.

        Args:
            name: Name of the exporter.
            after: Inclusive start of the range.
            before: Exclusive end of the range, defaulting to now.
            on_conflict: What the run would do with a file that already exists.
            range_mode: How the run would align the range with the exporter's files.
            adjust: Returns the records a file would hold from its selected range and the
                records the database holds there now, for a caller that would change the
                database first.

        Raises:
            KeyError: If no exporter is registered under `name`.
            ValueError: If `after` does not precede `before`.
            ExportConflictError: If `on_conflict` is `error` and files the run would write
                already exist.
        """
        registered, after, before = self.__resolve(name, after, before)
        exporter = registered.config
        span = effective_span(exporter.period, range_mode, after, before)
        mount = self.__mount(exporter)
        history = await self.__history(exporter)
        files: list[ExportFilePlan] = []
        existing: list[str] = []
        for whole, selected in [] if span is None else span_files(exporter.period, span):
            target = registered.path.file(mount, whole.after)
            relative = target.relative.as_posix()
            exists = await anyio.Path(target.path).exists()
            count = await self.__query(exporter, selected.after, selected.before).count()
            if adjust is not None:
                count = await adjust(selected, count)
            if exists and on_conflict == ExportConflict.ERROR:
                existing.append(relative)
                continue

            action, reason = decide(
                on_conflict,
                relative,
                exists=exists,
                records=count > 0,
                partial=whole != selected,
                before_history=_before_history(whole, history),
            )
            if action != ExportFileAction.NONE:
                files.append(
                    ExportFilePlan(
                        path=relative,
                        after=whole.after,
                        before=whole.before,
                        selected_after=selected.after,
                        selected_before=selected.before,
                        exists=exists,
                        action=action,
                        reason=reason,
                        records=count,
                    )
                )

        if existing:
            raise ExportConflictError(existing)

        written = (ExportFileAction.CREATE, ExportFileAction.OVERWRITE)
        return ExportPlan(
            exporter=name,
            after=after,
            before=before,
            on_conflict=on_conflict,
            range_mode=range_mode,
            effective_after=span.after if span is not None else None,
            effective_before=span.before if span is not None else None,
            covered=span is not None,
            files=files,
            count=sum(file.records for file in files if file.action in written),
        )

    async def count_records(
        self, name: str, after: datetime | None, before: datetime | None, filter: Any = None
    ) -> int:
        """Return the stored records the named exporter selects in `[after, before)`.

        Args:
            name: Name of the exporter.
            after: Inclusive start, `None` for the start of time.
            before: Exclusive end, `None` for the end of time.
            filter: A filter of the exporter's kind that narrows the records further.

        Raises:
            KeyError: If no exporter is registered under `name`.
        """
        registered = self.__exporters.get(name)
        if registered is None:
            raise KeyError(name)

        return await self.__query(registered.config, after, before, extra=filter).count()

    def selects(self, name: str, record: ExportRecord) -> bool:
        """Return whether the named exporter writes `record` once it is stored.

        Raises:
            KeyError: If no exporter is registered under `name`.
        """
        from ceres.particle import _get_cls_particle_type

        registered = self.__exporters.get(name)
        if registered is None:
            raise KeyError(name)

        exporter = registered.config
        particle = exporter.particle_class()
        if particle is not None and getattr(record, "type", None) != _get_cls_particle_type(
            particle
        ):
            return False

        filter: Any = exporter.filter
        return filter is None or filter.matches(record)

    def check_conflicts(
        self,
        name: str,
        after: datetime,
        before: datetime | None = None,
        range_mode: ExportRangeMode = ExportRangeMode.EXPAND,
    ) -> None:
        """Check that no file a run over `[after, before)` would write already exists.

        Raises:
            KeyError: If no exporter is registered under `name`.
            ValueError: If `after` does not precede `before`.
            ExportConflictError: If any file already exists, naming each one.
        """
        registered, after, before = self.__resolve(name, after, before)
        span = self.span(name, after, before, range_mode)
        if span is None:
            return

        mount = self.__mount(registered.config)
        existing = [
            target.relative.as_posix()
            for whole, _ in span_files(registered.config.period, span)
            if (target := registered.path.file(mount, whole.after)).path.exists()
        ]
        if existing:
            raise ExportConflictError(existing)

    def span(
        self, name: str, after: datetime, before: datetime, range_mode: ExportRangeMode
    ) -> ExportSpan | None:
        """Return the range a run of the named exporter covers, `None` for nothing.

        Raises:
            KeyError: If no exporter is registered under `name`.
        """
        registered = self.__exporters.get(name)
        if registered is None:
            raise KeyError(name)

        return effective_span(registered.config.period, range_mode, after, before)

    def __resolve(
        self, name: str, after: datetime, before: datetime | None
    ) -> tuple[_Exporter, datetime, datetime]:
        registered = self.__exporters.get(name)
        if registered is None:
            raise KeyError(name)

        after = after.astimezone(UTC)
        before = (before or datetime.now(UTC)).astimezone(UTC)
        if after >= before:
            raise ValueError("`after` must precede `before`")

        return registered, after, before

    async def __history(self, exporter: ExporterConfig) -> datetime | None:
        # The oldest record the exporter selects, before which the database may have lost
        # records an existing file still holds.
        oldest = await self.__query(exporter, None, None).first()
        return oldest.timestamp if oldest is not None else None

    def __sync_schedules(self) -> None:
        from ceres.job import _get_trigger_adapter_class

        TriggerAdapter = _get_trigger_adapter_class()
        for name, registered in self.__exporters.items():
            schedule = registered.config.schedule
            if schedule is None or self.__scheduler.get_job(name) is not None:
                continue

            self.__scheduler.add_job(
                self.__scheduled,
                args=[name],
                trigger=TriggerAdapter(schedule.create_trigger()),
                name=name,
                id=name,
            )

    def __sync_live(self) -> None:
        if self.__scope is None:
            return

        for name, registered in self.__exporters.items():
            if registered.config.is_live and name not in self.__live:
                live = self.__live[name] = _Live()
                live.task = create_task(self.__live_loop(registered, live))

    def __flushed(self, summary: FlushSummary) -> None:
        # Runs on the writer's flush path, so it only records what to write.
        scope = self.__scope
        if scope is None or not self.__live:
            return

        for (kind, address), keys in summary.items():
            targets = [
                (self.__exporters[name].config, live)
                for name, live in self.__live.items()
                if self.__exporters[name].config.exports == kind
            ]
            if targets and scope(address):
                keys = [key for key in keys if not self.__is_muted(kind, address, key)]
                for exporter, live in targets:
                    live.notify(exporter.period, keys)

    def __is_muted(self, kind: EntityType, address: Address, key: ExportKey) -> bool:
        return any(
            muted.kind == kind and muted.address == address and muted.after <= key[0] < muted.before
            for muted in self.__muted
        )

    @contextmanager
    def mute(
        self, kind: EntityType, address: Address, after: datetime, before: datetime
    ) -> Iterator[None]:
        """Keep live export from writing records of `kind` stored at `address` within a range.

        A playback mutes the range it rebuilds, so only its own export run, under the modes it
        names, changes the files.
        """
        muted = _Muted(kind, address, after, before)
        self.__muted.append(muted)
        try:
            yield
        finally:
            self.__muted.remove(muted)

    def get_written_through(self, kind: EntityType) -> tuple[str, datetime] | None:
        """Return the exporter of `kind` that has written the least, and how far it has written.

        A live exporter has written every stored record it selects before the returned time,
        and any other exporter every record before the end of its latest completed run. An
        exporter that has done neither returns the start of time.

        Returns:
            The exporter's name and time, or `None` when no exporter exports `kind`.
        """
        start = datetime.min.replace(tzinfo=UTC)
        found: tuple[str, datetime] | None = None
        for name, registered in self.__exporters.items():
            if registered.config.exports != kind:
                continue

            live = self.__live.get(name)
            if live is not None:
                through = live.written_through
            elif registered.config.is_live:
                through = start
            else:
                through = self.__completed.get(name, start)

            if found is None or through < found[1]:
                found = (name, through)

        return found

    async def __live_loop(self, registered: _Exporter, live: _Live) -> None:
        exporter = registered.config
        interval = exporter.interval
        checked = False
        failing = False
        while True:
            if checked and not live.pending:
                await live.wake.wait()

            live.wake.clear()
            try:
                if not checked:
                    await self.__check_start(registered, live)
                    checked = True

                if live.pending:
                    await self.__write_live(registered, live)

                failing = False
            except CancelledError:
                live.restore()
                raise
            except Exception as exception:
                live.restore()
                if not failing:
                    self.__system__.log.warning(
                        f"Exporter '{exporter.name}' failed to write live and retries every "
                        f"interval: {exception}"
                    )

                failing = True

            await sleep(interval.total_seconds())

    async def __check_start(self, registered: _Exporter, live: _Live) -> None:
        # Writes what the exporter missed while stopped before live writes resume. A missing
        # file is written whole, and a resumable file takes the records after its last line.
        started = datetime.now(UTC)
        exporter, format = registered.config, registered.format
        current = period_start(exporter.period, started)
        first = current
        if exporter.period != ExporterPeriod.ALL:
            first = period_shift(exporter.period, current, -1)
            newest = await self.__query(exporter, None, None, order=_REVERSE_ORDER).first()
            if newest is not None:
                first = min(first, period_start(exporter.period, newest.timestamp))

        starts = [
            start for start, _ in periods(exporter.period, first, started + TICK) if start
        ] or [current]
        if len(starts) > _START_CHECKS:
            self.__system__.log.warning(
                f"Exporter '{exporter.name}' checks only its newest {_START_CHECKS} periods "
                f"at start, so a run must write any records before "
                f"{starts[-_START_CHECKS].isoformat()}"
            )
            starts = starts[-_START_CHECKS:]

        mount = self.__mount(exporter)
        history = await self.__history(exporter)
        async with self.__locks[exporter.name]:
            for start in starts:
                bounds = _bounds(exporter.period, start)
                target = registered.path.file(mount, bounds[0])
                if not await anyio.Path(target.path).exists():
                    live.owned.add(start)
                    await self.__write_whole(registered, target, *bounds, started)
                elif isinstance(format, LineFormat) and format.resumes(registered.schema):
                    await self.__resume(registered, live, target, start, started)
                elif not format.appendable and not _before_history(ExportSpan(*bounds), history):
                    await self.__write_whole(registered, target, *bounds, started)
                elif await self.__query(exporter, bounds[0], started).first() is not None:
                    self.__warn_late(registered, live, start, None)

        live.cursor = started

    async def __write_whole(
        self,
        registered: _Exporter,
        target: Mount,
        start: datetime | None,
        end: datetime | None,
        through: datetime | None = None,
    ) -> None:
        # Writes a period's file from the records stored before `through`, every stored record
        # of the period when `through` is `None`.
        exporter = registered.config
        if through is not None:
            end = through if end is None else min(end, through)

        async with self.__query(exporter, start, end) as results:
            stream = _Counted(results)
            head = await anext(stream, None)
            if head is None:
                return

            async with atomic_write(target) as temporary:
                await registered.format.write(temporary, registered.schema, _prepend(head, stream))

    async def __resume(
        self,
        registered: _Exporter,
        live: _Live,
        target: Mount,
        start: datetime,
        through: datetime,
    ) -> None:
        exporter = registered.config
        try:
            last = await self.__last_key(registered, target.path)
        except ExportFileError as exception:
            self.__system__.log.warning(
                f"Exporter '{exporter.name}' cannot read where '{target.relative.as_posix()}' "
                f"ends, so it leaves the file as it is: {exception}"
            )
            return

        live.last[start] = last
        bounds = _bounds(exporter.period, start)
        after = bounds[0] if last is None else last[0]
        end = through if bounds[1] is None else min(bounds[1], through)
        async with self.__query(exporter, after, end) as results:
            stream = _Counted(_after(results, last))
            head = await anext(stream, None)
            if head is None:
                return

            await registered.format.append(target.path, registered.schema, _prepend(head, stream))

        if stream.last is not None:
            live.last[start] = _record_key(stream.last)

    def __warn_late(
        self, registered: _Exporter, live: _Live, start: datetime, oldest: datetime | None
    ) -> None:
        # A record the exporter cannot add to its file stays in the database alone, and holds
        # `written_through` so a pruner keeps it until a run writes the file.
        exporter = registered.config
        after = _bounds(exporter.period, start)[0]
        held = oldest or after or datetime.min.replace(tzinfo=UTC)
        previous = live.late.get(start)
        live.late[start] = held if previous is None else min(previous, held)
        if previous is not None:
            return

        relative = registered.path.render(self.__mount(exporter), after)
        range = f" --after {after.isoformat()}" if after is not None else ""
        self.__system__.log.warning(
            f"Exporter '{exporter.name}' cannot add records to '{relative}' without rewriting "
            f"it, so they stay in the database until `ceres export {self.__system__.address} "
            f"{exporter.name}{range}` writes the file"
        )

    async def __write_live(self, registered: _Exporter, live: _Live) -> None:
        exporter = registered.config
        mount = self.__mount(exporter)
        live.working, live.pending = live.pending, {}
        written = sorted(live.working)
        async with self.__locks[exporter.name]:
            for start in written:
                first, last = live.working[start]
                await self.__write_period_live(registered, live, mount, start, first, last)
                del live.working[start]
                live.cursor = last[0] if live.cursor is None else max(live.cursor, last[0])

        # Only the periods this wake wrote and the current one keep their last key, which
        # bounds the map by the periods one interval touches.
        kept = {*written, period_start(exporter.period, datetime.now(UTC))}
        live.last = {start: key for start, key in live.last.items() if start in kept}
        live.owned &= kept

    async def __write_period_live(
        self,
        registered: _Exporter,
        live: _Live,
        mount: Mount,
        start: datetime,
        first: ExportKey,
        last: ExportKey,
    ) -> None:
        exporter, format, schema = registered.config, registered.format, registered.schema
        bounds = _bounds(exporter.period, start)
        target = registered.path.file(mount, bounds[0])
        final = target.path
        if not format.appendable:
            # A whole-file format writes the period again, which loses nothing only while the
            # database holds every record the file does: the file was missing when this
            # exporter first wrote it, or the database's history reaches back past its start.
            history = await self.__history(exporter)
            missing = not await anyio.Path(final).exists()
            if missing or start in live.owned or not _before_history(ExportSpan(*bounds), history):
                live.owned.add(start)
                # The whole period, since a file already holding newer records than this wake's
                # would otherwise lose them.
                await self.__write_whole(registered, target, *bounds)
            else:
                self.__warn_late(registered, live, start, first[0])

            return

        # The upper bound keeps out a record committed after this wake took its keys, whose
        # own notification would otherwise read as late.
        async with self.__query(exporter, first[0], last[0] + TICK) as results:
            stream = _Counted(_within(results, first, last))
            head = await anext(stream, None)
            if head is None:
                return

            resumable = isinstance(format, LineFormat) and format.resumes(schema)
            previous = None
            if resumable:
                previous = (
                    live.last[start]
                    if start in live.last
                    else await self.__last_key(registered, final)
                )

            if previous is not None and _record_key(head) <= previous:
                # Records at or before the file's last line would land out of order. The newer
                # ones of this wake still append after it.
                self.__warn_late(registered, live, start, head.timestamp)
                stream = _Counted(_after(_prepend(head, stream), previous))
                head = await anext(stream, None)
                if head is None:
                    return

            await target.parent.aio().mkdir()
            await format.append(final, schema, _prepend(head, stream))

        if resumable and stream.last is not None:
            newest = _record_key(stream.last)
            live.last[start] = newest if previous is None else max(previous, newest)

    async def __last_key(self, registered: _Exporter, final: Path) -> ExportKey | None:
        # Called under the exporter's lock before an append, which would extend a torn record.
        format = registered.format
        if not isinstance(format, LineFormat) or not await anyio.Path(final).exists():
            return None

        last, length = await format.tail(final, registered.schema)
        if (await anyio.Path(final).stat()).st_size > length:
            await spawn(os.truncate, final, length)

        return last

    def __forget(self, name: str, start: datetime | None) -> None:
        # A run wrote the period's file, so its last key comes from the file again and any
        # late record of the period is in it.
        live = self.__live.get(name)
        if live is not None:
            key = start or datetime.min.replace(tzinfo=UTC)
            live.last.pop(key, None)
            live.late.pop(key, None)

    async def __scheduled(self, name: str) -> None:
        exporter = self.get(name)
        if exporter is None:
            return

        now = datetime.now(UTC)
        lookback = exporter.lookback or 0
        after = period_shift(exporter.period, period_start(exporter.period, now), -lookback)
        try:
            self.start(name, after, now)
        except AlreadyExistsError:
            # The next scheduled run's lookback covers the periods this one skips.
            self.__system__.log.warning(
                f"Exporter '{name}' skipped a scheduled run behind two pending runs"
            )

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
        self,
        exporter: ExporterConfig,
        start: datetime | None,
        end: datetime | None,
        order: list[str] = _ORDER,
        extra: Any = None,
    ) -> Any:
        # Range keywords would override the user filter's own bounds, so the range is a
        # filter of its own, joined with `&`.
        Filter: Any = exporter.filter_class()
        filter: Any = Filter(after=start, before=end, order=order)
        for narrower in (exporter.filter, extra):
            if narrower is not None:
                filter = filter & narrower
        particle = exporter.particle_class()
        if particle is not None:
            return self.__records(exporter).where(filter, cls=particle)

        return self.__records(exporter).where(filter)

    def __mount(self, exporter: ExporterConfig) -> Mount:
        mount = self.__system__.get_mount(exporter.mount)
        if mount is None:
            raise ValueError(f"component has no mount '{exporter.mount}'")

        # A period starts at a UTC boundary, so its file says which period it holds only in UTC.
        return Mount(mount, zone="utc")

    async def __export(
        self,
        registered: _Exporter,
        run: ExportRunRecord,
        files: list[tuple[ExportSpan, ExportSpan]],
    ) -> None:
        exporter, path = registered.config, registered.path
        events = self.__system__.events
        events.emit(
            ExportRunStartedEvent,
            exporter=run.exporter,
            run=run.id,
            after=run.after,
            before=run.before,
            on_conflict=run.on_conflict,
            range_mode=run.range_mode,
        )
        # A file left as it was may lack stored records, so the run then vouches for nothing.
        complete = True
        try:
            mount = self.__mount(exporter)
            lock = self.__locks.setdefault(exporter.name, Lock())
            async with lock:
                history = await self.__history(exporter)
                for whole, selected in files:
                    target = path.file(mount, whole.after)
                    relative = target.relative.as_posix()
                    action, count = await self.__export_file(
                        registered, run.on_conflict, target, whole, selected, history
                    )
                    if action != ExportFileAction.KEEP:
                        self.__forget(exporter.name, whole.after)

                    match action:
                        case ExportFileAction.CREATE | ExportFileAction.OVERWRITE:
                            run = self.__update(
                                run,
                                count=run.count + count,
                                files=[*run.files, relative],
                                periods_done=run.periods_done + 1,
                            )
                            events.emit(
                                ExportRunProgressEvent,
                                exporter=run.exporter,
                                run=run.id,
                                period=whole.after,
                                count=count,
                                path=relative,
                                periods=run.periods,
                                periods_done=run.periods_done,
                            )
                        case ExportFileAction.KEEP:
                            complete = complete and count == 0
                            run = self.__update(
                                run, kept=run.kept + 1, periods_done=run.periods_done + 1
                            )
                        case ExportFileAction.REMOVE:
                            run = self.__update(
                                run, removed=run.removed + 1, periods_done=run.periods_done + 1
                            )
                        case ExportFileAction.NONE:
                            # An empty period emits nothing, since a year of hours would log
                            # 8760 events, but it still counts toward the run's progress.
                            run = self.__update(run, periods_done=run.periods_done + 1)
        except CancelledError:
            self.__fail(run, RuntimeError("component stopped"))
            raise
        except Exception as exception:
            self.__fail(run, exception)
            return

        run = self.__update(run, state=ExportRunState.COMPLETED, ended=datetime.now(UTC))
        if complete and run.effective_before is not None and files:
            completed = self.__completed.get(run.exporter)
            through = min(run.effective_before, run.ended or run.effective_before)
            self.__completed[run.exporter] = (
                through if completed is None else max(completed, through)
            )

        events.emit(
            ExportRunCompletedEvent,
            exporter=run.exporter,
            run=run.id,
            count=run.count,
            files=run.files,
            kept=run.kept,
            removed=run.removed,
            after=run.after,
            before=run.before,
            periods=run.periods,
            periods_done=run.periods_done,
        )
        shown = ", ".join(run.files[:_SHOWN_FILES]) + (
            f" and {len(run.files) - _SHOWN_FILES} more" if len(run.files) > _SHOWN_FILES else ""
        )
        others = [
            f"kept {run.kept} existing files" if run.kept else "",
            f"removed {run.removed} files" if run.removed else "",
        ]
        self.__system__.log.info(
            f"Exporter '{run.exporter}' wrote {run.count} records over "
            f"[{run.after.isoformat()}, {run.before.isoformat()}) to {len(run.files)} files"
            + (f": {shown}" if shown else "")
            + "".join(f", {other}" for other in others if other)
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

    async def __export_file(
        self,
        registered: _Exporter,
        on_conflict: ExportConflict,
        target: Mount,
        whole: ExportSpan,
        selected: ExportSpan,
        history: datetime | None,
    ) -> tuple[ExportFileAction, int]:
        # Returns what the run did with the file and the records it wrote, or for a kept
        # file the records it left out.
        exporter = registered.config
        final = anyio.Path(target.path)
        async with self.__query(exporter, selected.after, selected.before) as results:
            stream = _Counted(results)
            first = await anext(stream, None)
            action, _ = decide(
                on_conflict,
                target.relative.as_posix(),
                exists=await final.exists(),
                records=first is not None,
                partial=whole != selected,
                before_history=_before_history(whole, history),
            )
            match action:
                case ExportFileAction.CREATE | ExportFileAction.OVERWRITE:
                    assert first is not None
                    async with atomic_write(target) as temporary:
                        await registered.format.write(
                            temporary, registered.schema, _prepend(first, stream)
                        )

                    return action, stream.count
                case ExportFileAction.REMOVE:
                    await final.unlink(missing_ok=True)
                    return action, 0
                case ExportFileAction.KEEP | ExportFileAction.NONE:
                    return action, 0 if first is None else 1


class _Counted[T]:
    __slots__ = ("__iterator", "count", "last")

    def __init__(self, iterable: AsyncIterable[T]) -> None:
        self.__iterator = aiter(iterable)
        self.count = 0
        self.last: T | None = None

    def __aiter__(self) -> _Counted[T]:
        return self

    async def __anext__(self) -> T:
        item = await anext(self.__iterator)
        self.count += 1
        self.last = item
        return item


async def _within(
    records: AsyncIterable[ExportRecord], first: ExportKey, last: ExportKey
) -> AsyncIterator[ExportRecord]:
    # The query bounds timestamps only, so records sharing a bound's timestamp need its ID.
    async for record in records:
        if first <= _record_key(record) <= last:
            yield record


async def _after(
    records: AsyncIterable[ExportRecord], last: ExportKey | None
) -> AsyncIterator[ExportRecord]:
    async for record in records:
        if last is None or _record_key(record) > last:
            yield record


def _bounds(period: ExporterPeriod, start: datetime) -> tuple[datetime | None, datetime | None]:
    # A run names the one `period: all` period by `None`, and a live exporter by its start.
    if period == ExporterPeriod.ALL:
        return None, None

    return start, period_shift(period, start, 1)


async def _prepend[T](first: T, rest: AsyncIterator[T]) -> AsyncIterator[T]:
    yield first
    async for item in rest:
        yield item
