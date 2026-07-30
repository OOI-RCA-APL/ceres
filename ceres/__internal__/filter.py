from collections.abc import Iterable
from enum import Enum
from typing import TYPE_CHECKING, Any, Self, TypedDict

from pydantic import ConfigDict
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.expression import ColumnElement

from ceres.__internal__.utilities.collections import seq
from ceres.data import MaybeSequence, defaulting, replacing
from ceres.data.object import DataModel

if TYPE_CHECKING:
    from sqlalchemy import SQLColumnExpression


class MatchMode(Enum):
    """Enumerate the supported string matching strategies for filter comparisons."""

    EQUALS = 0
    CONTAINS = 1
    PREFIX = 2
    SUFFIX = 3


class BaseFilterArgs(TypedDict, total=False):
    """Base TypedDict for keyword arguments accepted by filter constructors."""

    pass


class BaseFilter(DataModel):
    """Immutable base class for all filter models, providing value and string matching helpers."""

    model_config = ConfigDict(frozen=True)

    def with_overrides(self, overrides: Self | None) -> Self:
        """Return a copy of this filter with fields from `overrides` replacing set fields.

        Args:
            overrides: Filter whose explicitly-set fields take priority over this one's, or
                ``None`` to return this filter unchanged.

        Returns:
            A new filter with merged field values.
        """
        return replacing(self, overrides)

    def with_defaults(self, defaults: Self | None) -> Self:
        """Return a copy of this filter, filling unset fields from `defaults`.

        Args:
            defaults: Filter whose explicitly-set fields fill in for unset fields in this
                filter, or ``None`` to return this filter unchanged.

        Returns:
            A new filter with merged field values.
        """
        return defaulting(self, defaults)

    @classmethod
    def _match_value[T](
        cls,
        value: T,
        possibilities: MaybeSequence[T] | None = None,
    ) -> bool:
        """Check whether `value` is present in `possibilities`.

        Args:
            value: The value to test.
            possibilities: One or more allowed values, or ``None`` to match unconditionally.

        Returns:
            ``True`` if `possibilities` is ``None`` or `value` appears in the sequence.
        """
        if possibilities is None:
            return True

        return value in seq(possibilities)

    @classmethod
    def _match_string[T: (str, bytes)](
        cls,
        value: T | None,
        possibilities: MaybeSequence[T] | None,
        mode: MatchMode,
        *,
        insensitive: bool = False,
    ) -> bool:
        """Check whether `value` matches any of `possibilities` using the given match mode.

        Args:
            value: The string or bytes value to test, or ``None``.
            possibilities: One or more patterns to match against, or ``None`` to match
                unconditionally.
            mode: The matching strategy (equals, contains, prefix, or suffix).
            insensitive: Perform case-insensitive comparison when ``True``.

        Returns:
            ``True`` if `possibilities` is ``None`` or `value` matches at least one pattern.

        Raises:
            ValueError: If `mode` is not a recognized ``MatchMode``.
        """
        if possibilities is None:
            return True

        if value is None:
            return False

        possibilities = seq(possibilities)
        if not possibilities:
            return False

        if insensitive:
            value = value.lower()
            possibilities = [current.lower() for current in possibilities]

        match mode:
            case MatchMode.EQUALS:
                return value in possibilities
            case MatchMode.CONTAINS:
                return any(current in value for current in possibilities)
            case MatchMode.PREFIX:
                return any(value.startswith(current) for current in possibilities)
            case MatchMode.SUFFIX:
                return any(value.endswith(current) for current in possibilities)

        raise ValueError(f"invalid mode: {mode!r}")

    @classmethod
    def _match_string_equals[T: (str, bytes)](
        cls,
        value: T | None,
        possibilities: MaybeSequence[T] | None,
        *,
        insensitive: bool = False,
    ) -> bool:
        """Match `value` against `possibilities` using exact equality."""
        return cls._match_string(value, possibilities, MatchMode.EQUALS, insensitive=insensitive)

    @classmethod
    def _match_string_contains[T: (str, bytes)](
        cls,
        value: T | None,
        possibilities: MaybeSequence[T] | None,
        *,
        insensitive: bool = False,
    ) -> bool:
        """Match `value` against `possibilities` using substring containment."""
        return cls._match_string(value, possibilities, MatchMode.CONTAINS, insensitive=insensitive)

    @classmethod
    def _match_string_prefix[T: (str, bytes)](
        cls,
        value: T | None,
        possibilities: MaybeSequence[T] | None,
        *,
        insensitive: bool = False,
    ) -> bool:
        """Match `value` against `possibilities` using prefix comparison."""
        return cls._match_string(value, possibilities, MatchMode.PREFIX, insensitive=insensitive)

    @classmethod
    def _match_string_suffix[T: (str, bytes)](
        cls,
        value: T | None,
        possibilities: MaybeSequence[T] | None,
        *,
        insensitive: bool = False,
    ) -> bool:
        """Match `value` against `possibilities` using suffix comparison."""
        return cls._match_string(value, possibilities, MatchMode.SUFFIX, insensitive=insensitive)

    @classmethod
    def _sql_match_value[T](
        cls,
        expression: SQLColumnExpression[T],
        value: MaybeSequence[T],
    ) -> SQLColumnExpression[bool]:
        """Build a SQL ``IN`` clause that matches `expression` against `value`.

        Args:
            expression: A SQLAlchemy column expression to compare.
            value: One or more values to include in the ``IN`` clause.

        Returns:
            A boolean SQL expression suitable for use in a ``WHERE`` clause.
        """
        return expression.in_(seq(value))

    @classmethod
    def _sql_match_string[T: (str, bytes)](
        cls,
        expression: SQLColumnExpression[T | None],
        value: MaybeSequence[T],
        mode: MatchMode,
        *,
        insensitive: bool = False,
    ) -> SQLColumnExpression[bool]:
        """Build a SQL expression that matches `expression` against string patterns.

        Escape ``%`` and ``_`` wildcards in the provided values so they are treated as
        literals when used in ``LIKE`` / ``ILIKE`` clauses.

        Args:
            expression: A SQLAlchemy column expression representing the column to compare.
            value: One or more string or bytes patterns to match against.
            mode: The matching strategy (equals, contains, prefix, or suffix).
            insensitive: Use ``ILIKE`` instead of ``LIKE`` when ``True``.

        Returns:
            A boolean SQL expression suitable for use in a ``WHERE`` clause.

        Raises:
            ValueError: If `mode` is not a recognized ``MatchMode``.
        """
        import sqlalchemy

        values = seq(value)
        if not values:
            return sqlalchemy.false()

        if mode == MatchMode.EQUALS and not insensitive:
            return expression.in_(values)

        def match(current: Any) -> SQLColumnExpression[bool]:
            if insensitive:
                escaped = _escape_like_expression(current, "^")
                pattern = _with_wildcards(escaped, mode, "%")
                return expression.ilike(pattern, escape="^")

            # A case-sensitive match cannot be written here, because how it is written depends on
            # the backend it lands on. `_CaseSensitiveMatch` carries the raw value and decides at
            # compile time, when the dialect is known.
            return _CaseSensitiveMatch(expression, current, mode)

        if mode == MatchMode.EQUALS:
            return sqlorf(match(current) for current in values)

        if all(value == "" or value == b"" for value in values):
            return sqlalchemy.true()

        return sqlorf(match(current) for current in values)

    @classmethod
    def _sql_match_bytes(
        cls,
        expression: SQLColumnExpression[Any],
        value: MaybeSequence[bytes],
        mode: MatchMode,
    ) -> SQLColumnExpression[bool]:
        """Build a SQL expression matching a binary column against byte patterns.

        Matching is on whole bytes, so a pattern is only found where a byte begins.

        Args:
            expression: A column expression holding the bytes to search.
            value: One or more byte patterns to match against.
            mode: The matching strategy (equals, contains, prefix, or suffix).

        Returns:
            A boolean SQL expression suitable for use in a ``WHERE`` clause.
        """
        import sqlalchemy

        values = seq(value)
        if not values:
            return sqlalchemy.false()

        def match(current: bytes) -> SQLColumnExpression[bool]:
            # Every value contains, starts with, and ends with nothing, so an empty pattern matches
            # everything. Searching for empty bytes would instead find nothing.
            if current == b"" and mode != MatchMode.EQUALS:
                return sqlalchemy.true()

            return _BytesMatch(expression, current, mode)

        return sqlorf(match(current) for current in values)

    @classmethod
    def _sql_match_bytes_contains(
        cls,
        expression: SQLColumnExpression[Any],
        value: MaybeSequence[bytes],
    ) -> SQLColumnExpression[bool]:
        """Match a binary column against byte patterns appearing anywhere in it."""
        return cls._sql_match_bytes(expression, value, MatchMode.CONTAINS)

    @classmethod
    def _sql_match_bytes_prefix(
        cls,
        expression: SQLColumnExpression[Any],
        value: MaybeSequence[bytes],
    ) -> SQLColumnExpression[bool]:
        """Match a binary column against byte patterns it starts with."""
        return cls._sql_match_bytes(expression, value, MatchMode.PREFIX)

    @classmethod
    def _sql_match_bytes_suffix(
        cls,
        expression: SQLColumnExpression[Any],
        value: MaybeSequence[bytes],
    ) -> SQLColumnExpression[bool]:
        """Match a binary column against byte patterns it ends with."""
        return cls._sql_match_bytes(expression, value, MatchMode.SUFFIX)

    @classmethod
    def _sql_match_string_equals[T: (str, bytes)](
        cls,
        expression: SQLColumnExpression[T | None],
        value: MaybeSequence[T],
        *,
        insensitive: bool = False,
    ) -> SQLColumnExpression[bool]:
        """Build a SQL expression that matches `expression` using exact equality."""
        return cls._sql_match_string(expression, value, MatchMode.EQUALS, insensitive=insensitive)

    @classmethod
    def _sql_match_string_contains[T: (str, bytes)](
        cls,
        expression: SQLColumnExpression[T | None],
        value: MaybeSequence[T],
        *,
        insensitive: bool = False,
    ) -> SQLColumnExpression[bool]:
        """Build a SQL expression that matches `expression` using substring containment."""
        return cls._sql_match_string(expression, value, MatchMode.CONTAINS, insensitive=insensitive)

    @classmethod
    def _sql_match_string_prefix[T: (str, bytes)](
        cls,
        expression: SQLColumnExpression[T | None],
        value: MaybeSequence[T],
        *,
        insensitive: bool = False,
    ) -> SQLColumnExpression[bool]:
        """Build a SQL expression that matches `expression` using prefix comparison."""
        return cls._sql_match_string(expression, value, MatchMode.PREFIX, insensitive=insensitive)

    @classmethod
    def _sql_match_string_suffix[T: (str, bytes)](
        cls,
        expression: SQLColumnExpression[T | None],
        value: MaybeSequence[T],
        *,
        insensitive: bool = False,
    ) -> SQLColumnExpression[bool]:
        """Build a SQL expression that matches `expression` using suffix comparison."""
        return cls._sql_match_string(expression, value, MatchMode.SUFFIX, insensitive=insensitive)


