"""Paging a subtree listing, which the store answers as one seek per branch.

A `:all` selector compiles to a range on the address, which finds its rows but returns them
ordered by address rather than by the sort column. The store rewrites such a listing into one
ordered, limited seek per discovered branch, and these hold that rewrite to the rows the plain
statement returns. Every assertion runs against whichever backend `--database` selects, the
rewrite reaching PostgreSQL, SQLite, and turso alike.
"""

from datetime import datetime, timedelta
from typing import Any

from ceres import LogEntry
from ceres.database import Database
from tests.testing import arbitrary

_BASE = datetime(2026, 8, 21, 12, 0, 0)

_ADDRESSES = [
    "@abc",
    "@abc.cde",
    "@abc.cde.efg",
    "@abc.fgh",
    "@cde",
    "~",
]


async def _written() -> tuple[Any, list[LogEntry]]:
    """Write one entry per address, each a second apart, newest address last.

    Returns the manager and the entries in ascending timestamp order.
    """
    database = Database()
    await database.migrate()
    manager = LogEntry.Manager(database)
    await manager.where().delete()

    written: list[LogEntry] = []
    for index, address in enumerate(_ADDRESSES):
        for entity in await arbitrary(
            LogEntry,
            {
                "address": address,
                "timestamp": (_BASE + timedelta(seconds=index)).isoformat(),
            },
        ):
            if isinstance(entity, LogEntry):
                await manager._insert(entity)
                written.append(entity)

    return manager, written


def _under(written: list[LogEntry], selected: list[str]) -> list[LogEntry]:
    """The written entries at these addresses, newest first."""
    matching = [entry for entry in written if str(entry.address) in selected]
    matching.sort(key=lambda entry: entry.timestamp, reverse=True)
    return matching


async def test_a_subtree_page_matches_the_rows_the_addresses_hold():
    manager, written = await _written()
    expected = _under(written, ["@abc", "@abc.cde", "@abc.cde.efg", "@abc.fgh"])

    found = await manager.where(address="@abc:all", order="timestamp:desc", limit=10)

    assert [str(entry.address) for entry in found] == [str(entry.address) for entry in expected]


async def test_a_subtree_page_stops_at_its_limit():
    manager, written = await _written()
    expected = _under(written, ["@abc", "@abc.cde", "@abc.cde.efg", "@abc.fgh"])[:2]

    found = await manager.where(address="@abc:all", order="timestamp:desc", limit=2)

    assert [str(entry.address) for entry in found] == [str(entry.address) for entry in expected]


async def test_every_page_of_a_subtree_is_reachable():
    """The per-branch limit has to cover the offset as well as the page.

    Limiting each branch to the page size alone drops rows from every page but the first, and it
    does so silently, the merged page simply coming back short of rows that exist.
    """
    manager, written = await _written()
    ordered = _under(written, ["@abc", "@abc.cde", "@abc.cde.efg", "@abc.fgh"])

    paged: list[str] = []
    for offset in range(0, len(ordered), 2):
        page = await manager.where(
            address="@abc:all", order="timestamp:desc", limit=2, offset=offset
        )
        paged.extend(str(entry.address) for entry in page)

    assert paged == [str(entry.address) for entry in ordered]


async def test_ascending_order_pages_the_same_way():
    manager, written = await _written()
    ordered = list(reversed(_under(written, ["@abc", "@abc.cde", "@abc.cde.efg", "@abc.fgh"])))

    found = await manager.where(address="@abc:all", order="timestamp:asc", limit=3)

    assert [str(entry.address) for entry in found] == [str(entry.address) for entry in ordered[:3]]


async def test_a_descendants_selector_leaves_the_base_out():
    manager, written = await _written()
    expected = _under(written, ["@abc.cde", "@abc.cde.efg", "@abc.fgh"])

    found = await manager.where(address="@abc:descendants", order="timestamp:desc", limit=10)

    assert [str(entry.address) for entry in found] == [str(entry.address) for entry in expected]


async def test_a_children_selector_reaches_one_level_only():
    """Discovery walks the descendants range, so the selector's own condition is what narrows it.

    A branch list covering more than the selector admits still has to return exactly what the
    plain statement would, which is what makes a superset safe to discover.
    """
    manager, written = await _written()
    expected = _under(written, ["@abc.cde", "@abc.fgh"])

    found = await manager.where(address="@abc:children", order="timestamp:desc", limit=10)

    assert [str(entry.address) for entry in found] == [str(entry.address) for entry in expected]


async def test_every_component_is_reached_without_the_engine():
    manager, written = await _written()
    expected = _under(written, ["@abc", "@abc.cde", "@abc.cde.efg", "@abc.fgh", "@cde"])

    found = await manager.where(address="@:all", order="timestamp:desc", limit=10)

    assert [str(entry.address) for entry in found] == [str(entry.address) for entry in expected]


async def test_an_or_group_still_reaches_rows_outside_the_selector():
    """The selector bounds every row only while it is conjoined with the rest of the tree.

    Under an `or` a row can match without carrying a selected address, so the listing must not be
    expanded over the selector's branches, which would drop exactly those rows.
    """
    manager, written = await _written()
    expected = _under(written, ["@abc", "@abc.cde", "@abc.cde.efg", "@abc.fgh", "@cde"])

    found = await manager.where(
        address="@abc:all", or__=[{"address": "@cde"}], order="timestamp:desc", limit=10
    )

    assert [str(entry.address) for entry in found] == [str(entry.address) for entry in expected]


async def test_a_subtree_holding_nothing_returns_nothing():
    manager, _ = await _written()

    found = await manager.where(address="@none:all", order="timestamp:desc", limit=10)

    assert list(found) == []
