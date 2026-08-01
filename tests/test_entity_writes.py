"""What a manager's update and delete do to the rows they touch.

These run against every backend because the statement is compiled natively and its values are
encoded per backend, so a column that stores one way under SQLite and another under PostgreSQL
has to come back the same either way.
"""

import pytest

from ceres.address import Address
from ceres.database import Database
from ceres.message import Message, MessageDirection
from ceres.variable import Variable

pytestmark = pytest.mark.databases()


async def _database() -> Database:
    database = Database()
    await database.migrate()
    return database


async def test_updating_a_binary_column_keeps_every_byte() -> None:
    """Bytes that are not text survive an update unchanged.

    The compiler is handed its values as JSON, which carries no byte string of its own, so a
    payload holding a null, a high byte, and an invalid UTF-8 sequence is the one that catches
    an encoding that only round-trips printable text.
    """
    database = await _database()
    try:
        created = await database.messages.create(
            Message.Create(
                address=Address("@sensor.temp"),
                direction=MessageDirection.RECEIVE,
                data=b"\x00A\xff",
            )
        )

        assert (
            await database.messages.where(id=created.id).update({"data": b"\xff\xfe\x00\x7f"}) == 1
        )

        again = await database.messages.get(created.id)
        assert again is not None
        assert again.data == b"\xff\xfe\x00\x7f"
    finally:
        await database.dispose()


async def test_an_update_reports_only_the_rows_its_filter_matched() -> None:
    """The count is the rows the filter narrowed to, not every row in the table."""
    database = await _database()
    try:
        for name in ("first", "second", "third"):
            await database.variables.create(
                Variable.Create(address=Address("@sensor"), name=name, value=0)
            )

        assert await database.variables.where(name="second").update({"value": 42}) == 1

        second = await database.variables.where(name="second").first()
        assert second is not None and second.value == 42

        first = await database.variables.where(name="first").first()
        assert first is not None and first.value == 0
    finally:
        await database.dispose()


async def test_a_delete_removes_only_what_its_filter_matched() -> None:
    """The rows the filter passed over are still there afterwards."""
    database = await _database()
    try:
        for name in ("first", "second", "third"):
            await database.variables.create(
                Variable.Create(address=Address("@sensor"), name=name, value=0)
            )

        assert await database.variables.where(name="second").delete() == 1

        assert await database.variables.where(name="second").any() is False
        assert await database.variables.where(address=Address("@sensor")).count() == 2
    finally:
        await database.dispose()


async def test_a_paged_write_touches_only_its_page() -> None:
    """A limit on a write narrows it through the ordered page its filter names."""
    database = await _database()
    try:
        for name in ("first", "second", "third"):
            await database.variables.create(
                Variable.Create(address=Address("@sensor"), name=name, value=0)
            )

        assert await database.variables.where(address=Address("@sensor")).limit(2).delete() == 2
        assert await database.variables.where(address=Address("@sensor")).count() == 1
    finally:
        await database.dispose()