def sqlorf(
    *expressions: Iterable[SQLColumnExpression[bool]],
) -> SQLColumnExpression[bool]:
    """Combine multiple iterables of SQL boolean expressions with ``OR``.

    Unlike ``sqlalchemy.or_``, this function accepts iterables of expressions and flattens
    them before combining. A literal ``False`` seed ensures the result is valid even when no
    expressions are provided.

    Args:
        *expressions: Iterables of SQLAlchemy boolean column expressions.

    Returns:
        A single SQL ``OR`` expression over all provided clauses.
    """
    from sqlalchemy import or_

    from ceres.__internal__.utilities.collections import flatten

    return or_(False, *flatten(expressions))


class _BytesMatch(ColumnElement[bool]):
    """A substring match against a binary column, written differently depending on the backend.

    PostgreSQL searches the hex rendering of the bytes, because that is what its trigram index is
    built over and a `bytea` comparison could not use it. The SQLite family has no trigram index,
    so its search is a scan whichever way it is written, and comparing the bytes directly is both
    exact and free of the function PostgreSQL needs, which Turso cannot register at all.
    """

    inherit_cache = True

    def __init__(
        self,
        column: SQLColumnExpression[Any],
        value: bytes,
        mode: MatchMode,
    ) -> None:
        self.column = column
        self.value = value
        self.mode = mode


