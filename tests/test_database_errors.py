"""What a manager raises when the database refuses a write.

These are the exception types an application catches, so they are part of what the managers
promise rather than an implementation detail of the driver underneath. Every driver reports a
constraint violation in its own words, and the translation from those words to a Ceres error is
what these tests hold still.
"""

from uuid import uuid4

import pytest

from ceres import Group, GroupMembership, User
from ceres.database import Database
from ceres.error import AlreadyExistsError, IntegrityError

# Each backend words a constraint violation its own way, and the translation is what is being
# tested, so every backend has to run these.
pytestmark = pytest.mark.databases()


async def _database() -> Database:
    database = Database()
    await database.migrate()
    return database


async def test_a_duplicate_username_names_the_column_it_collided_on() -> None:
    """`AlreadyExistsError.field` tells the caller which value was already taken."""
    database = await _database()
    await database.users.create(
        User.Create(username="taken", email="first@example.com", password="password1234")
    )

    with pytest.raises(AlreadyExistsError) as caught:
        await database.users.create(
            User.Create(username="taken", email="second@example.com", password="password1234")
        )

    assert caught.value.field == "username"


async def test_a_duplicate_primary_key_is_an_already_exists_error() -> None:
    """A repeated ID collides on the primary key rather than on a named unique constraint."""
    database = await _database()
    identifier = uuid4()
    await database.groups.create(Group.Create(id=identifier, name="first"))

    with pytest.raises(AlreadyExistsError):
        await database.groups.create(Group.Create(id=identifier, name="second"))


async def test_a_missing_foreign_key_is_an_integrity_error() -> None:
    """A row pointing at something that is not there is refused, and not as a duplicate."""
    database = await _database()

    with pytest.raises(IntegrityError) as caught:
        await database.group_memberships.create(
            GroupMembership.Create(user_id=uuid4(), group_id=uuid4())
        )

    assert not isinstance(caught.value, AlreadyExistsError)
