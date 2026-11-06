"""NetCDF files of particles: the variables a data class gives, and the arrays that fill them."""

import math
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import NoneType, UnionType
from typing import TYPE_CHECKING, Annotated, Any, TypeAliasType, Union, get_args, get_origin

import h5netcdf
import h5py
import numpy
from pydantic import AwareDatetime, NaiveDatetime
from pydantic.fields import FieldInfo

from ceres.data.binary import PackedSequence, PackingSchema

if TYPE_CHECKING:
    from pathlib import Path

    from ceres.exporter import ExportField
    from ceres.particle import Particle

TIME_UNITS = "seconds since 1970-01-01T00:00:00Z"
"""CF units of the `time` variable and of every datetime variable."""

TIME_CALENDAR = "standard"

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

_CHUNK_ROWS = 65536
"""Most rows allocated at once while records stream in, so a period never reallocates per row."""

_CHUNK_BYTES = 4 * 1024 * 1024
"""Most bytes one chunk allocates, so a wide row never costs a full chunk of rows."""

_ID_LENGTH = 36
"""Characters of a UUID's canonical text form, the width of the `id` variable."""

KEY_DTYPE = numpy.dtype([("time", "<i8"), ("id", f"S{_ID_LENGTH}")])
"""A record key as one array element, microseconds since the epoch then the UUID text.

Structured arrays sort and search field by field, so arrays of keys sort in key order.
"""

_NO_CONNECTION = -1

# netCDF's default fill values, which readers treat as missing data without an attribute.
_FILL_VALUES: dict[str, Any] = {
    "i1": -127,
    "u1": 255,
    "i2": -32767,
    "u2": 65535,
    "i4": -2147483647,
    "u4": 4294967295,
    "i8": -9223372036854775806,
    "u8": 18446744073709551614,
    "f4": 9.969209968386869e36,
    "f8": 9.969209968386869e36,
}

_DATETIME_MARKERS = frozenset({NaiveDatetime, AwareDatetime})


@dataclass(frozen=True, slots=True)
class NetCDFVariable:
    """One data variable of a NetCDF file and the particle data field it reads."""

    name: str
    """Variable name, a nested field joined to its section's name with `_`."""

    dtype: str
    """NumPy type code of the stored values, `str` for variable-length text."""

    path: tuple[str, ...]
    """Attribute names leading from a particle's data to the field."""

    shape: tuple[int, ...] = ()
    """Sizes of the dimensions after `time`, one per level of a fixed-length sequence."""

    datetime: bool = False
    """Whether the field holds datetimes, stored as seconds since the epoch."""

    units: str | None = None
    """Units the field's `Unit()` annotation names."""

    @property
    def dimensions(self) -> tuple[str, ...]:
        """The variable's dimensions, `time` first."""
        return ("time", *(f"{self.name}_{index}" for index in range(len(self.shape))))

    @property
    def fill(self) -> Any:
        """The value an absent field stores."""
        return "" if self.dtype == "str" else _FILL_VALUES[self.dtype]

    def get(self, data: Any) -> Any:
        """Return the field's stored form from a particle's data, `None` when it is absent."""
        for name in self.path:
            if data is None:
                return None

            data = getattr(data, name)

        if data is None:
            return None
        if self.datetime:
            moment: datetime = data
            return (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).timestamp()
        if self.dtype == "str":
            return str(data)

        return data


def netcdf_variables(
    fields: Sequence[ExportField],
) -> tuple[tuple[NetCDFVariable, ...], tuple[str, ...]]:
    """Derive the data variables of a particle class's NetCDF files from its fields.

    Scalars become variables over `time`. A nested data object's fields join its name with
    `_` unless they already start with it, and an object holding a sequence of open length is
    left out whole. Fixed-shape tuples and `PackedSequence(length=N)` sequences gain a
    dimension per level, and any other field is left out.

    Returns:
        The variables, and the dotted paths of the fields they leave out.

    Raises:
        ValueError: If two fields give one name, or a name collides with a fixed variable or a
            dimension.
    """
    variables: list[NetCDFVariable] = []
    dropped: list[str] = []
    _variables(fields, None, (), variables, dropped)

    seen = {"time", "id", "connection", "connection_name", "connections", f"string{_ID_LENGTH}"}
    for variable in variables:
        for name in (variable.name, *variable.dimensions[1:]):
            if name in seen:
                raise ValueError(f"netcdf variable '{name}' collides with another variable")

            seen.add(name)

    return tuple(variables), tuple(dropped)


