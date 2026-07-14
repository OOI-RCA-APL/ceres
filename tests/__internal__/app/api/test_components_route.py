from ceres import Component, Engine
from ceres.__internal__.app.api.routes.components import get_components


async def _build_engine() -> tuple[Engine, Component, Component]:
    """Build an engine with two top-level components: `@alpha` and `@beta`.

    `@alpha` has a single child, `@alpha.child`.
    """
    engine = Engine()
    await engine.database.migrate()

    alpha = Component(__with_name__="alpha")
    beta = Component(__with_name__="beta")
    child = Component(__with_name__="child")

    engine.attach(alpha)
    engine.attach(beta)
    alpha.system.attach(child)

    return engine, alpha, beta


async def test_get_components_returns_one_entry_per_top_level_component() -> None:
    """`GET /api/components` returns one entry per top-level component, not their children."""
    engine, alpha, beta = await _build_engine()

    result = await get_components(engine=engine)

    addresses = {str(info.address) for info in result}
    assert addresses == {str(alpha.system.address), str(beta.system.address)}

    await engine.database.dispose()


async def test_get_components_recursively_populates_children() -> None:
    """Each top-level entry has its descendants nested under `components`."""
    engine, alpha, beta = await _build_engine()

    result = await get_components(engine=engine)

    alpha_info = next(info for info in result if str(info.address) == str(alpha.system.address))
    child_addresses = {str(child.address) for child in alpha_info.components}
    assert child_addresses == {"@alpha.child"}

    await engine.database.dispose()
