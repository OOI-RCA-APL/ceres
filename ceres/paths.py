import re
import socket
from collections.abc import Callable, Iterable, Iterator, Mapping
from datetime import UTC, datetime, timedelta, tzinfo
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, override
from zoneinfo import ZoneInfo

import tzlocal
from pydantic import BeforeValidator, Field

if TYPE_CHECKING:
    from os import PathLike

    from pydantic import GetCoreSchemaHandler
    from pydantic_core import CoreSchema

__all__ = [
    "PathLayout",
    "PathTemplate",
    "rel",
    "proj",
]


def rel(path: str | PathLike[str]) -> Path:
    """Resolve a path relative to the calling module's parent directory.

    Args:
        path: Path relative to the calling module's parent directory.

    Returns:
        The absolute path.
    """
    return _get_current_python_module_path() / Path(path)


def proj(relative: str | PathLike | None = None) -> Path:
    """Resolve a path relative to the current Python project's root directory.

    The project root is the parent directory of the nearest `pyproject.toml` file found
    when walking up from the calling module's file. If `relative` is provided, join it
    onto the project root, otherwise return the root itself.

    Args:
        relative: Path relative to the project root, or `None` to return the root.

    Returns:
        The absolute path to the requested location.

    Raises:
        AssertionError: If no parent directory contains a `pyproject.toml` file.
    """
    current = _get_current_python_module_path()
    root = None

    for current in current.parents:
        if (current / "pyproject.toml").is_file():
            root = current
            break

    assert root, (
        "Could not find project root. No parent directory contains a `pyproject.toml` file."
    )
    if relative is not None:
        return root / Path(relative)

    return root


def _get_current_python_module_path() -> Path:
    import inspect

    caller = inspect.stack()[2]
    module = inspect.getmodule(caller[0])
    assert module is not None
    assert module.__file__ is not None
    return Path(module.__file__)


_MONTHS: Final = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_WEEKDAYS: Final = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _offset(when: datetime) -> str:
    offset = when.utcoffset()
    minutes = 0 if offset is None else int(offset.total_seconds()) // 60
    sign = "-" if minutes < 0 else "+"
    return f"{sign}{abs(minutes) // 60:02d}{abs(minutes) % 60:02d}"


# The `strftime` directives a `{time:...}` atom may use, rendered here rather than by the
# platform, so every platform and the console's renderer agree and names stay English.
_DIRECTIVES: Final[Mapping[str, Callable[[datetime], str]]] = {
    "Y": lambda when: f"{when.year:04d}",
    "y": lambda when: f"{when.year % 100:02d}",
    "m": lambda when: f"{when.month:02d}",
    "d": lambda when: f"{when.day:02d}",
    "H": lambda when: f"{when.hour:02d}",
    "I": lambda when: f"{(when.hour - 1) % 12 + 1:02d}",
    "p": lambda when: "AM" if when.hour < 12 else "PM",
    "M": lambda when: f"{when.minute:02d}",
    "S": lambda when: f"{when.second:02d}",
    "j": lambda when: f"{when.timetuple().tm_yday:03d}",
    "b": lambda when: _MONTHS[when.month - 1][:3],
    "B": lambda when: _MONTHS[when.month - 1],
    "a": lambda when: _WEEKDAYS[when.weekday()][:3],
    "A": lambda when: _WEEKDAYS[when.weekday()],
    "G": lambda when: f"{when.isocalendar().year:04d}",
    "V": lambda when: f"{when.isocalendar().week:02d}",
    "u": lambda when: str(when.isoweekday()),
    "w": lambda when: str(when.isoweekday() % 7),
    "z": _offset,
    "Z": lambda when: when.tzname() or _offset(when),
    "%": lambda when: "%",
}


def _strftime(pattern: str) -> Callable[[datetime], str]:
    """Compile `pattern`, a `strftime` pattern limited to `_DIRECTIVES`, into a renderer.

    Raises:
        ValueError: If `pattern` uses another directive or ends in a lone `%`.
    """
    pieces: list[str | Callable[[datetime], str]] = []
    for match in re.finditer(r"%(.?)|[^%]+", pattern, re.DOTALL):
        if not match.group().startswith("%"):
            pieces.append(match.group())
            continue

        directive = _DIRECTIVES.get(match.group(1))
        if directive is None:
            raise ValueError(f"'{pattern}' uses '{match.group()}', which a template cannot use")

        pieces.append(directive)

    return lambda when: "".join(
        piece if isinstance(piece, str) else piece(when) for piece in pieces
    )