def _variables(
    fields: Sequence[ExportField],
    section: str | None,
    path: tuple[str, ...],
    variables: list[NetCDFVariable],
    dropped: list[str],
) -> None:
    for field in fields:
        name = (
            field.name
            if section is None or field.name.startswith(section)
            else f"{section}_{field.name}"
        )
        if field.fields:
            if any(_ragged(inner.info) for inner in field.fields):
                dropped.append(".".join((*path, field.name)))
            else:
                _variables(field.fields, name, (*path, field.name), variables, dropped)

            continue

        variable = _variable(name, field.info, (*path, field.name))
        if variable is None:
            dropped.append(".".join((*path, field.name)))
        else:
            variables.append(variable)


def _variable(name: str, info: FieldInfo, path: tuple[str, ...]) -> NetCDFVariable | None:
    annotation, metadata = info.annotation, tuple(info.metadata)
    units = _units(info)
    if _is_datetime(annotation):
        return NetCDFVariable(name, "f8", path, datetime=True, units=units)

    dtype = _scalar_dtype(annotation, metadata)
    if dtype is not None:
        return NetCDFVariable(name, dtype, path, units=units)

    shaped = _fixed_length(annotation, metadata) or _tuple_shape(annotation)
    if shaped is not None:
        shape, dtype = shaped
        return NetCDFVariable(name, dtype, path, shape, units=units)

    return None


def _peel(annotation: Any) -> Any:
    # Resolves type aliases and strips `None` from an optional, keeping `Annotated`.
    while isinstance(annotation, TypeAliasType):
        annotation = annotation.__value__

    if get_origin(annotation) in (Union, UnionType):
        members = [member for member in get_args(annotation) if member is not NoneType]
        if len(members) == 1:
            return _peel(members[0])

    return annotation


def _unwrap(annotation: Any) -> tuple[Any, tuple[Any, ...]]:
    # Returns the base type under every alias, optional and `Annotated`, with the metadata
    # the `Annotated` layers carried, outermost first.
    metadata: list[Any] = []
    annotation = _peel(annotation)
    while get_origin(annotation) is Annotated:
        base, *extra = get_args(annotation)
        metadata.extend(extra)
        annotation = _peel(base)

    return annotation, tuple(metadata)


def _is_datetime(annotation: Any) -> bool:
    if _peel(annotation) in _DATETIME_MARKERS:
        return True

    base, _ = _unwrap(annotation)
    return isinstance(base, type) and issubclass(base, datetime)


def _packed_dtype(metadata: Sequence[Any]) -> str | None:
    for entry in metadata:
        if isinstance(entry, PackingSchema) and entry.symbol:
            kind = numpy.dtype(entry.symbol)
            if kind.kind == "b":
                # NetCDF has no boolean type, so booleans store as bytes.
                return "i1"
            if kind.kind == "f":
                # NetCDF has no half precision, so it widens to single.
                return f"f{max(kind.itemsize, 4)}"
            if kind.kind in "iu":
                return f"{kind.kind}{kind.itemsize}"

    return None


def _scalar_dtype(annotation: Any, metadata: Sequence[Any] = ()) -> str | None:
    base, wrapped = _unwrap(annotation)
    packed = _packed_dtype((*metadata, *wrapped))
    if packed is not None:
        return packed

    if get_origin(base) in (Union, UnionType):
        # `Number` is `int | float`, which has no fixed width, so it stores as a double.
        return "f8" if set(get_args(base)) <= {int, float} else None

    if isinstance(base, type):
        if issubclass(base, bool):
            return "i1"
        if issubclass(base, str):
            return "str"
        if issubclass(base, int):
            return "i8"
        if issubclass(base, float):
            return "f8"

    return None


def _tuple_shape(annotation: Any) -> tuple[tuple[int, ...], str] | None:
    # A variable-length `tuple[X, ...]` has no shape, so it returns `None` like a ragged list.
    base, _ = _unwrap(annotation)
    arguments = get_args(base)
    if get_origin(base) is not tuple or not arguments or Ellipsis in arguments:
        return None

    inner = _tuple_shape(arguments[0])
    if inner is not None:
        return (len(arguments), *inner[0]), inner[1]

    dtype = _scalar_dtype(arguments[0])
    if dtype is None or dtype == "str":
        return None

    return (len(arguments),), dtype


def _fixed_length(annotation: Any, metadata: Sequence[Any]) -> tuple[tuple[int, ...], str] | None:
    # Pydantic keeps the `tuple[X, ...]` annotation and moves `PackedSequence(length=N)` into
    # the field's metadata, so the length comes from there.
    base, wrapped = _unwrap(annotation)
    item = _open_item(base)
    length = _packed_length((*metadata, *wrapped))
    if item is None or length is None:
        return None

    dtype = _scalar_dtype(item[0])
    if dtype is None or dtype == "str":
        return None

    return (length,), dtype


def _ragged(info: FieldInfo) -> bool:
    # A sequence of open length without a `PackedSequence` length varies from row to row.
    base, wrapped = _unwrap(info.annotation)
    return _open_item(base) is not None and _packed_length((*info.metadata, *wrapped)) is None


