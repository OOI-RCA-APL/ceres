import os
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


def _hour12(when: datetime) -> int:
    return (when.hour - 1) % 12 + 1


# The Unicode LDML date symbols (UTS #35) a template may use, one spelling per meaning. Names
# render from English tables rather than the platform, so every platform and the console's
# renderer agree.
_SYMBOLS: Final[Mapping[str, Callable[[datetime], str]]] = {
    "yyyy": lambda when: f"{when.year:04d}",
    "yy": lambda when: f"{when.year % 100:02d}",
    "MM": lambda when: f"{when.month:02d}",
    "M": lambda when: str(when.month),
    "MMM": lambda when: _MONTHS[when.month - 1][:3],
    "MMMM": lambda when: _MONTHS[when.month - 1],
    "dd": lambda when: f"{when.day:02d}",
    "d": lambda when: str(when.day),
    "DDD": lambda when: f"{when.timetuple().tm_yday:03d}",
    "HH": lambda when: f"{when.hour:02d}",
    "H": lambda when: str(when.hour),
    "hh": lambda when: f"{_hour12(when):02d}",
    "h": lambda when: str(_hour12(when)),
    "a": lambda when: "AM" if when.hour < 12 else "PM",
    "mm": lambda when: f"{when.minute:02d}",
    "ss": lambda when: f"{when.second:02d}",
    **{
        "S" * width: lambda when, width=width: f"{when.microsecond:06d}"[:width]
        for width in range(1, 7)
    },
    "EEE": lambda when: _WEEKDAYS[when.weekday()][:3],
    "EEEE": lambda when: _WEEKDAYS[when.weekday()],
    "Z": _offset,
    "XX": lambda when: "Z" if when.utcoffset() == timedelta(0) else _offset(when),
}

# Every other LDML spelling a reader might reach for, refused with the one meant.
_REFUSED: Final[Mapping[str, str]] = {
    **dict.fromkeys(("YYYY", "YY", "Y"), "the week-based year, use '{yyyy}' for the year"),
    "y": "use '{yyyy}' for the year",
    **dict.fromkeys(
        ("D", "DD"), "use '{DDD}' for the day of the year, '{dd}' for the day of the month"
    ),
    "m": "use '{mm}' for the minute",
    "s": "use '{ss}' for the second",
    **dict.fromkeys(("k", "kk", "K", "KK"), "use '{HH}' for the hour, or '{hh}' with '{a}'"),
    **dict.fromkeys(
        ("MMMMM", "L", "LL", "LLL", "LLLL"), "use '{MM}', '{MMM}', or '{MMMM}' for the month"
    ),
    **dict.fromkeys(("E", "EE"), "use '{EEE}' for the weekday"),
    **dict.fromkeys(("ZZ", "ZZZ"), "use '{Z}' for the offset"),
    **dict.fromkeys(
        ("ZZZZ", "XXX", "ZZZZZ"), "an offset with a colon, which a name cannot hold, use '{Z}'"
    ),
    "X": "an offset without its minutes, use '{XX}'",
    **dict.fromkeys(
        ("z", "zz", "zzz", "zzzz", "v", "vvvv", "O", "OOOO", "V", "VV"),
        "a zone name, which differs between platforms, use '{Z}' or '{XX}'",
    ),
    **dict.fromkeys(("w", "ww", "W"), "a week number, which a template does not render"),
    **dict.fromkeys(("u", "e", "ee", "c", "cc"), "a weekday number, use '{EEE}'"),
    "year": "use '{yyyy}' for the year",
    "month": "use '{MM}' for the month",
    "day": "use '{dd}' for the day",
    "hour": "use '{HH}' for the hour",
    "minute": "use '{mm}' for the minute",
    "second": "use '{ss}' for the second",
}

_HOURS: Final = frozenset({"HH", "H", "hh", "h"})

_IDENTITY_ATOMS: Final = frozenset({"component", "mount", "connection", "project", "host"})

