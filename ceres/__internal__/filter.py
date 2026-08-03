from enum import Enum
from typing import Self, TypedDict

from pydantic import ConfigDict

from ceres.__internal__.utilities.collections import seq
from ceres.data import MaybeSequence, defaulting, replacing
from ceres.data.object import DataModel


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
