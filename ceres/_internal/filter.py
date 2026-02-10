from __future__ import annotations

from typing import Self, TypedDict

from ceres.data import ImmutableDataModel, defaulting, replacing


class BaseFilterArgs(TypedDict, total=False):
    pass


class BaseFilter(ImmutableDataModel):
    def with_overrides(self, overrides: Self | None) -> Self:
        return replacing(self, overrides)

    def with_defaults(self, defaults: Self | None) -> Self:
        return defaulting(self, defaults)
