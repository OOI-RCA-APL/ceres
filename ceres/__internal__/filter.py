from typing import Self, TypedDict

from pydantic import ConfigDict

from ceres.data import defaulting, replace
from ceres.data.object import DataModel


class BaseFilterArgs(TypedDict, total=False):
    """Base TypedDict for keyword arguments accepted by filter constructors."""

    pass


class BaseFilter(DataModel):
    """Immutable base class for all filter models."""

    model_config = ConfigDict(frozen=True)

    def with_overrides(self, overrides: Self | None) -> Self:
        """Return a copy of this filter with fields from `overrides` replacing set fields.

        Args:
            overrides: Filter whose explicitly-set fields take priority over this one's, or
                ``None`` to return this filter unchanged.

        Returns:
            A new filter with merged field values.
        """
        return replace(self, overrides)

    def with_defaults(self, defaults: Self | None) -> Self:
        """Return a copy of this filter, filling unset fields from `defaults`.

        Args:
            defaults: Filter whose explicitly-set fields fill in for unset fields in this
                filter, or ``None`` to return this filter unchanged.

        Returns:
            A new filter with merged field values.
        """
        return defaulting(self, defaults)