_TIME_ATOMS: Final[Mapping[str, Callable[[datetime], str]]] = {
    "year": _strftime("%Y"),
    "month": _strftime("%m"),
    "day": _strftime("%d"),
    "hour": _strftime("%H"),
    "minute": _strftime("%M"),
    "second": _strftime("%S"),
    "date": _strftime("%Y%m%d"),
    "time": _strftime("%H%M%S"),
    "datetime": _strftime("%Y%m%dT%H%M%S"),
    "week": _strftime("%V"),
    "doy": _strftime("%j"),
    "epoch": lambda when: str(int(when.timestamp() // 1)),
    "zone": _strftime("%Z"),
    "yy": _strftime("%y"),
    "m": lambda when: str(when.month),
    "d": lambda when: str(when.day),
    "h": lambda when: str(when.hour),
    "mon": _strftime("%b"),
    "month_name": _strftime("%B"),
    "wd": _strftime("%a"),
    "weekday": _strftime("%A"),
}

_IDENTITY_ATOMS: Final = frozenset({"component", "mount", "connection", "project", "host"})

# Device names Windows reserves in every directory, with or without an extension.
_RESERVED: Final = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"{device}{i}" for device in ("COM", "LPT") for i in range(1, 10)}
)

_FORBIDDEN: Final = re.compile(r'[<>:"|?*\\\x00-\x1f]')

# Renders every template once at construction, so a pattern that can only fail at render
# time, such as a `strftime` directive producing a separator, fails at once.
_PROBE: Final = datetime(2001, 2, 3, 4, 5, 6, tzinfo=UTC)


@lru_cache(maxsize=64)
def resolve_zone(zone: str) -> tzinfo | None:
    """Return the time zone `zone` names, `None` for the system's local zone.

    `None` is what `datetime.astimezone` takes for the local zone. The cache holds one entry
    per configured zone name, a handful in any project.

    Args:
        zone: `utc`, `local`, or an IANA name such as `America/Los_Angeles`.

    Raises:
        ValueError: If `zone` names no known time zone.
    """
    if zone == "utc":
        return UTC

    if zone == "local":
        return None

    try:
        return ZoneInfo(zone)
    except (ValueError, LookupError) as error:
        raise ValueError(f"'{zone}' is not a time zone, use utc, local, or an IANA name") from error


def zone_name(zone: str) -> str:
    """Return the IANA name of the time zone `zone` names, the system's own for `local`.

    Raises:
        ValueError: If `zone` names no known time zone.
    """
    resolve_zone(zone)
    if zone == "utc":
        return "UTC"

    if zone == "local":
        return tzlocal.get_localzone_name() or "UTC"

    return zone


def host_name() -> str:
    """Return this machine's host name up to its first dot, the value of `{host}`."""
    return socket.gethostname().partition(".")[0]


class _Atom:
    __slots__ = ("name", "render")

    def __init__(self, name: str, render: Callable[[datetime, Mapping[str, object]], str]):
        self.name = name
        self.render = render


