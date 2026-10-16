"""Split a docstring into its prose and the text it gives each parameter, the return value and the
exceptions raised.

Two styles are read, Sphinx fields (`:param name: text`) and Google sections (`Args:` followed by
indented `name: text` entries), and one docstring may mix them. Whatever is not one of those
fields stays in the prose untouched, so Markdown and any other section (`Example:`, `Note:`)
render as written. Types given in the docstring are dropped since the signature is authoritative.

The edge cases follow `docstring_parser` (MIT, https://github.com/rr-/docstring_parser), whose
Sphinx and Google parsers served as the reference for this one.
"""

import inspect
import re
import textwrap
from dataclasses import dataclass, field
from functools import lru_cache


@dataclass(frozen=True)
class DocstringRaise:
    """An exception a docstring says is raised, and when."""

    type: str | None
    """The exception's name as written, or `None` when the docstring names none."""

    description: str
    """When it is raised."""


@dataclass(frozen=True)
class Docstring:
    """A docstring split into its prose and its fields."""

    description: str | None = None
    """The summary and body, without the fields, or `None` when there is no prose."""

    params: dict[str, str] = field(default_factory=dict)
    """Text per parameter name, as named in the docstring."""

    returns: str | None = None
    """What the return value or the yielded values are."""

    raises: tuple[DocstringRaise, ...] = ()
    """The exceptions raised, in the order given."""


_PARAM_KEYS = frozenset({"param", "parameter", "arg", "argument", "key", "keyword"})
_RETURN_KEYS = frozenset({"return", "returns", "yield", "yields"})
_RAISE_KEYS = frozenset({"raise", "raises", "except", "exception"})
# Fields that carry no text worth showing but still end the previous field.
_SILENT_KEYS = frozenset({"type", "rtype", "ytype", "var", "ivar", "cvar", "vartype", "meta"})

_SPHINX_FIELD = re.compile(
    r"^:(?P<key>"
    + "|".join(sorted(_PARAM_KEYS | _RETURN_KEYS | _RAISE_KEYS | _SILENT_KEYS))
    + r")(?P<args>(?:[ \t]+[^:\n]+?)?)[ \t]*:(?:[ \t]+|$)(?P<text>.*)$"
)

_GOOGLE_SECTIONS = {
    "args": "params",
    "arguments": "params",
    "parameters": "params",
    "params": "params",
    "keyword args": "params",
    "keyword arguments": "params",
    "kwargs": "params",
    "other parameters": "params",
    "returns": "returns",
    "return": "returns",
    "yields": "returns",
    "yield": "returns",
    "raises": "raises",
    "exceptions": "raises",
    "except": "raises",
}
_GOOGLE_TITLE = re.compile(
    r"^(?P<title>" + "|".join(re.escape(title) for title in _GOOGLE_SECTIONS) + r")[ \t]*:[ \t]*$",
    re.IGNORECASE,
)
# `name: text`, `name (type): text` or `*args: text`. The name is one word, so prose holding a
# colon does not read as an entry.
_GOOGLE_PARAM = re.compile(
    r"^\*{0,2}(?P<name>\w+)[ \t]*(?:\([^)]*\))?[ \t]*:(?:[ \t]+|$)(?P<text>.*)$"
)
_GOOGLE_RAISE = re.compile(r"^(?P<type>[A-Za-z_][\w.]*)[ \t]*:(?:[ \t]+|$)(?P<text>.*)$")
# A leading `type:` on a Google return, which goes the way of every other docstring type.
_GOOGLE_RETURN_TYPE = re.compile(r"^[^\s:]+:[ \t]+")


def parse_docstring(text: str | None, /) -> Docstring:
    """Split `text` into its prose and the text it gives parameters, the return value and the
    exceptions raised. An empty or missing docstring gives an empty `Docstring`."""
    if not text:
        return Docstring()

    return _parse(text)


