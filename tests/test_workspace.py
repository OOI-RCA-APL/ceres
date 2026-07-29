from ceres import Engine
from ceres.address import Address
from ceres.workspace import Workspace


async def _build_engine() -> Engine:
    engine = Engine()
    await engine.database.migrate()
    return engine


async def test_workspace_scope_round_trips() -> None:
    engine = await _build_engine()
    created = await engine.workspaces.create(
        Workspace.Create(name="pump", scope=Address("@rig.pump"))
    )
    fetched = await engine.workspaces.get(created.id)
    assert fetched is not None
    assert fetched.scope == Address("@rig.pump")

    await engine.database.dispose()


async def test_workspace_scope_defaults_to_the_engine_root() -> None:
    engine = await _build_engine()
    created = await engine.workspaces.create(Workspace.Create(name="home"))
    fetched = await engine.workspaces.get(created.id)
    assert fetched is not None
    assert fetched.scope == Address("~")

    await engine.database.dispose()


async def test_workspace_filter_by_scope_and_placement() -> None:
    engine = await _build_engine()
    on_component = await engine.workspaces.create(
        Workspace.Create(name="scoped", scope=Address("@rig"))
    )
    on_engine = await engine.workspaces.create(Workspace.Create(name="home"))

    by_scope = await engine.workspaces.where(scope=Address("@rig")).all()
    assert [workspace.id for workspace in by_scope] == [on_component.id]

    only_engine = await engine.workspaces.where(placed_on_engine=True).all()
    assert [workspace.id for workspace in only_engine] == [on_engine.id]

    only_components = await engine.workspaces.where(placed_on_engine=False).all()
    assert [workspace.id for workspace in only_components] == [on_component.id]

    await engine.database.dispose()