class PathTemplate:
    """A relative path rendered from a time and a few names, a file name or a folder layout.

    Atoms in braces stand for parts of the time or for names: `{year}/{month}` or
    `TimeLapse_{datetime}_{zone}.jpg`. Long time atoms are zero padded to a fixed width,
    `{date}` `20261027`, `{time}` `134509`, `{datetime}` `20261027T134509`, and short ones read
    as people write them, `{m}` `10`, `{mon}` `Oct`, `{weekday}` `Tuesday`. `{time:%j}` renders
    a `strftime` pattern. `{component}`, `{mount}`, `{connection}`, `{project}`, and `{host}`
    stand for names the producer supplies, and a producer may declare more atoms of its own.
    `{{` and `}}` write a brace.
    """

    __slots__ = ("_source", "_parts", "_atoms")

    def __init__(self, source: str, *, atoms: Iterable[str] = ()):
        """Parse `source`.

        Args:
            source: The template.
            atoms: Names of atoms the producer supplies beyond the standard ones.

        Raises:
            ValueError: If `source` uses an unknown atom, is absolute, has an empty or `..`
                segment, or renders a name Windows reserves or a character a file name cannot
                hold.
        """
        extras = frozenset(atoms)
        parts: list[str | _Atom] = []
        position = 0
        for match in re.finditer(r"\{\{|\}\}|\{([^{}]*)\}|[{}]", source):
            parts.append(source[position : match.start()])
            position = match.end()
            text = match.group()
            if text in ("{{", "}}"):
                parts.append(text[0])
            elif match.group(1) is None:
                raise ValueError(f"template '{source}' has an unmatched '{text}'")
            else:
                parts.append(_parse_atom(source, match.group(1), extras))

        parts.append(source[position:])
        self._source = source
        self._parts = tuple(part for part in parts if part != "")
        self._atoms = frozenset(part.name for part in self._parts if isinstance(part, _Atom))

        if source.startswith(("/", "\\")):
            raise ValueError(f"template '{source}' is absolute, a template renders relative paths")

        self.render(_PROBE, values=dict.fromkeys(self._atoms, "x"))

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        source_type: Any,
        handler: GetCoreSchemaHandler,
    ) -> CoreSchema:
        from pydantic_core.core_schema import (
            is_instance_schema,
            no_info_after_validator_function,
            plain_serializer_function_ser_schema,
            str_schema,
            union_schema,
        )

        return union_schema(
            [is_instance_schema(cls), no_info_after_validator_function(cls, str_schema())],
            serialization=plain_serializer_function_ser_schema(str),
        )

    @staticmethod
    def Field(default: Any = ..., *, atoms: Iterable[str] = (), **kwargs: Any) -> Any:
        """Declare a pydantic field holding a template that may use `atoms`.

        A string `default` is parsed here, so a bad default fails when the class is created. A
        configured value is parsed with the same `atoms`.

        Args:
            default: The template, or `...` for a required field.
            atoms: Names of atoms the producer supplies beyond the standard ones.
            **kwargs: Passed to `pydantic.Field`.
        """
        names = tuple(atoms)

        def parse(value: object) -> object:
            if isinstance(value, PathTemplate):
                value = value.source

            return PathTemplate(value, atoms=names) if isinstance(value, str) else value

        info = Field(parse(default), **kwargs)
        info.metadata.append(BeforeValidator(parse))
        return info

    @property
    def source(self) -> str:
        """The template as written."""
        return self._source

    @property
    def atoms(self) -> frozenset[str]:
        """Names of every atom the template uses."""
        return self._atoms

    def render(
        self,
        when: datetime,
        zone: str = "utc",
        values: Mapping[str, object] | None = None,
    ) -> str:
        """Render the path for `when`, a `/` between segments.

        Args:
            when: A timezone-aware time.
            zone: Time zone the time atoms read in, see `resolve_zone`.
            values: Value of each name atom. `{host}` defaults to this machine's short name.

        Raises:
            ValueError: If `when` is naive, a name atom has no value or renders a separator,
                or the path breaks a rule `PathTemplate` checks at construction.
        """
        if when.tzinfo is None:
            raise ValueError("a template renders only a timezone-aware time")

        local = when.astimezone(resolve_zone(zone))
        given = {} if values is None else values
        pieces: list[str] = []
        for part in self._parts:
            if isinstance(part, str):
                pieces.append(part)
                continue

            text = part.render(local, given)
            if "/" in text or "\\" in text:
                raise ValueError(
                    f"atom '{{{part.name}}}' renders '{text}', which holds a separator"
                )

            pieces.append(text)

        path = "".join(pieces)
        for segment in path.split("/"):
            _check_segment(self._source, segment)

        return path

    @override
    def __str__(self) -> str:
        return self._source

    @override
    def __repr__(self) -> str:
        return f"PathTemplate({self._source!r})"

    @override
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PathTemplate):
            return NotImplemented

        return self._source == other._source

    @override
    def __hash__(self) -> int:
        return hash(self._source)


def _parse_atom(source: str, body: str, extras: frozenset[str]) -> _Atom:
    name, colon, pattern = body.partition(":")
    if colon:
        if name != "time":
            raise ValueError(
                f"template '{source}' gives a pattern to '{{{name}}}', only '{{time}}' takes one"
            )

        render = _strftime(pattern)
        return _Atom(name, lambda when, values: render(when))

    time = _TIME_ATOMS.get(name)
    if time is not None:
        return _Atom(name, lambda when, values: time(when))

    if name not in _IDENTITY_ATOMS and name not in extras:
        raise ValueError(f"template '{source}' uses '{{{name}}}', which is not an atom")

    return _Atom(name, lambda when, values: _name_value(name, values))


def _name_value(name: str, values: Mapping[str, object]) -> str:
    given = values.get(name)
    if given is None and name == "host":
        return host_name()

    if given is None:
        raise ValueError(f"atom '{{{name}}}' has no value")

    return str(given)


class _Capture:
    """One calendar field a layout atom renders, and how to read it back from a folder name."""

    __slots__ = ("field", "pattern", "read")

    def __init__(self, field: str, pattern: str, read: Callable[[str], int] = int):
        self.field = field
        self.pattern = pattern
        self.read = read