# A producer's atom under one of these names would never render, the built-in takes it.
_BUILT_IN_ATOMS: Final = _SYMBOLS.keys() | _IDENTITY_ATOMS | {"epoch"}

_TOKEN: Final = re.compile(r"\{\{|\}\}|\{([^{}]*)\}|[{}]")

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

    Atoms in braces stand for parts of the time or for names: `{yyyy}/{MM}` or
    `TimeLapse_{yyyy}{MM}{dd}T{HH}{mm}{ss}_{XX}.jpg`. Time atoms are Unicode LDML date symbols,
    one spelling per meaning, and every other spelling is refused with the one meant.
    `{epoch}`, `{epoch:ms}`, and `{epoch:us}` count Unix time. `{component}`, `{mount}`,
    `{connection}`, `{project}`, and `{host}` stand for names the producer supplies, and a
    producer may declare more atoms of its own. `{{` and `}}` write a brace.
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
        for name in sorted(extras & _BUILT_IN_ATOMS):
            raise ValueError(f"atom '{name}' is a built-in")

        # The console's renderer tokenizes with this same expression, so both read one grammar.
        parts: list[str | _Atom] = []
        position = 0
        for match in _TOKEN.finditer(source):
            parts.append(source[position : match.start()])
            position = match.end()
            text = match.group()
            if text in ("{{", "}}"):
                parts.append(text[0])
            elif match.group(1) is None:
                raise ValueError(f"template '{source}' has an unmatched brace")
            else:
                parts.append(_parse_atom(source, match.group(1), extras))

        parts.append(source[position:])
        self._source = source
        self._parts = tuple(part for part in parts if part != "")
        self._atoms = frozenset(part.name for part in self._parts if isinstance(part, _Atom))

        if source.startswith(("/", "\\")):
            raise ValueError(f"template '{source}' is absolute, a template renders relative paths")

        _check_clock(source, self._atoms)
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


_EPOCH_ATOMS: Final[Mapping[str, int]] = {"epoch": 1, "epoch:ms": 1_000, "epoch:us": 1_000_000}


