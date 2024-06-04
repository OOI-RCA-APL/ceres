from __future__ import annotations

from abc import ABC

from pydantic import ConfigDict
from typing_extensions import Self, TypedDict

from ceres._internal.lazy import lazy_imports
from ceres.data import ImmutableDataObject

with lazy_imports(__name__):
    from ceres._internal import util


class BaseFilterArgs(TypedDict, total=False):
    pass


class BaseFilter(ImmutableDataObject, ABC):
    model_config = ConfigDict(extra="ignore")

    def with_overrides(self, overrides: Self | None) -> Self:
        return util.model_apply_overrides(self, overrides)

    def with_defaults(self, defaults: Self | None) -> Self:
        return util.model_apply_defaults(self, defaults)

    def is_empty(self) -> bool:
        return util.model_is_empty(self)
