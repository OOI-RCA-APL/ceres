from abc import ABC

from pydantic import ConfigDict
from typing_extensions import Self, TypedDict

from ceres._internal.utilities import model_apply_defaults, model_apply_overrides, model_is_empty
from ceres.data import ImmutableDataObject


class BaseFilterArgs(TypedDict, total=False):
    pass


class BaseFilter(ImmutableDataObject, ABC):
    model_config = ConfigDict(extra="ignore")

    def with_overrides(self, overrides: Self | None) -> Self:
        return model_apply_overrides(self, overrides)

    def with_defaults(self, defaults: Self | None) -> Self:
        return model_apply_defaults(self, defaults)

    def is_empty(self) -> bool:
        return model_is_empty(self)