def _names(names: Iterable[str], field: str) -> _Capture:
    listed = list(names)
    return _Capture(field, "|".join(listed), lambda text: listed.index(text) + 1)


_DATE: Final = (_Capture("year", r"\d{4}"), _Capture("month", r"\d{2}"), _Capture("day", r"\d{2}"))
_TIME: Final = (
    _Capture("hour", r"\d{2}"),
    _Capture("minute", r"\d{2}"),
    _Capture("second", r"\d{2}"),
)

# The time atoms a layout may use, each read back by `PathLayout.walk`. A capture of variable
# width cannot sit beside another, `{m}{d}` reads `111` two ways.
_LAYOUT_ATOMS: Final[Mapping[str, tuple[_Capture | str, ...]]] = {
    "year": (_DATE[0],),
    "yy": (_Capture("year", r"\d{2}", lambda text: 2000 + int(text)),),
    "month": (_DATE[1],),
    "m": (_Capture("month", r"\d{1,2}"),),
    "mon": (_names((month[:3] for month in _MONTHS), "month"),),
    "month_name": (_names(_MONTHS, "month"),),
    "doy": (_Capture("doy", r"\d{3}"),),
    "day": (_DATE[2],),
    "d": (_Capture("day", r"\d{1,2}"),),
    "hour": (_TIME[0],),
    "h": (_Capture("hour", r"\d{1,2}"),),
    "minute": (_TIME[1],),
    "second": (_TIME[2],),
    "date": _DATE,
    "time": _TIME,
    "datetime": (*_DATE, "T", *_TIME),
}
_VARIABLE_WIDTH: Final = frozenset({"m", "d", "h", "mon", "month_name"})
_LAYOUT_NAMES: Final = frozenset({"component", "mount", "project", "host"})

_CALENDAR: Final = ("year", "month", "day", "hour", "minute", "second")


class PathLayout(PathTemplate):
    """A `PathTemplate` for dated folders, which `walk` reads back to find a time range.

    A layout uses calendar atoms from the year down without a gap, `{year}/{month}` or
    `{year}/{doy}`, plus `{component}`, `{mount}`, `{project}`, and `{host}`. A folder's
    period runs from its time to the next value of its finest atom.
    """

    __slots__ = ("_segments",)

    def __init__(self, source: str):
        """Parse `source`.

        Raises:
            ValueError: If `source` breaks a `PathTemplate` rule, uses an atom a folder name
                cannot be read back from, skips a calendar field, or puts two atoms of
                variable width side by side.
        """
        super().__init__(source)
        segments: list[list[str | _Atom]] = [[]]
        for part in self._parts:
            if isinstance(part, _Atom):
                if part.name not in _LAYOUT_ATOMS and part.name not in _LAYOUT_NAMES:
                    raise ValueError(
                        f"layout '{source}' uses '{{{part.name}}}', which a folder cannot"
                    )

                if (
                    part.name in _VARIABLE_WIDTH
                    and segments[-1]
                    and isinstance(segments[-1][-1], _Atom)
                    and segments[-1][-1].name in _VARIABLE_WIDTH
                ):
                    raise ValueError(f"layout '{source}' puts two atoms of variable width together")

                segments[-1].append(part)
                continue

            first, *rest = part.split("/")
            segments[-1].append(first)
            segments.extend([piece] for piece in rest)

        fields = {
            capture.field
            for part in self._parts
            if isinstance(part, _Atom)
            for capture in _LAYOUT_ATOMS.get(part.name, ())
            if isinstance(capture, _Capture)
        }
        if "doy" in fields:
            fields |= {"month", "day"}

        if fields - {"doy"} != set(_CALENDAR[: len(fields - {"doy"})]):
            raise ValueError(f"layout '{source}' must name calendar fields from the year down")

        self._segments = tuple(tuple(segment) for segment in segments)

    def walk(
        self,
        root: Path,
        after: datetime,
        before: datetime,
        zone: str = "utc",
        values: Mapping[str, object] | None = None,
    ) -> Iterator[Path]:
        """Yield each existing folder below `root` whose period overlaps `after` to `before`.

        Folders come in time order. A name the layout cannot have rendered is skipped.

        Args:
            root: Folder the layout starts from.
            after: Start of the range, inclusive, timezone-aware.
            before: End of the range, exclusive, timezone-aware.
            zone: Time zone the folder names are written in, see `resolve_zone`.
            values: Value of each name atom, as `render` takes them.

        Raises:
            ValueError: If `after` or `before` is naive, or a name atom has no value.
        """
        if after.tzinfo is None or before.tzinfo is None:
            raise ValueError("a layout walks only a timezone-aware range")

        given = {} if values is None else values
        patterns = [_segment_pattern(segment, given) for segment in self._segments]
        place = resolve_zone(zone)

        def visit(folder: Path, depth: int, known: dict[str, int]) -> Iterator[Path]:
            if depth == len(patterns):
                yield folder
                return

            pattern, captures = patterns[depth]
            try:
                entries = list(folder.iterdir())
            except FileNotFoundError, NotADirectoryError:
                return

            found: list[tuple[tuple[int, ...], str, Path, dict[str, int]]] = []
            for entry in entries:
                match = pattern.fullmatch(entry.name)
                fields = None if match is None else _merge(known, captures, match.groups())
                if fields is None or not entry.is_dir():
                    continue

                try:
                    period = _period(fields, place)
                except ValueError, OverflowError:
                    continue

                if period is not None and not (period[0] < before and period[1] > after):
                    continue

                key = tuple(fields.get(field, 0) for field in (*_CALENDAR, "doy"))
                found.append((key, entry.name, entry, fields))

            for _, _, entry, fields in sorted(found, key=lambda item: item[:2]):
                yield from visit(entry, depth + 1, fields)

        yield from visit(root, 0, {})


