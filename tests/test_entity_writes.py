"""What a manager's update and delete do to the rows they touch.

These run against every backend because the statement is compiled natively and its values are
encoded per backend, so a column that stores one way under SQLite and another under PostgreSQL
has to come back the same either way.
"""

import pytest

from ceres.address import Address
from ceres.alert import Alert
from ceres.database import Database
from ceres.level import Level
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


async def test_a_document_column_stores_a_null_as_a_value() -> None:
    """A variable holding `None` holds the JSON null, not an empty column.

    The column is not nullable, so writing SQL NULL would be refused outright. It is the
    one place a null means a value rather than the absence of one, and it has to read back
    as `None` rather than as the string "null".
    """
    database = await _database()
    try:
        created = await database.variables.create(
            Variable.Create(address=Address("@sensor"), name="reading", value=None)
        )
        assert created.value is None

        stored = await database.variables.where(address=Address("@sensor"), name="reading").first()
        assert stored is not None and stored.value is None

        # And the same on the way through an update, which encodes by the same rule.
        assert await database.variables.where(name="reading").update({"value": 1}) == 1
        assert await database.variables.where(name="reading").update({"value": None}) == 1

        cleared = await database.variables.where(name="reading").first()
        assert cleared is not None and cleared.value is None
    finally:
        await database.dispose()


async def test_a_document_column_keeps_the_key_order_it_was_given() -> None:
    """A stored document reads back as the text it was written as.

    PostgreSQL's `json` keeps what it was given while its `jsonb` normalizes, sorting keys
    on the way in. `data_contains` matches against that stored text, so a document written
    as `jsonb` would be searched in an order nobody wrote, and a substring spanning two
    keys would miss the very row that had just been stored.
    """
    database = await _database()
    try:
        # `jsonb` would sort these the other way round, "name" being the shorter key.
        data = {"number": 123, "name": "abc"}
        created = await database.alerts.create(
            Alert.Create(address=Address("@sensor"), level=Level.INFO, type="ordered", data=data)
        )
        assert list(created.data) == ["number", "name"]

        found = await database.alerts.where(data_contains='"number"').all()
        assert [alert.id for alert in found] == [created.id]
        assert list(found[0].data) == ["number", "name"]
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
