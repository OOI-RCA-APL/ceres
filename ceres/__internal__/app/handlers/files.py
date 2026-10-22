from pathlib import Path
from typing import TYPE_CHECKING

from ceres.__internal__.app.shared import get_component_access, get_components_access
from ceres.address import Address
from ceres.component import Component, ComponentAccessLevel
from ceres.data import DataObject, Name
from ceres.error import NotFoundError
from ceres.mount import MountAccess, MountPath

if TYPE_CHECKING:
    from ceres.__internal__.app.shared import Actor
    from ceres.engine import Engine

PROJECT_MOUNT = "project"
"""ID of the mount serving the project directory, to administrators only."""

COMPONENT_MOUNT_PREFIX = "component:"
"""Prefix of a component mount's ID, followed by `<address>:<name>`."""


class MountInfo(DataObject):
    """A mount of the files API that the caller may view."""

    id: str
    name: Name
    label: str
    component: Address | None
    """The component whose field holds the mount, `None` for the project mount."""
    access: MountAccess
    """What the caller may do with the mount."""
    temporary: bool
    """Whether the mount is a temporary directory removed with the component's last
    reference to it."""


MountInfo.__name__ = "FileMount"
MountInfo.__qualname__ = "FileMount"


class ResolvedMount(DataObject):
    """Where a mount lives on disk, for the server that reads and writes it."""

    path: str
    """Absolute path of the mount's root directory."""
    access: MountAccess
    """What the caller may do with the mount."""
    exclude: list[str]
    """The `server.files.exclude` patterns."""
    max_upload: int | None
    """Largest file one upload may write, in bytes, unlimited when `None`."""


def component_mount_id(address: Address, name: str) -> str:
    """Return the ID of the mount the component at `address` lists under `name`."""
    return f"{COMPONENT_MOUNT_PREFIX}{address}:{name}"


def _cap(engine: Engine) -> MountAccess:
    return MountAccess(engine.config.server.files.access)


def _mount_access(engine: Engine, level: ComponentAccessLevel, mount: MountPath) -> MountAccess:
    declared = mount.access
    if declared is None:
        declared = MountAccess.EDIT if mount.writable else MountAccess.VIEW

    if level >= ComponentAccessLevel.OPERATE:
        caller = MountAccess.EDIT
    elif level >= ComponentAccessLevel.VIEW:
        caller = MountAccess.VIEW
    else:
        caller = MountAccess.NONE

    return min(declared, _cap(engine), caller)


def _project_directory(engine: Engine) -> Path:
    project = engine.project
    base = project.directory.path if project is not None else Path.cwd()
    root = engine.config.server.files.root
    return base if root is None else base / root


def _project_mount(engine: Engine, actor: Actor) -> MountInfo | None:
    access = _cap(engine)
    if not actor.admin or access == MountAccess.NONE:
        return None

    return MountInfo(
        id=PROJECT_MOUNT,
        name=PROJECT_MOUNT,
        label="Project",
        component=None,
        access=access,
        temporary=False,
    )


def component_mounts(
    engine: Engine, component: Component, level: ComponentAccessLevel
) -> list[MountInfo]:
    """Return the mounts of `component` a caller at `level` may view."""
    system = component.system
    mounts: list[MountInfo] = []
    for binding in system.get_mount_bindings().values():
        mount = system.get_mount(binding.name)
        if mount is None:
            continue

        access = _mount_access(engine, level, mount)
        if access == MountAccess.NONE:
            continue

        mounts.append(
            MountInfo(
                id=component_mount_id(system.address, binding.name),
                name=binding.name,
                label=binding.label,
                component=system.address,
                access=access,
                temporary=mount.temporary,
            )
        )

    return mounts


async def get_mounts(engine: Engine, actor: Actor) -> list[MountInfo]:
    """Return every mount the caller may view, the project mount first."""
    project = _project_mount(engine, actor)
    mounts = [] if project is None else [project]

    components = [
        component for component in engine.get_components() if component.system.get_mount_bindings()
    ]
    access = (
        None if actor.unrestricted else await get_components_access(engine, actor.user, components)
    )
    for component in components:
        address = component.system.address
        level = ComponentAccessLevel.MANAGE if access is None else access.get(address)
        if level is not None:
            mounts.extend(component_mounts(engine, component, level))

    return mounts


async def resolve_mount(engine: Engine, actor: Actor, id: str) -> ResolvedMount:
    """Return where the mount with `id` lives and what the caller may do with it.

    Raises:
        NotFoundError: If no mount has the ID or the caller may not view it.
    """
    exclude = list(engine.config.server.files.exclude)
    max_upload = engine.config.server.files.max_upload
    if id == PROJECT_MOUNT:
        project = _project_mount(engine, actor)
        if project is None:
            raise NotFoundError()

        return ResolvedMount(
            path=str(_project_directory(engine).absolute()),
            access=project.access,
            exclude=exclude,
            max_upload=max_upload,
        )

    address, separator, name = id.removeprefix(COMPONENT_MOUNT_PREFIX).rpartition(":")
    if not id.startswith(COMPONENT_MOUNT_PREFIX) or not separator:
        raise NotFoundError()

    component = engine.get_component(address)
    mount = None if component is None else component.system.get_mount(name)
    if component is None or mount is None:
        raise NotFoundError()

    if actor.unrestricted:
        level = ComponentAccessLevel.MANAGE
    else:
        level = await get_component_access(engine, actor.user, component)

    access = MountAccess.NONE if level is None else _mount_access(engine, level, mount)
    if access == MountAccess.NONE:
        raise NotFoundError()

    return ResolvedMount(
        path=str(mount.path),
        access=access,
        exclude=exclude,
        max_upload=max_upload,
    )
