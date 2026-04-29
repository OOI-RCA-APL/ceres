from collections.abc import Iterable
from enum import Enum
from typing import TYPE_CHECKING, Any, Self, TypedDict

from pydantic import ConfigDict

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

        values = [_escape_like_expression(value, "^") for value in values]

        def like(current: str | bytes) -> SQLColumnExpression[bool]:
            if insensitive:
                return expression.ilike(current, escape="^")
            else:
                return expression.like(current, escape="^")

        wildcard: Any = b"%" if isinstance(values[0], bytes) else "%"

        if mode == MatchMode.EQUALS:
            if insensitive:
                return sqlorf(like(current) for current in values)
            else:
                return expression.in_(values)

        if all(value == "" or value == b"" for value in values):
            return sqlalchemy.true()

        match mode:
            case MatchMode.CONTAINS:
                return sqlorf(like(wildcard + current + wildcard) for current in values)
            case MatchMode.PREFIX:
                return sqlorf(like(current + wildcard) for current in values)
            case MatchMode.SUFFIX:
                return sqlorf(like(wildcard + current) for current in values)

        raise ValueError(f"invalid mode: {mode!r}")

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
