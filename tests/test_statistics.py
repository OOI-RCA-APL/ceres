"""What the alert statistics roll up, and how the time window narrows them.

The counts come back from one grouped aggregate rather than from listing alerts and
counting them here, so the grouping, the window, and the ancestor propagation on top of it
are each worth holding still.
"""

from datetime import timedelta

import pytest

from ceres.address import Address
from ceres.alert import Alert
from ceres.database import Database
from ceres.logs import Level
from ceres.timing import utc

pytestmark = pytest.mark.databases()


async def _seeded() -> Database:
    """A database holding alerts at two levels, under two addresses, an hour apart."""
    database = Database()
    await database.migrate()

    now = utc()
    for address, level, age in (
        ("@sensor.temp", Level.WARNING, timedelta(0)),
        ("@sensor.temp", Level.WARNING, timedelta(0)),
        ("@sensor.temp", Level.ERROR, timedelta(0)),
        ("@sensor.flow", Level.ERROR, timedelta(0)),
        ("@sensor.temp", Level.WARNING, timedelta(hours=2)),
    ):
        await database.alerts.create(
            Alert.Create(
                address=Address(address),
                level=level,
                type="test",
                timestamp=now - age,
            )
        )

    return database


def _for(statistics: list, address: str):
    """The one entry for `address`, which the roll-up produces at most one of."""
    return next(entry for entry in statistics if entry.address == Address(address))


async def test_counts_group_by_address_and_level() -> None:
    """Each address reports its own alerts split by level."""
    database = await _seeded()
    try:
        statistics = await database.statistics.get_all()

        temp = _for(statistics, "@sensor.temp")
        assert temp.alerts.count == 4
        assert {(entry.level, entry.count) for entry in temp.alerts.levels} == {
            (Level.WARNING, 3),
            (Level.ERROR, 1),
        }

        flow = _for(statistics, "@sensor.flow")
        assert flow.alerts.count == 1
    finally:
        await database.dispose()


async def test_an_ancestor_totals_the_subtree_below_it() -> None:
    """A parent reflects every alert under it, which is the point of the roll-up."""
    database = await _seeded()
    try:
        statistics = await database.statistics.get_all()

        sensor = _for(statistics, "@sensor")
        assert sensor.alerts.count == 5
        assert {(entry.level, entry.count) for entry in sensor.alerts.levels} == {
            (Level.WARNING, 3),
            (Level.ERROR, 2),
        }
    finally:
        await database.dispose()


async def test_the_window_excludes_alerts_outside_it() -> None:
    """`after` narrows the aggregate itself rather than the roll-up on top of it."""
    database = await _seeded()
    try:
        statistics = await database.statistics.get_all(after=utc() - timedelta(hours=1))

        temp = _for(statistics, "@sensor.temp")
        assert temp.alerts.count == 3
        assert {(entry.level, entry.count) for entry in temp.alerts.levels} == {
            (Level.WARNING, 2),
            (Level.ERROR, 1),
        }
    finally:
        await database.dispose()


async def test_a_window_holding_nothing_reports_nothing() -> None:
    """A window before every alert produces no addresses at all, not zeroed ones."""
    database = await _seeded()
    try:
        assert await database.statistics.get_all(before=utc() - timedelta(days=1)) == []
    finally:
        await database.dispose()
