from pathlib import Path
from typing import TYPE_CHECKING

from ceres.__internal__.app.shared import get_component_access, get_components_access
from ceres.address import Address
from ceres.component import Component, ComponentAccessLevel, FileRootBinding
from ceres.data import DataObject
from ceres.error import NotFoundError, NotPermittedError

if TYPE_CHECKING:
    from ceres.__internal__.app.shared import Actor
    from ceres.engine import Engine

PROJECT_ROOT = "project"
"""ID of the root serving the project directory, to administrators only."""

COMPONENT_ROOT_PREFIX = "component:"
"""Prefix of a component root's ID, followed by `<address>:<field>`."""


class FileRootInfo(DataObject):
    """A root of the console's file browser that the caller may view."""

    id: str
    label: str
    component: Address | None
    """The component whose field serves the root, `None` for the project root."""
    level: ComponentAccessLevel
    """The caller's access level on the root."""
    writable: bool
    """Whether the caller may change files in the root."""


FileRootInfo.__name__ = "FileRoot"
FileRootInfo.__qualname__ = "FileRoot"


class ResolvedFileRoot(DataObject):
    """Where a file root lives on disk, for the server that reads and writes it."""

    path: str
    """Absolute path of the root directory."""
    level: ComponentAccessLevel
    writable: bool
    """Whether the caller may change files in the root."""
    exclude: list[str]
    """The `server.files.exclude` patterns."""
    max_upload: int | None
    """Largest file one upload may write, in bytes, unlimited when `None`."""


def component_root_id(address: Address, field: str) -> str:
    """Return the ID of the root that `field` of the component at `address` serves."""
    return f"{COMPONENT_ROOT_PREFIX}{address}:{field}"


def _component_root_writable(level: ComponentAccessLevel, binding: FileRootBinding) -> bool:
    # The marker binds every level, since a component that marks its directory read-only writes
    # there itself and no level of trust makes a concurrent write safe.
    return binding.writable and level >= ComponentAccessLevel.OPERATE


def _served_components(engine: Engine) -> list[Component]:
    return [
        component
        for component in engine.get_components()
        if component.system.get_file_root_bindings()
    ]


def _project_root(engine: Engine) -> Path:
    project = engine.project
    base = project.directory.path if project is not None else Path.cwd()
    root = engine.config.server.files.root
    return base if root is None else base / root


async def get_file_roots(engine: Engine, actor: Actor) -> list[FileRootInfo]:
    """Return every file root the caller may view, the project root first."""
    roots: list[FileRootInfo] = []
    if actor.admin:
        roots.append(
            FileRootInfo(
                id=PROJECT_ROOT,
                label="Project",
                component=None,
                level=ComponentAccessLevel.MANAGE,
                writable=True,
            )
        )

    components = _served_components(engine)
    access = (
        None if actor.unrestricted else await get_components_access(engine, actor.user, components)
    )
    for component in components:
        system = component.system
        level = ComponentAccessLevel.MANAGE if access is None else access.get(system.address)
        if level is None or level < ComponentAccessLevel.VIEW:
            continue

        roots.extend(
            FileRootInfo(
                id=component_root_id(system.address, binding.field),
                label=binding.label,
                component=system.address,
                level=level,
                writable=_component_root_writable(level, binding),
            )
            for binding in system.get_file_root_bindings().values()
            if system.get_file_root(binding.field) is not None
        )

    return roots


async def resolve_file_root(engine: Engine, actor: Actor, id: str) -> ResolvedFileRoot:
    """Return where the root with `id` lives and the caller's access level on it.

    Raises:
        NotFoundError: If no root has the ID.
        NotPermittedError: If the caller may not view the root.
    """
    exclude = list(engine.config.server.files.exclude)
    max_upload = engine.config.server.files.max_upload
    if id == PROJECT_ROOT:
        if not actor.admin:
            raise NotPermittedError()

        return ResolvedFileRoot(
            path=str(_project_root(engine).absolute()),
            level=ComponentAccessLevel.MANAGE,
            writable=True,
            exclude=exclude,
            max_upload=max_upload,
        )

    address, separator, field = id.removeprefix(COMPONENT_ROOT_PREFIX).rpartition(":")
    if not id.startswith(COMPONENT_ROOT_PREFIX) or not separator:
        raise NotFoundError()

    component = engine.get_component(address)
    directory = None if component is None else component.system.get_file_root(field)
    if component is None or directory is None:
        raise NotFoundError()

    if actor.unrestricted:
        level = ComponentAccessLevel.MANAGE
    else:
        level = await get_component_access(engine, actor.user, component)
        if level is None or level < ComponentAccessLevel.VIEW:
            raise NotPermittedError()

    binding = component.system.get_file_root_bindings()[field]
    return ResolvedFileRoot(
        path=str(directory.path),
        level=level,
        writable=_component_root_writable(level, binding),
        exclude=exclude,
        max_upload=max_upload,
    )
