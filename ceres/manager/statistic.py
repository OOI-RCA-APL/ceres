from __future__ import annotations

from typing_extensions import Unpack

from ceres._internal.lazy import lazy_imports
from ceres._internal.manager.manager import BaseManager
from ceres.address import Address
from ceres.statistics import LevelStatistics, Statistics, StatisticsFilter, StatisticsFilterArgs
from ceres.timing import utc

with lazy_imports(__name__):
    from sqlalchemy import func, select

    from ceres._internal import util
    from ceres.alert import Alert
    from ceres.database.database import Database
    from ceres.node import Node


class StatisticsManager(BaseManager[Statistics]):
    def __init__(self, source: Database | Node) -> None:
        super().__init__(source, Statistics)

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
            .with_defaults(self._get_filter_defaults())
        )

        statement = select(Alert.Row.address, Alert.Row.level, func.count()).group_by(
            Alert.Row.address,
            Alert.Row.level,
        )

        if filter.within is not None:
            statement = statement.where(Alert.Row.timestamp >= utc() - filter.within)
        if filter.after is not None:
            statement = statement.where(Alert.Row.timestamp >= filter.after)
        if filter.before is not None:
            statement = statement.where(Alert.Row.timestamp < filter.before)

        results: dict[Address, Statistics] = {}

        with util.wrap_database_errors():
            async with await self._database.init() as session:
                for address, level, count in await session.execute(statement):
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

    def _get_filter_defaults(self) -> StatisticsFilter | None:
        if self._node is None:
            return None

        address = self._node.address
        return util.call_partial(
            StatisticsFilter,
            root=address,
            address=address.all(),
        )
