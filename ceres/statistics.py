from pydantic import Field

from ceres.address import Address, AddressSelector
from ceres.data import DataObject, DateTime, PositiveTimeDelta
from ceres.filter import BaseFilter, BaseFilterArgs
from ceres.level import Level


class LevelStatistics(DataObject):
    level: Level
    count: int = Field(ge=0)


class AlertStatistics(DataObject):
    count: int = 0
    levels: list[LevelStatistics] = Field(default_factory=list)


class StatisticsFilterArgs(BaseFilterArgs, total=False):
    root: Address | None
    address: AddressSelector | None
    within: PositiveTimeDelta | None
    after: DateTime | None
    before: DateTime | None


class StatisticsFilter(BaseFilter):
    root: Address | None = None
    address: AddressSelector | None = None
    within: PositiveTimeDelta | None = None
    after: DateTime | None = None
    before: DateTime | None = None


class Statistics(DataObject):
    address: Address
    alerts: AlertStatistics = Field(default_factory=AlertStatistics)