@lru_cache(maxsize=1024)
def _parse(text: str) -> Docstring:
    lines = inspect.cleandoc(text).splitlines()

    prose: list[str] = []
    params: dict[str, str] = {}
    returns: list[str] = []
    raises: list[DocstringRaise] = []

    index = 0
    while index < len(lines):
        line = lines[index]

        if match := _SPHINX_FIELD.match(line):
            body, index = _take_indented(lines, index + 1)
            index = _skip_blank_after(lines, index, prose)
            description = _join(match["text"], body)
            key = match["key"]
            args = match["args"].split()
            if key in _PARAM_KEYS and args:
                params.setdefault(args[-1].lstrip("*"), description)
            elif key in _RETURN_KEYS and description:
                returns.append(description)
            elif key in _RAISE_KEYS:
                raises.append(
                    DocstringRaise(type=args[-1] if args else None, description=description)
                )
            continue

        if match := _GOOGLE_TITLE.match(line):
            body, after = _take_indented(lines, index + 1)
            if any(entry.strip() for entry in body):
                kind = _GOOGLE_SECTIONS[match["title"].lower()]
                if kind == "params":
                    for name, description in _google_entries(body, _GOOGLE_PARAM, "name"):
                        params.setdefault(name, description)
                elif kind == "raises":
                    raises.extend(
                        DocstringRaise(type=name, description=description)
                        for name, description in _google_entries(body, _GOOGLE_RAISE, "type")
                    )
                else:
                    description = _join("", body)
                    description = _GOOGLE_RETURN_TYPE.sub("", description, count=1)
                    if description:
                        returns.append(description)
                index = _skip_blank_after(lines, after, prose)
                continue

        prose.append(line)
        index += 1

    description = "\n".join(prose).strip() or None
    return Docstring(
        description=description,
        params=params,
        returns="\n\n".join(returns) or None,
        raises=tuple(raises),
    )


def _take_indented(lines: list[str], start: int) -> tuple[list[str], int]:
    """The lines from `start` belonging to a field or section: blank lines and lines indented past
    column zero, up to the first unindented line. Blank lines at the end are left behind."""
    end = start
    last = start
    while end < len(lines):
        line = lines[end]
        if line.strip() == "":
            end += 1
            continue
        if not line[0].isspace():
            break
        end += 1
        last = end
    return lines[start:last], last


def _skip_blank_after(lines: list[str], index: int, prose: list[str]) -> int:
    """Past the blank lines following a field taken out of the prose, when the prose already ends
    in a blank line or has none yet, so the gap it leaves is one blank line rather than two."""
    if prose and prose[-1].strip():
        return index
    while index < len(lines) and not lines[index].strip():
        index += 1
    return index


def _join(first: str, rest: list[str]) -> str:
    """One field's text from its first line and its indented continuation, dedented."""
    continuation = textwrap.dedent("\n".join(rest)).rstrip()
    return f"{first.strip()}\n{continuation}".strip()


def _google_entries(body: list[str], pattern: re.Pattern[str], group: str) -> list[tuple[str, str]]:
    """The entries of a Google section, each starting on a line at the section's own indent and
    running on through the lines indented deeper. A line at that indent not shaped like an entry
    continues the one before it."""
    indent = min(len(line) - len(line.lstrip()) for line in body if line.strip())
    entries: list[tuple[str, str, list[str]]] = []
    index = 0
    while index < len(body):
        line = body[index]
        index += 1
        stripped = line.strip()
        if not stripped or len(line) - len(line.lstrip()) != indent:
            if entries:
                entries[-1][2].append(line)
            continue

        # A type in parentheses may wrap onto the lines below, so the entry's head runs on until
        # its parentheses close.
        head = stripped
        after = index
        while head.count("(") > head.count(")") and after < len(body):
            head += " " + body[after].strip()
            after += 1

        if match := pattern.match(head):
            entries.append((match[group], match["text"], []))
            index = after
        elif entries:
            entries[-1][2].append(line)

    return [(name, _join(first, rest)) for name, first, rest in entries]
