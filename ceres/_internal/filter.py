from __future__ import annotations

from abc import ABC
from typing import Self, TypedDict

from ceres._internal import util
from ceres.data import ImmutableDataObject


class BaseFilterArgs(TypedDict, total=False):
    pass


class BaseFilter(ImmutableDataObject, ABC):
    def with_overrides(self, overrides: Self | None) -> Self:
        return util.model_apply_overrides(self, overrides)

    def with_defaults(self, defaults: Self | None) -> Self:
        return util.model_apply_defaults(self, defaults)