def _open_item(base: Any) -> tuple[Any] | None:
    # Returns the item type of a sequence its type leaves open in length, in a one-tuple so an
    # item of `None` stays apart from no sequence.
    origin, arguments = get_origin(base) or base, get_args(base)
    if origin in (list, Sequence) or (origin is tuple and arguments[-1:] in ((), (Ellipsis,))):
        return (arguments[0] if arguments else Any,)

    return None


def _packed_length(metadata: Sequence[Any]) -> int | None:
    for entry in metadata:
        if isinstance(entry, PackedSequence) and entry.length is not None:
            return entry.length

    return None


def _units(info: FieldInfo) -> str | None:
    # `Unit()` is a `Field` whose JSON schema extra pydantic merges into the field, unless a
    # type alias carries it, where it stays in the alias's `Annotated` metadata.
    for extra in (info.json_schema_extra, *_field_extras(info.annotation)):
        if isinstance(extra, Mapping) and isinstance(unit := extra.get("unit"), str):
            return unit

    return None


def _field_extras(annotation: Any) -> Iterator[Any]:
    _, metadata = _unwrap(annotation)
    for entry in metadata:
        if isinstance(entry, FieldInfo):
            yield entry.json_schema_extra


@dataclass(slots=True)
class NetCDFTable:
    """The rows of one NetCDF file as typed arrays, in key order."""

    keys: numpy.ndarray[Any, Any]
    """Each row's key as `KEY_DTYPE`."""

    connection: numpy.ndarray[Any, Any]
    """Each row's index into `connections`, `-1` for a particle with no connection."""

    connections: list[str]
    """The connection names rows refer to, sorted so equal rows give equal files."""

    values: dict[str, numpy.ndarray[Any, Any]]
    """Each data variable's values, shaped `(rows, *shape)`."""

    @property
    def rows(self) -> int:
        """The table's row count."""
        return len(self.keys)

    def sorted(self) -> bool:
        """Return whether every key is greater than the one before it."""
        time, id = self.keys["time"], self.keys["id"]
        later = (time[1:] > time[:-1]) | ((time[1:] == time[:-1]) & (id[1:] > id[:-1]))
        return bool(later.all())


def _reindex(
    connection: numpy.ndarray[Any, Any], names: list[str], index: Mapping[str, int]
) -> numpy.ndarray[Any, Any]:
    lookup = numpy.array([index[name] for name in names] + [_NO_CONNECTION], dtype="i2")
    # `-1` reads the lookup's last entry, so a row with no connection keeps `-1`.
    return lookup[connection]