def _epoch(when: datetime, per_second: int) -> str:
    # Integer arithmetic, since a float timestamp scaled to microseconds is off by one.
    seconds = int((when - _EPOCH) // timedelta(seconds=1))
    return str(seconds * per_second + when.microsecond * per_second // 1_000_000)


_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)


def _parse_atom(source: str, body: str, extras: frozenset[str]) -> _Atom:
    name, colon, _ = body.partition(":")
    if colon or name == "epoch":
        per_second = _EPOCH_ATOMS.get(body)
        if per_second is None:
            raise ValueError(
                f"template '{source}' uses '{{{body}}}', only '{{epoch}}' takes a unit, ms or us"
            )

        return _Atom(body, lambda when, values: _epoch(when, per_second))

    symbol = _SYMBOLS.get(name)
    if symbol is not None:
        return _Atom(name, lambda when, values: symbol(when))

    if name in _IDENTITY_ATOMS or name in extras:
        return _Atom(name, lambda when, values: _name_value(name, values))

    refused = _REFUSED.get(name)
    if refused is None and re.fullmatch(r"S{7,}", name):
        refused = "use up to '{SSSSSS}', the microsecond"

    if refused is None and re.fullmatch(r"([A-Za-z])\1*", name):
        refused = "a date symbol a template does not render"

    if refused is not None:
        raise ValueError(f"template '{source}' uses '{{{name}}}', {refused}")

    raise ValueError(f"template '{source}' uses '{{{name}}}', which is not an atom")


def _check_clock(source: str, atoms: frozenset[str]) -> None:
    """Refuse a 12-hour clock without its `{a}`, and a minute or second with nothing above it,
    which is how `{mm}` written for the month shows itself."""
    if atoms & {"hh", "h"} and "a" not in atoms:
        raise ValueError(
            f"template '{source}' uses the 12-hour clock without '{{a}}', the 24-hour hour is "
            "'{HH}'"
        )

    if "mm" in atoms and not atoms & _HOURS:
        raise ValueError(
            f"template '{source}' uses '{{mm}}' without an hour, '{{mm}}' is the minute and "
            "'{MM}' the month"
        )

    if "ss" in atoms and "mm" not in atoms:
        raise ValueError(f"template '{source}' uses '{{ss}}' without '{{mm}}'")


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


# The time atoms a layout may use, each read back by `PathLayout.walk`. A capture of variable
# width cannot sit beside another, `{M}{d}` reads `111` two ways.
_LAYOUT_ATOMS: Final[Mapping[str, _Capture]] = {
    "yyyy": _Capture("year", r"\d{4}"),
    "yy": _Capture("year", r"\d{2}", lambda text: 2000 + int(text)),
    "MM": _Capture("month", r"\d{2}"),
    "M": _Capture("month", r"\d{1,2}"),
    "MMM": _names((month[:3] for month in _MONTHS), "month"),
    "MMMM": _names(_MONTHS, "month"),
    "DDD": _Capture("doy", r"\d{3}"),
    "dd": _Capture("day", r"\d{2}"),
    "d": _Capture("day", r"\d{1,2}"),
    "HH": _Capture("hour", r"\d{2}"),
    "H": _Capture("hour", r"\d{1,2}"),
    "hh": _Capture("hour12", r"\d{2}"),
    "h": _Capture("hour12", r"\d{1,2}"),
    "a": _names(("AM", "PM"), "meridiem"),
    "mm": _Capture("minute", r"\d{2}"),
    "ss": _Capture("second", r"\d{2}"),
}
_VARIABLE_WIDTH: Final = frozenset({"M", "d", "H", "h", "MMMM"})
_LAYOUT_NAMES: Final = frozenset({"component", "mount", "project", "host"})

_CALENDAR: Final = ("year", "month", "day", "hour", "minute", "second")


class PathLayout(PathTemplate):
    """A `PathTemplate` for dated folders, which `walk` reads back to find a time range.

    A layout uses calendar atoms from the year down without a gap, `{yyyy}/{MM}` or
    `{yyyy}/{DDD}`, plus `{component}`, `{mount}`, `{project}`, and `{host}`. A folder's
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

        for segment in segments:
            names = {part.name for part in segment if isinstance(part, _Atom)}
            if names & {"hh", "h"} and "a" not in names or "a" in names and not names & {"hh", "h"}:
                raise ValueError(f"layout '{source}' must keep '{{a}}' beside its 12-hour hour")

        fields = {_LAYOUT_ATOMS[name].field for name in self._atoms if name in _LAYOUT_ATOMS}
        fields = {"hour" if field == "hour12" else field for field in fields} - {"meridiem"}
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
                # On a network share every stat is a round trip, so the listing's own entry
                # types decide which entries are folders, and only those in range are asked.
                with os.scandir(folder) as listing:
                    entries = list(listing)
            except FileNotFoundError, NotADirectoryError:
                return

            found: list[tuple[tuple[int, ...], str, Path, dict[str, int]]] = []
            for entry in entries:
                match = pattern.fullmatch(entry.name)
                fields = None if match is None else _merge(known, captures, match.groups())
                if fields is None:
                    continue

                try:
                    period = _period(fields, place)
                except ValueError, OverflowError:
                    continue

                if period is not None and not (period[0] < before and period[1] > after):
                    continue

                if not entry.is_dir():
                    continue

                key = tuple(fields.get(field, 0) for field in (*_CALENDAR, "doy"))
                found.append((key, entry.name, Path(entry.path), fields))

            for _, _, path, fields in sorted(found, key=lambda item: item[:2]):
                yield from visit(path, depth + 1, fields)

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

        capture = _LAYOUT_ATOMS[part.name]
        pattern.append(f"({capture.pattern})")
        captures.append(capture)

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

    if "hour12" in fields and "meridiem" in fields:
        if not 1 <= fields["hour12"] <= 12:
            return None

        hour = fields.pop("hour12") % 12 + 12 * (fields.pop("meridiem") - 1)
        if fields.setdefault("hour", hour) != hour:
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
