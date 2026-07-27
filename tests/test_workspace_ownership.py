from ceres.database import Database
from ceres.user import User
from ceres.workspace import Workspace


async def _setup_database() -> Database:
    database = Database()
    await database.migrate()
    return database


async def test_workspace_defaults_to_unowned_and_hidden_when_logged_out() -> None:
    database = await _setup_database()
    workspace = await database.workspaces.create(Workspace.Create(name="shared"))

    assert workspace.owner_id is None
    assert workspace.show_when_logged_out is False

    await database.dispose()


async def test_owned_workspace_records_its_owner() -> None:
    database = await _setup_database()
    user = await database.users.create(
        User.Create(username="owner", email="o@test.com", password="hashed")
    )
    workspace = await database.workspaces.create(Workspace.Create(name="scratch", owner_id=user.id))

    assert workspace.owner_id == user.id

    await database.dispose()


async def test_filter_by_owner_selects_only_that_users_workspaces() -> None:
    database = await _setup_database()
    first = await database.users.create(
        User.Create(username="first", email="f@test.com", password="hashed")
    )
    second = await database.users.create(
        User.Create(username="second", email="s@test.com", password="hashed")
    )
    mine = await database.workspaces.create(Workspace.Create(name="mine", owner_id=first.id))
    theirs = await database.workspaces.create(Workspace.Create(name="theirs", owner_id=second.id))
    shared = await database.workspaces.create(Workspace.Create(name="shared"))

    found = {current.id for current in await database.workspaces.where(owner_id=first.id)}
    assert found == {mine.id}
    assert theirs.id not in found
    assert shared.id not in found

    await database.dispose()


async def test_filter_by_owned_separates_owned_from_shared() -> None:
    database = await _setup_database()
    user = await database.users.create(
        User.Create(username="owner", email="o@test.com", password="hashed")
    )
    owned = await database.workspaces.create(Workspace.Create(name="owned", owner_id=user.id))
    shared = await database.workspaces.create(Workspace.Create(name="shared"))

    only_owned = {current.id for current in await database.workspaces.where(owned=True)}
    only_shared = {current.id for current in await database.workspaces.where(owned=False)}

    assert only_owned == {owned.id}
    assert only_shared == {shared.id}

    await database.dispose()


async def test_filter_by_show_when_logged_out_separates_visible_from_hidden() -> None:
    database = await _setup_database()
    visible = await database.workspaces.create(
        Workspace.Create(name="visible", show_when_logged_out=True)
    )
    hidden = await database.workspaces.create(Workspace.Create(name="hidden"))

    shown = {current.id for current in await database.workspaces.where(show_when_logged_out=True)}
    not_shown = {
        current.id for current in await database.workspaces.where(show_when_logged_out=False)
    }

    assert shown == {visible.id}
    assert not_shown == {hidden.id}

    await database.dispose()


async def test_deleting_a_user_deletes_their_private_workspaces() -> None:
    database = await _setup_database()
    user = await database.users.create(
        User.Create(username="owner", email="o@test.com", password="hashed")
    )
    workspace = await database.workspaces.create(Workspace.Create(name="scratch", owner_id=user.id))

    await database.users.where(id=user.id).delete()

    assert await database.workspaces.where(id=workspace.id).first() is None

    await database.dispose()
