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


async def test_workspace_scope_defaults_to_none() -> None:
    engine = await _build_engine()
    created = await engine.workspaces.create(Workspace.Create(name="global"))
    fetched = await engine.workspaces.get(created.id)
    assert fetched is not None
    assert fetched.scope is None

    await engine.database.dispose()


async def test_workspace_filter_by_scope_and_scoped() -> None:
    engine = await _build_engine()
    scoped = await engine.workspaces.create(Workspace.Create(name="scoped", scope=Address("@rig")))
    unscoped = await engine.workspaces.create(Workspace.Create(name="global"))

    by_scope = await engine.workspaces.where(scope=Address("@rig")).all()
    assert [workspace.id for workspace in by_scope] == [scoped.id]

    only_global = await engine.workspaces.where(scoped=False).all()
    assert [workspace.id for workspace in only_global] == [unscoped.id]

    only_scoped = await engine.workspaces.where(scoped=True).all()
    assert [workspace.id for workspace in only_scoped] == [scoped.id]

    await engine.database.dispose()
