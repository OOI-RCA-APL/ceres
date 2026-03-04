from collections.abc import Iterable
from enum import Enum
from typing import TYPE_CHECKING, Any, Self, TypedDict

from ceres._internal.utilities.collections import seq
from ceres.data import ImmutableDataModel, MaybeSequence, defaulting, replacing

if TYPE_CHECKING:
    from sqlalchemy import SQLColumnExpression


class MatchMode(Enum):
    EQUALS = 0
    CONTAINS = 1
    PREFIX = 2
    SUFFIX = 3


class BaseFilterArgs(TypedDict, total=False):
    pass


class BaseFilter(ImmutableDataModel):
    def with_overrides(self, overrides: Self | None) -> Self:
        return replacing(self, overrides)

    def with_defaults(self, defaults: Self | None) -> Self:
        return defaulting(self, defaults)

    @classmethod
    def _match_value[T](
        cls,
        value: T,
        possibilities: MaybeSequence[T] | None = None,
    ) -> bool:
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
        return cls._match_string(value, possibilities, MatchMode.EQUALS, insensitive=insensitive)

    @classmethod
    def _match_string_contains[T: (str, bytes)](
        cls,
        value: T | None,
        possibilities: MaybeSequence[T] | None,
        *,
        insensitive: bool = False,
    ) -> bool:
        return cls._match_string(value, possibilities, MatchMode.CONTAINS, insensitive=insensitive)

    @classmethod
    def _match_string_prefix[T: (str, bytes)](
        cls,
        value: T | None,
        possibilities: MaybeSequence[T] | None,
        *,
        insensitive: bool = False,
    ) -> bool:
        return cls._match_string(value, possibilities, MatchMode.PREFIX, insensitive=insensitive)

    @classmethod
    def _match_string_suffix[T: (str, bytes)](
        cls,
        value: T | None,
        possibilities: MaybeSequence[T] | None,
        *,
        insensitive: bool = False,
    ) -> bool:
        return cls._match_string(value, possibilities, MatchMode.SUFFIX, insensitive=insensitive)

    @classmethod
    def _sql_match_value[T](
        cls,
        expression: SQLColumnExpression[T],
        value: MaybeSequence[T],
    ) -> SQLColumnExpression[bool]:
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
        return cls._sql_match_string(expression, value, MatchMode.EQUALS, insensitive=insensitive)

    @classmethod
    def _sql_match_string_contains[T: (str, bytes)](
        cls,
        expression: SQLColumnExpression[T | None],
        value: MaybeSequence[T],
        *,
        insensitive: bool = False,
    ) -> SQLColumnExpression[bool]:
        return cls._sql_match_string(expression, value, MatchMode.CONTAINS, insensitive=insensitive)

    @classmethod
    def _sql_match_string_prefix[T: (str, bytes)](
        cls,
        expression: SQLColumnExpression[T | None],
        value: MaybeSequence[T],
        *,
        insensitive: bool = False,
    ) -> SQLColumnExpression[bool]:
        return cls._sql_match_string(expression, value, MatchMode.PREFIX, insensitive=insensitive)

    @classmethod
    def _sql_match_string_suffix[T: (str, bytes)](
        cls,
        expression: SQLColumnExpression[T | None],
        value: MaybeSequence[T],
        *,
        insensitive: bool = False,
    ) -> SQLColumnExpression[bool]:
        return cls._sql_match_string(expression, value, MatchMode.SUFFIX, insensitive=insensitive)


def sqlorf(
    *expressions: Iterable[SQLColumnExpression[bool]],
) -> SQLColumnExpression[bool]:
    from sqlalchemy import or_

    from ceres._internal.utilities.collections import flatten

    return or_(False, *flatten(expressions))


def _escape_like_expression[T: (str, bytes)](text: T, escape: str) -> T:
    if isinstance(text, bytes):
        return text.replace(b"%", escape.encode() + b"%").replace(b"_", escape.encode() + b"_")
    else:
        return text.replace("%", escape + "%").replace("_", escape + "_")
