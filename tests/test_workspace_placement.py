import pytest
import sqlalchemy
from sqlalchemy.exc import IntegrityError

from ceres.address import Address
from ceres.database import Database
from ceres.workspace import Workspace


async def _setup_database() -> Database:
    database = Database()
    await database.migrate()
    return database


async def test_workspace_defaults_to_engine_placement() -> None:
    database = await _setup_database()
    workspace = await database.workspaces.create(Workspace.Create(name="home"))

    assert workspace.scope == Address("~")
    assert workspace.scope.is_engine

    await database.dispose()


async def test_workspace_can_be_placed_on_a_component() -> None:
    database = await _setup_database()
    workspace = await database.workspaces.create(
        Workspace.Create(name="rig view", scope=Address("@rig"))
    )

    assert workspace.scope == Address("@rig")
    assert not workspace.scope.is_engine

    await database.dispose()


async def test_filter_by_placement_selects_one_placement() -> None:
    database = await _setup_database()
    engine_placed = await database.workspaces.create(Workspace.Create(name="home"))
    component_placed = await database.workspaces.create(
        Workspace.Create(name="rig view", scope=Address("@rig"))
    )

    on_engine = {current.id for current in await database.workspaces.where(scope=Address("~"))}
    on_rig = {current.id for current in await database.workspaces.where(scope=Address("@rig"))}

    assert on_engine == {engine_placed.id}
    assert on_rig == {component_placed.id}

    await database.dispose()


async def test_filter_by_placed_on_engine_separates_the_two_placements() -> None:
    database = await _setup_database()
    engine_placed = await database.workspaces.create(Workspace.Create(name="home"))
    component_placed = await database.workspaces.create(
        Workspace.Create(name="rig view", scope=Address("@rig"))
    )

    on_engine = {current.id for current in await database.workspaces.where(placed_on_engine=True)}
    on_components = {
        current.id for current in await database.workspaces.where(placed_on_engine=False)
    }

    assert on_engine == {engine_placed.id}
    assert on_components == {component_placed.id}

    await database.dispose()


async def test_placement_column_rejects_a_null() -> None:
    """The migrated schema has no representation for an unplaced workspace."""
    database = await _setup_database()
    await database.workspaces.create(Workspace.Create(name="home"))

    with pytest.raises(IntegrityError):
        async with database.engine.begin() as connection:
            await connection.execute(
                sqlalchemy.text(
                    "INSERT INTO workspaces (id, name, scope, data) "
                    "VALUES ('00000000000000000000000000000001', 'legacy', NULL, '{}')"
                )
            )

    await database.dispose()