@compiles(_BytesMatch)
def _compile_bytes_match(element: _BytesMatch, compiler: Any, **kw: Any) -> str:
    from sqlalchemy import func, literal

    from ceres.__internal__.database.bytes import tokenize_bytes

    tokens = func.ceres_tokenize_bytes(element.column)
    escaped = _escape_like_expression(tokenize_bytes(element.value), "^")
    pattern = _with_wildcards(escaped, element.mode, "%")
    return compiler.process(tokens.like(literal(pattern), escape="^"), **kw)


@compiles(_BytesMatch, "sqlite")
def _compile_bytes_match_sqlite(element: _BytesMatch, compiler: Any, **kw: Any) -> str:
    from sqlalchemy import func, literal

    # "instr" over two blobs compares whole bytes, so a needle can only be found where a byte
    # actually starts. Searching hex text instead would report a match straddling two bytes.
    needle = literal(element.value)
    size = len(element.value)

    match element.mode:
        case MatchMode.EQUALS:
            expression = element.column == needle
        case MatchMode.CONTAINS:
            expression = func.instr(element.column, needle) > 0
        case MatchMode.PREFIX:
            expression = func.substr(element.column, 1, size) == needle
        case MatchMode.SUFFIX:
            expression = func.substr(element.column, -size) == needle
        case _:
            raise ValueError(f"invalid mode: {element.mode!r}")

    return compiler.process(expression, **kw)