def _segment_pattern(
    segment: Iterable[str | _Atom],
    values: Mapping[str, object],
) -> tuple[re.Pattern[str], list[_Capture]]:
    pattern: list[str] = []
    captures: list[_Capture] = []
    for part in segment:
        if isinstance(part, str):
            pattern.append(re.escape(part))
            continue

        if part.name in _LAYOUT_NAMES:
            pattern.append(re.escape(_name_value(part.name, values)))
            continue

        for piece in _LAYOUT_ATOMS[part.name]:
            if isinstance(piece, str):
                pattern.append(re.escape(piece))
            else:
                pattern.append(f"({piece.pattern})")
                captures.append(piece)

    return re.compile("".join(pattern)), captures


def _merge(
    known: Mapping[str, int],
    captures: Iterable[_Capture],
    groups: Iterable[str | None],
) -> dict[str, int] | None:
    """Return `known` plus the fields a folder name gives, `None` when two disagree."""
    fields = dict(known)
    for capture, text in zip(captures, groups, strict=True):
        assert text is not None
        value = capture.read(text)
        if fields.setdefault(capture.field, value) != value:
            return None

    if "doy" in fields and "year" in fields:
        try:
            day = datetime(fields["year"], 1, 1) + timedelta(days=fields["doy"] - 1)  # noqa: DTZ001
        except OverflowError:
            return None

        if day.year != fields["year"]:
            return None

        for field, value in (("month", day.month), ("day", day.day)):
            if fields.setdefault(field, value) != value:
                return None

    return fields


def _period(fields: Mapping[str, int], place: tzinfo | None) -> tuple[datetime, datetime] | None:
    """Return the span `fields` name, `None` when they name no calendar prefix yet.

    Raises:
        ValueError: If the fields name no real date, such as month 13.
    """
    depth = 0
    while depth < len(_CALENDAR) and _CALENDAR[depth] in fields:
        depth += 1

    if depth == 0 or any(field in fields for field in _CALENDAR[depth:]):
        return None

    start = datetime(  # noqa: DTZ001
        fields["year"],
        fields.get("month", 1),
        fields.get("day", 1),
        fields.get("hour", 0),
        fields.get("minute", 0),
        fields.get("second", 0),
    )
    unit = _CALENDAR[depth - 1]
    if unit == "year":
        end = start.replace(year=start.year + 1)
    elif unit == "month":
        end = (start + timedelta(days=32)).replace(day=1)
    else:
        end = start + timedelta(**{f"{unit}s": 1})

    return _localize(start, place), _localize(end, place)


def _localize(naive: datetime, place: tzinfo | None) -> datetime:
    return naive.astimezone() if place is None else naive.replace(tzinfo=place)


def _check_segment(source: str, segment: str) -> None:
    if segment in ("", ".", ".."):
        raise ValueError(f"template '{source}' renders an empty, '.', or '..' segment")

    if _FORBIDDEN.search(segment):
        raise ValueError(
            f"template '{source}' renders '{segment}', which holds a reserved character"
        )

    if segment.partition(".")[0].upper() in _RESERVED or segment.endswith((".", " ")):
        raise ValueError(f"template '{source}' renders '{segment}', a name Windows reserves")
