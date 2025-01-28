from __future__ import annotations

from pydantic import Field

from ceres._internal.filter import BaseFilter, BaseFilterArgs
from ceres.address import Address, AddressSelector
from ceres.data import DataObject, DateTime, DeferBuild
from ceres.level import Level


class __BaseStatisticsObject(DataObject, DeferBuild):
    pass


class LevelStatistics(__BaseStatisticsObject):
    level: Level
    count: int = Field(ge=0)


class AlertStatistics(__BaseStatisticsObject):
    count: int = 0
    levels: list[LevelStatistics] = Field(default_factory=list)


class StatisticsFilterArgs(BaseFilterArgs, total=False):
    root: Address | None
    address: AddressSelector | None
    after: DateTime | None
    before: DateTime | None


class StatisticsFilter(BaseFilter, __BaseStatisticsObject):
    root: Address | None = None
    address: AddressSelector | None = None
    after: DateTime | None = None
    before: DateTime | None = None


class Statistics(__BaseStatisticsObject):
    address: Address
    alerts: AlertStatistics = Field(default_factory=AlertStatistics)
