"""Engine control operations.

Starting, stopping, enabling, and disabling components, each narrowed to the components
the caller may operate.
"""

from typing import TYPE_CHECKING

from ceres.__internal__.app.shared import Actor, get_components_access
from ceres.__internal__.utilities.collections import uniq
from ceres.address import Address
from ceres.component import Component, ComponentAccessLevel, ComponentFilter
from ceres.concurrency import concurrently
from ceres.data import DataObject

if TYPE_CHECKING:
    from ceres.engine import Engine


async def _filter_operable(
    engine: Engine,
    actor: Actor,
    components: list[Component],
) -> list[Component]:
    """Narrow `components` to those the actor may operate.

    Unrestricted actors (CLI, disabled authentication) and admins pass everything through.
    """
    if actor.unrestricted:
        return components

    access = await get_components_access(engine, actor.user, components)

    return [
        component
        for component in components
        if (level := access[component.system.address]) is not None
        and level >= ComponentAccessLevel.OPERATE
    ]


class StartResult(DataObject):
    started: list[Address]


async def start(engine: Engine, actor: Actor, filter: ComponentFilter) -> StartResult:
    stopped = await _filter_operable(engine, actor, engine.get_components(filter, running=False))
    for component in stopped:
        component.system.start()
    return StartResult(started=sorted(current.system.address for current in stopped))


class StopResult(DataObject):
    stopped: list[Address]


async def stop(engine: Engine, actor: Actor, filter: ComponentFilter) -> StopResult:
    running = await _filter_operable(engine, actor, engine.get_components(filter, running=True))
    await concurrently(component.system.stop() for component in running)

    return StopResult(stopped=sorted(current.system.address for current in running))


class EnableResult(DataObject):
    enabled: list[Address]


async def enable(engine: Engine, actor: Actor, filter: ComponentFilter) -> EnableResult:
    disabled = await _filter_operable(engine, actor, engine.get_components(filter, enabled=False))
    await concurrently(component.system.enable() for component in disabled)

    return EnableResult(enabled=sorted(current.system.address for current in disabled))


class DisableResult(DataObject):
    disabled: list[Address]


async def disable(engine: Engine, actor: Actor, filter: ComponentFilter) -> DisableResult:
    enabled = await _filter_operable(engine, actor, engine.get_components(filter, enabled=True))
    await concurrently(system.system.disable() for system in enabled)

    return DisableResult(disabled=sorted(current.system.address for current in enabled))


class UpResult(DataObject):
    enabled: list[Address]
    started: list[Address]


async def up(engine: Engine, actor: Actor, filter: ComponentFilter) -> UpResult:
    disabled = await _filter_operable(engine, actor, engine.get_components(filter, enabled=False))
    stopped = await _filter_operable(engine, actor, engine.get_components(filter, running=False))
    await concurrently(system.system.up() for system in uniq([*disabled, *stopped], key=id))

    return UpResult(
        enabled=sorted(current.system.address for current in disabled),
        started=sorted(current.system.address for current in stopped),
    )


class DownResult(DataObject):
    disabled: list[Address]
    stopped: list[Address]


async def down(engine: Engine, actor: Actor, filter: ComponentFilter) -> DownResult:
    enabled = await _filter_operable(engine, actor, engine.get_components(filter, enabled=True))
    running = await _filter_operable(engine, actor, engine.get_components(filter, running=True))
    await concurrently(system.system.down() for system in uniq([*enabled, *running], key=id))

    return DownResult(
        disabled=sorted(current.system.address for current in enabled),
        stopped=sorted(current.system.address for current in running),
    )
