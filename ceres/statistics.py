from __future__ import annotations

from typing import Unpack

from pydantic import Field
from sqlalchemy import func, select

from ceres._internal import util
from ceres._internal.filter import BaseFilter, BaseFilterArgs
from ceres._internal.manager import BaseDatabaseManager
from ceres.address import Address, AddressSelector
from ceres.alert import Alert
from ceres.data import DataModel, DateTime
from ceres.level import Level


class __BaseStatisticsObject(DataModel):
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


class StatisticsManager(BaseDatabaseManager):
    async def get(
        self,
        filter: StatisticsFilter | None = None,
        /,
        *,
        relative_to: Address = Address.root(),
        **kwargs: Unpack[StatisticsFilterArgs],
    ) -> Statistics | None:
        results = await self.get_all(filter, relative_to=relative_to, **kwargs)
        return results[0] if results else None

    async def get_all(
        self,
        filter: StatisticsFilter | None = None,
        /,
        *,
        relative_to: Address = Address.root(),
        **kwargs: Unpack[StatisticsFilterArgs],
    ) -> list[Statistics]:
        filter = (
            StatisticsFilter(**kwargs)
            .with_defaults(filter)
            .with_defaults(self._construct_filter_defaults())
        )

        statement = select(Alert.Row.address, Alert.Row.level, func.count()).group_by(
            Alert.Row.address,
            Alert.Row.level,
        )

        if filter.after is not None:
            statement = statement.where(Alert.Row.timestamp >= filter.after)
        if filter.before is not None:
            statement = statement.where(Alert.Row.timestamp < filter.before)

        results: dict[Address, Statistics] = {}

        with util.wrap_database_errors():
            async with await self.__database__.use() as connection:
                for address, level, count in await connection.execute(statement):
                    address: Address
                    for ancestor in address.path:
                        if filter.root is not None:
                            if not filter.root.contains(ancestor):
                                continue

                        current = results.setdefault(ancestor, Statistics(address=ancestor))
                        current.alerts.count += count
                        for entry in current.alerts.levels:
                            if entry.level == level:
                                entry.count += count
                                break
                        else:
                            current.alerts.levels.append(LevelStatistics(level=level, count=count))
                            current.alerts.levels.sort(key=lambda entry: entry.level)

        return list(
            result
            for result in results.values()
            if filter.address is None or filter.address.matches(result.address, relative_to)
        )

    def _construct_filter_defaults(self) -> StatisticsFilter | None:
        return util.call_partial(StatisticsFilter, **self.__get_filter_defaults__())
