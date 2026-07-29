"""Cover record subsampling, which reduces a time range to one record per bucket.

Subsampling is the only place the query layer bins timestamps, and each backend bins them its own
way, so these run against whichever backend the suite was pointed at.
"""

from datetime import datetime, timedelta

import pytest

from ceres import Address, Alert, Level
from ceres.__internal__.record import SubsampleSelect
from ceres.alert import AlertCreate
from ceres.database import Database

pytestmark = pytest.mark.databases()
"""Every backend, since each bins timestamps with its own SQL."""

ORIGIN = datetime.fromisoformat("2026-01-01T00:00:00+00:00")


async def _seed(interval: timedelta, count: int) -> Database:
    """Build a database holding `count` alerts spaced `interval` apart from `ORIGIN`."""
    database = Database()
    await database.migrate()

    for index in range(count):
        await database.alerts.create(
            AlertCreate(
                address=Address("@test"),
                level=Level.INFO,
                type=f"t{index}",
                timestamp=ORIGIN + interval * index,
            )
        )

    return database


async def test_subsample_every_keeps_one_record_per_bucket():
    """Ten records a minute apart, bucketed every five minutes, leave one per bucket."""
    database = await _seed(timedelta(minutes=1), 10)
    try:
        got = await database.alerts.where(subsample_every=timedelta(minutes=5)).all()

        assert len(got) == 2
        assert [alert.timestamp for alert in got] == sorted(alert.timestamp for alert in got)
    finally:
        await database.dispose()


async def test_subsample_every_picks_the_first_record_in_each_bucket():
    database = await _seed(timedelta(minutes=1), 10)
    try:
        got = await database.alerts.where(
            subsample_every=timedelta(minutes=5), subsample_select=SubsampleSelect.FIRST
        ).all()

        assert [alert.type for alert in got] == ["t0", "t5"]
    finally:
        await database.dispose()


async def test_subsample_every_picks_the_last_record_in_each_bucket():
    database = await _seed(timedelta(minutes=1), 10)
    try:
        got = await database.alerts.where(
            subsample_every=timedelta(minutes=5), subsample_select=SubsampleSelect.LAST
        ).all()

        assert [alert.type for alert in got] == ["t4", "t9"]
    finally:
        await database.dispose()


async def test_subsample_divides_the_range_into_a_fixed_number_of_buckets():
    """`subsample` asks for a count rather than a width, so the range decides the width."""
    database = await _seed(timedelta(minutes=1), 10)
    try:
        got = await database.alerts.where(
            after=ORIGIN,
            before=ORIGIN + timedelta(minutes=10),
            subsample=2,
        ).all()

        assert len(got) == 2
        assert [alert.type for alert in got] == ["t0", "t5"]
    finally:
        await database.dispose()


async def test_subsample_every_buckets_below_a_second():
    """Records arrive faster than once a second, so buckets have to be finer than that."""
    database = await _seed(timedelta(milliseconds=100), 10)
    try:
        got = await database.alerts.where(
            subsample_every=timedelta(milliseconds=500), subsample_select=SubsampleSelect.FIRST
        ).all()

        assert [alert.type for alert in got] == ["t0", "t5"]
    finally:
        await database.dispose()


async def test_subsample_every_buckets_down_to_a_millisecond():
    """A millisecond is as fine as bucketing goes.

    SQLite and Turso read a timestamp's fraction to milliseconds and no further, so a bucket
    narrower than that cannot separate two records inside the same millisecond. PostgreSQL keeps
    microseconds, and this pins the coarser of the two so a change in either is noticed.
    """
    database = await _seed(timedelta(milliseconds=1), 10)
    try:
        got = await database.alerts.where(
            subsample_every=timedelta(milliseconds=5), subsample_select=SubsampleSelect.FIRST
        ).all()

        assert [alert.type for alert in got] == ["t0", "t5"]
    finally:
        await database.dispose()


async def test_subsampling_leaves_a_short_range_alone():
    """Fewer records than buckets means every record survives."""
    database = await _seed(timedelta(minutes=1), 3)
    try:
        got = await database.alerts.where(subsample_every=timedelta(minutes=5)).all()

        assert len(got) == 1
        assert got[0].type == "t0"
    finally:
        await database.dispose()


async def test_subsampling_narrows_to_the_filtered_range():
    """Records outside the time bounds are gone before any bucketing happens."""
    database = await _seed(timedelta(minutes=1), 10)
    try:
        got = await database.alerts.where(
            after=ORIGIN + timedelta(minutes=5),
            subsample_every=timedelta(minutes=5),
        ).all()

        assert all(alert.timestamp >= ORIGIN + timedelta(minutes=5) for alert in got)
        assert got
    finally:
        await database.dispose()


async def test_subsampling_returns_whole_records():
    """The bucketing is a filter, not a projection, so a full record comes back."""
    database = await _seed(timedelta(minutes=1), 10)
    try:
        got = await database.alerts.where(subsample_every=timedelta(minutes=5)).all()

        assert got
        for alert in got:
            assert isinstance(alert, Alert)
            assert str(alert.address) == "@test"
            assert alert.level is Level.INFO
    finally:
        await database.dispose()