class NetCDFRows:
    """Collects streamed particles into a `NetCDFTable`, one preallocated chunk at a time."""

    __slots__ = ("__chunk_rows", "__chunks", "__connections", "__row", "__variables")

    def __init__(self, variables: Sequence[NetCDFVariable]) -> None:
        self.__variables = variables
        self.__chunks: list[tuple[numpy.ndarray[Any, Any], numpy.ndarray[Any, Any], dict[str, Any]]]
        self.__chunks = []
        row_bytes = KEY_DTYPE.itemsize + numpy.dtype("i2").itemsize
        for variable in variables:
            dtype = numpy.dtype(object if variable.dtype == "str" else variable.dtype)
            row_bytes += dtype.itemsize * math.prod(variable.shape)

        self.__chunk_rows = max(1, min(_CHUNK_ROWS, _CHUNK_BYTES // row_bytes))
        self.__row = self.__chunk_rows
        self.__connections: dict[str, int] = {}

    @property
    def chunk_rows(self) -> int:
        """Rows each chunk allocates, fewer than `_CHUNK_ROWS` when rows are wide."""
        return self.__chunk_rows

    def add(self, particle: Particle[Any]) -> None:
        """Add one particle as the next row."""
        if self.__row == self.__chunk_rows:
            self.__chunks.append(self.__allocate())
            self.__row = 0

        keys, connection, values = self.__chunks[-1]
        row = self.__row
        keys[row] = (encode_time(particle.timestamp), str(particle.id).encode())
        if particle.connection is not None:
            connection[row] = self.__connections.setdefault(
                particle.connection, len(self.__connections)
            )

        for variable in self.__variables:
            value = variable.get(particle.data)
            if value is not None:
                values[variable.name][row] = value

        self.__row += 1

    def finish(self) -> NetCDFTable:
        """Return the rows added so far as a table, its connection names sorted."""
        if self.__chunks:
            self.__chunks[-1] = _head(self.__chunks[-1], self.__row)

        names = list(self.__connections)
        table = NetCDFTable(
            numpy.concatenate([keys for keys, _, _ in self.__chunks] or [_keys(0)]),
            numpy.concatenate(
                [connection for _, connection, _ in self.__chunks] or [_connections(0)]
            ),
            names,
            {
                variable.name: numpy.concatenate(
                    [values[variable.name] for _, _, values in self.__chunks]
                    or [_values(variable, 0)]
                )
                for variable in self.__variables
            },
        )
        index = {name: position for position, name in enumerate(sorted(names))}
        table.connection = _reindex(table.connection, names, index)
        table.connections = sorted(names)
        return table

    def __allocate(
        self,
    ) -> tuple[numpy.ndarray[Any, Any], numpy.ndarray[Any, Any], dict[str, Any]]:
        return (
            _keys(self.__chunk_rows),
            _connections(self.__chunk_rows),
            {variable.name: _values(variable, self.__chunk_rows) for variable in self.__variables},
        )


def _keys(rows: int) -> numpy.ndarray[Any, Any]:
    return numpy.zeros(rows, KEY_DTYPE)


def _connections(rows: int) -> numpy.ndarray[Any, Any]:
    return numpy.full(rows, _NO_CONNECTION, "i2")


def _values(variable: NetCDFVariable, rows: int) -> numpy.ndarray[Any, Any]:
    dtype = object if variable.dtype == "str" else variable.dtype
    return numpy.full((rows, *variable.shape), variable.fill, dtype)


def _head(
    chunk: tuple[numpy.ndarray[Any, Any], numpy.ndarray[Any, Any], dict[str, Any]], rows: int
) -> tuple[numpy.ndarray[Any, Any], numpy.ndarray[Any, Any], dict[str, Any]]:
    keys, connection, values = chunk
    return keys[:rows], connection[:rows], {name: array[:rows] for name, array in values.items()}


def encode_time(moment: datetime) -> int:
    """Return a datetime as whole microseconds since the epoch."""
    return (moment - _EPOCH) // timedelta(microseconds=1)


def seconds(microseconds: numpy.ndarray[Any, Any]) -> numpy.ndarray[Any, Any]:
    """Return microsecond times as the `time` variable's seconds since the epoch."""
    return microseconds / 1e6


__all__ = [
    "KEY_DTYPE",
    "TIME_CALENDAR",
    "TIME_UNITS",
    "NetCDFRows",
    "NetCDFTable",
    "NetCDFVariable",
    "encode_time",
    "netcdf_variables",
    "seconds",
    "write_table",
]


def write_table(
    path: Path,
    table: NetCDFTable,
    variables: Sequence[NetCDFVariable],
    attributes: Mapping[str, Mapping[str, str]],
    global_attributes: Mapping[str, str],
) -> None:
    """Write `table` as a complete NetCDF-4 file at `path`, blocking until it is written."""
    compression: dict[str, Any] = {"compression": "gzip", "compression_opts": 4}
    with h5netcdf.File(path, "w") as file:
        file.dimensions = {
            "time": table.rows,
            f"string{_ID_LENGTH}": _ID_LENGTH,
            # A variable named after a dimension it does not span gets renamed in HDF5, so the
            # name table's dimension differs from the `connection` index variable.
            "connections": len(table.connections),
        }
        file.attrs.update(global_attributes)

        time = file.create_variable("time", ("time",), "f8", **compression)
        time.attrs.update({"units": TIME_UNITS, "calendar": TIME_CALENDAR})
        time[:] = seconds(table.keys["time"])

        id = file.create_variable("id", ("time", f"string{_ID_LENGTH}"), "S1", **compression)
        id[:] = _characters(table.keys["id"])

        names = file.create_variable("connection_name", ("connections",), h5py.string_dtype())
        names[:] = numpy.array(table.connections, dtype=object)
        connection = file.create_variable(
            "connection", ("time",), "i2", fillvalue=_NO_CONNECTION, **compression
        )
        connection[:] = table.connection

        for variable in variables:
            for dimension, size in zip(variable.dimensions[1:], variable.shape, strict=True):
                file.dimensions[dimension] = size

            if variable.dtype == "str":
                created = file.create_variable(
                    variable.name, variable.dimensions, h5py.string_dtype()
                )
            else:
                created = file.create_variable(
                    variable.name,
                    variable.dimensions,
                    variable.dtype,
                    fillvalue=variable.fill,
                    **compression,
                )

            if variable.datetime:
                created.attrs.update({"units": TIME_UNITS, "calendar": TIME_CALENDAR})
            elif variable.units is not None:
                created.attrs["units"] = variable.units

            created.attrs.update(attributes.get(variable.name, {}))
            if table.rows:
                created[:] = table.values[variable.name]


def _characters(ids: numpy.ndarray[Any, Any]) -> numpy.ndarray[Any, Any]:
    return numpy.ascontiguousarray(ids).view("S1").reshape(len(ids), _ID_LENGTH)
