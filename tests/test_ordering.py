"""Assert that text ordering is a property of Ceres rather than of the database it runs on.

Ordering of text follows the collation a database was created with, so the same query returns a
different order on a cluster initialized with a locale than on one initialized with `C`. These
tests pin the order Ceres promises, which is by code point, matching every general-purpose
language and matching SQLite. They pass on either backend, which is the point.

See `2026-07-27-string-ordering-design.md`.
"""

from ceres import Address, Variable
from ceres.database import Database

# Chosen so a locale collation and a code point collation disagree. A locale orders these
# case-insensitively, giving `abc, ABC, cba, CBA`, and folds punctuation away.
_NAMES = ["abc", "ABC", "cba", "CBA", "_leading", "-dash", "Zebra", "apple"]


async def _database() -> Database:
    database = Database()
    await database.migrate()
    return database


async def test_names_order_by_code_point() -> None:
    """Uppercase sorts before lowercase, and punctuation sorts by its own code point."""
    database = await _database()
    for name in _NAMES:
        await database.variables.create(
            Variable.Create(address=Address("@test"), name=name, value=0)
        )

    ordered = [variable.name for variable in await database.variables.where(order="name")]

    assert ordered == sorted(_NAMES), (
        "Text ordering must match Python's own, which is by code point. A mismatch means the "
        "database's collation is deciding the order instead of Ceres."
    )


async def test_addresses_order_by_code_point() -> None:
    """The engine root sorts after component addresses, because `~` is above `@` in code point."""
    database = await _database()
    addresses = [Address("~"), Address("@abc"), Address("@abc.cde"), Address("@cde")]
    for address in addresses:
        await database.variables.create(Variable.Create(address=address, name="value", value=0))

    ordered = [
        str(variable.address) for variable in await database.variables.where(order="address")
    ]

    assert ordered == ["@abc", "@abc.cde", "@cde", "~"], (
        "A locale collation folds punctuation away and puts `~` first. Ceres orders addresses by "
        "code point so a component tree reads the same on every deployment."
    )


async def test_descending_order_is_the_exact_reverse() -> None:
    """Descending must invert the same comparison, not fall back to the database's own."""
    database = await _database()
    for name in _NAMES:
        await database.variables.create(
            Variable.Create(address=Address("@test"), name=name, value=0)
        )

    ascending = [variable.name for variable in await database.variables.where(order="name:asc")]
    descending = [variable.name for variable in await database.variables.where(order="name:desc")]

    assert descending == list(reversed(ascending))
