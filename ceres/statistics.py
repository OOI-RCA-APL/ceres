from typing import Any, Unpack

from pydantic import Field
from sqlalchemy import func, select

from ceres.__internal__.database.errors import wrap_database_errors
from ceres.__internal__.filter import BaseFilter, BaseFilterArgs
from ceres.__internal__.manager import BaseDatabaseManager
from ceres.__internal__.utilities.functions import call_partial
from ceres.address import Address, AddressSelector
from ceres.alert import Alert
from ceres.data import DataObject, DateTime
from ceres.level import Level

__all__ = [
    "Statistics",
]


class LevelStatistics(DataObject):
    """Per-level count of alerts rolled up under a single address."""

    level: Level
    """Severity level these statistics apply to."""
    count: int = Field(ge=0)
    """Number of alerts recorded at this level."""


class AlertStatistics(DataObject):
    """Aggregated alert counts rolled up under a single address."""

    count: int = 0
    """Total number of alerts across all levels."""
    levels: list[LevelStatistics] = Field(default_factory=list)
    """Per-level breakdown of the aggregated count, sorted by level."""


class StatisticsFilterArgs(BaseFilterArgs, total=False):
    """Keyword-argument form of `StatisticsFilter` for ergonomic call sites."""

    root: Address | None
    address: AddressSelector | None
    after: DateTime | None
    before: DateTime | None


class StatisticsFilter(BaseFilter):
    """Filter controlling which alerts contribute to `Statistics` results."""

    root: Address | None = None
    """Restrict aggregation to addresses contained within the given root address."""
    address: AddressSelector | None = None
    """Restrict returned `Statistics` to addresses matching the given selector."""
    after: DateTime | None = None
    """Include only alerts with a timestamp greater than or equal to the given time."""
    before: DateTime | None = None
    """Include only alerts with a timestamp strictly less than the given time."""


class Statistics(DataObject):
    """Aggregated counts rolled up for a single address across its subtree of descendants."""

    Filter = StatisticsFilter
    FilterArgs = StatisticsFilterArgs

    address: Address
    """Address these statistics describe."""
    alerts: AlertStatistics = Field(default_factory=AlertStatistics)
    """Alert counts aggregated for this address and its descendants."""


class StatisticsManager(BaseDatabaseManager):
    """Database-bound manager that computes aggregated `Statistics` over stored alerts."""

    async def get(
        self,
        filter: StatisticsFilter | None = None,
        /,
        *,
        relative_to: Address | None = None,
        **kwargs: Unpack[StatisticsFilterArgs],
    ) -> Statistics | None:
        """Return the first `Statistics` result matching the given filter.

        Args:
            filter: Base filter to combine with keyword arguments.
            relative_to: Address used to resolve relative `AddressSelector` patterns.
            **kwargs: Keyword-form filter arguments merged onto `filter`.

        Returns:
            The first matching `Statistics`, or `None` if none match.
        """
        results = await self.get_all(filter, relative_to=relative_to, **kwargs)
        return results[0] if results else None

    async def get_all(
        self,
        filter: StatisticsFilter | None = None,
        /,
        *,
        relative_to: Address | None = None,
        **kwargs: Unpack[StatisticsFilterArgs],
    ) -> list[Statistics]:
        """Compute `Statistics` for every address that has matching alerts.

        Alerts are grouped by source address and level, then propagated up through each
        ancestor address so that parents reflect the totals of their subtree.

        Args:
            filter: Base filter to combine with keyword arguments.
            relative_to: Address used to resolve relative `AddressSelector` patterns.
            **kwargs: Keyword-form filter arguments merged onto `filter`.

        Returns:
            A list of `Statistics`, one per address that has matching alerts, filtered by the
            configured `address` selector when provided.
        """
        filter = (
            StatisticsFilter(**kwargs)
            .with_defaults(filter)
            .with_defaults(self._construct_filter_defaults())
        )

        results: dict[Address, Statistics] = {}

        with wrap_database_errors():
            for address, level, count in await self._counts(filter):
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

    async def _counts(self, filter: StatisticsFilter) -> list[tuple[Address, Level, int]]:
        """How many alerts each address holds at each level, within the filter's window.

        The grouping is the whole query, so this is one aggregate rather than a listing the
        caller counts, and the window is the only thing narrowing it. Ancestor propagation
        happens above, on far fewer rows than the alerts themselves.
        """
        database = self.__database__
        store = database._store()
        if store is None:
            statement = select(Alert.Row.address, Alert.Row.level, func.count()).group_by(
                Alert.Row.address,
                Alert.Row.level,
            )
            if filter.after is not None:
                statement = statement.where(Alert.Row.timestamp >= filter.after)
            if filter.before is not None:
                statement = statement.where(Alert.Row.timestamp < filter.before)

            async with await database.use() as connection:
                return [
                    (address, level, count)
                    for address, level, count in await connection.execute(statement)
                ]

        await database.ready()
        postgres = database.type.value == "postgres"
        conditions: list[str] = []
        parameters: list[Any] = []
        for operator, bound in ((">=", filter.after), ("<", filter.before)):
            if bound is None:
                continue

            parameters.append(bound)
            # PostgreSQL numbers its placeholders, the SQLite family takes them in order.
            marker = f"${len(parameters)}" if postgres else "?"
            conditions.append(f'"timestamp" {operator} {marker}')

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = await store.fetch(
            f'SELECT "address", "level", COUNT(*) AS "count" FROM "alerts"{where} '
            'GROUP BY "address", "level"',
            parameters,
            "alerts",
        )
        return [(Address(row["address"]), Level(row["level"]), row["count"]) for row in rows]

    def _construct_filter_defaults(self) -> StatisticsFilter | None:
        return call_partial(StatisticsFilter, **self.__get_filter_defaults__())