def _with_wildcards[T: (str, bytes)](text: T, mode: MatchMode, wildcard: str) -> T:
    """Wrap `text` in the wildcards `mode` calls for.

    Args:
        text: The already-escaped pattern body.
        mode: The matching strategy the wildcards express.
        wildcard: The backend's "any sequence" character, `%` for `LIKE` and `*` for `GLOB`.

    Returns:
        The pattern to match against.

    Raises:
        ValueError: If `mode` is not a recognized `MatchMode`.
    """
    any: Any = wildcard.encode() if isinstance(text, bytes) else wildcard

    match mode:
        case MatchMode.EQUALS:
            return text
        case MatchMode.CONTAINS:
            return any + text + any
        case MatchMode.PREFIX:
            return text + any
        case MatchMode.SUFFIX:
            return any + text

    raise ValueError(f"invalid mode: {mode!r}")


class _CaseSensitiveMatch(ColumnElement[bool]):
    """A case-sensitive string match, written differently depending on the backend.

    PostgreSQL's `LIKE` already compares case, so it gets one. SQLite's does not: it folds ASCII
    case unless `PRAGMA case_sensitive_like` is on, and that PRAGMA is deprecated in SQLite and
    unimplemented in Turso, which accepts it and ignores it. `GLOB` compares case by definition on
    both, so the SQLite family gets that instead.

    The pattern cannot be built before the backend is known, because the two escape different
    characters and spell their wildcards differently, so this carries the raw value and builds the
    pattern while compiling.
    """

    inherit_cache = True

    def __init__(
        self,
        column: SQLColumnExpression[Any],
        value: Any,
        mode: MatchMode,
    ) -> None:
        self.column = column
        self.value: Any = value
        self.mode = mode


@compiles(_CaseSensitiveMatch)
def _compile_case_sensitive_match(element: _CaseSensitiveMatch, compiler: Any, **kw: Any) -> str:
    from sqlalchemy import literal

    escaped = _escape_like_expression(element.value, "^")
    pattern = _with_wildcards(escaped, element.mode, "%")
    return compiler.process(element.column.like(literal(pattern), escape="^"), **kw)


@compiles(_CaseSensitiveMatch, "sqlite")
def _compile_case_sensitive_match_sqlite(
    element: _CaseSensitiveMatch, compiler: Any, **kw: Any
) -> str:
    from sqlalchemy import literal

    escaped = _escape_glob_expression(element.value)
    pattern = _with_wildcards(escaped, element.mode, "*")
    return compiler.process(element.column.op("GLOB")(literal(pattern)), **kw)


class _SelectorMatch(ColumnElement[bool]):
    """One address selector segment's modifier condition, written per backend.

    SQLite's `LIKE` folds ASCII case while the in-memory selector comparison does not,
    so the SQLite family matches with `GLOB`, which compares case by definition and is
    how the case-sensitive string matches are written too. PostgreSQL's `LIKE` already
    compares case, so it gets an escaped `LIKE`, protecting the `_` a component name
    can contain.
    """

    inherit_cache = True

    def __init__(
        self,
        column: SQLColumnExpression[Any],
        base: str,
        modifier: str,
    ) -> None:
        self.column = column
        self.base = base
        self.modifier = modifier


@compiles(_SelectorMatch)
def _compile_selector_match(element: _SelectorMatch, compiler: Any, **kw: Any) -> str:
    from sqlalchemy import literal, not_

    escaped = _escape_like_expression(element.base, "^")

    def like(pattern: str) -> ColumnElement[bool]:
        return element.column.like(literal(pattern), escape="^")

    match element.modifier:
        case "all":
            expression = (element.column == element.base) | like(f"{escaped}.%")
        case "descendants":
            expression = like(f"{escaped}.%")
        case "children":
            expression = like(f"{escaped}.%") & not_(like(f"{escaped}.%.%"))
        case _:
            raise ValueError(f"invalid modifier: {element.modifier!r}")

    return compiler.process(expression, **kw)


@compiles(_SelectorMatch, "sqlite")
def _compile_selector_match_sqlite(element: _SelectorMatch, compiler: Any, **kw: Any) -> str:
    from sqlalchemy import literal, not_

    escaped = _escape_glob_expression(element.base)

    def glob(pattern: str) -> ColumnElement[bool]:
        return element.column.op("GLOB")(literal(pattern))

    match element.modifier:
        case "all":
            expression = (element.column == element.base) | glob(f"{escaped}.*")
        case "descendants":
            expression = glob(f"{escaped}.*")
        case "children":
            expression = glob(f"{escaped}.*") & not_(glob(f"{escaped}.*.*"))
        case _:
            raise ValueError(f"invalid modifier: {element.modifier!r}")

    return compiler.process(expression, **kw)


def _escape_glob_expression[T: (str, bytes)](text: T) -> T:
    """Escape the characters `GLOB` treats as wildcards, so `text` matches literally.

    `GLOB` has no `ESCAPE` clause. A metacharacter is made literal by wrapping it in a character
    class instead, so `*` becomes `[*]`. Only `*`, `?`, and `[` need it, because `]` outside a
    class is already literal.

    Args:
        text: The string or bytes value to escape.

    Returns:
        A copy of `text` that `GLOB` matches literally.
    """
    if isinstance(text, bytes):
        for character in (b"[", b"*", b"?"):
            text = text.replace(character, b"[" + character + b"]")

        return text

    for character in ("[", "*", "?"):
        text = text.replace(character, "[" + character + "]")

    return text


def _escape_like_expression[T: (str, bytes)](text: T, escape: str) -> T:
    """Escape SQL ``LIKE`` wildcard characters (``%`` and ``_``) in `text`.

    Args:
        text: The string or bytes value to escape.
        escape: The escape character to prepend to each wildcard.

    Returns:
        A copy of `text` with ``%`` and ``_`` escaped.
    """
    if isinstance(text, bytes):
        return text.replace(b"%", escape.encode() + b"%").replace(b"_", escape.encode() + b"_")
    else:
        return text.replace("%", escape + "%").replace("_", escape + "_")
