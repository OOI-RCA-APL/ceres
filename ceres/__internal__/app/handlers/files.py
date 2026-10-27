from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from ceres.__internal__.app.shared import get_component_access, get_components_access
from ceres.address import Address
from ceres.component import Component, ComponentAccessLevel
from ceres.data import DataObject, Name
from ceres.error import NotFoundError
from ceres.mount import MountAccess, MountPath
from ceres.paths import host_name, zone_name

if TYPE_CHECKING:
    from ceres.__internal__.app.shared import Actor
    from ceres.engine import Engine


class MountInfo(DataObject):
    """A mount of the files API that the caller may view.

    An engine mount's ID is its name in `server.files.mounts`, and a component mount's is
    `<address>/<name>`. A name never starts with `@`, which keeps the two apart.
    """

    id: str
    name: Name
    label: str
    component: Address | None
    """The component whose field holds the mount, `None` for an engine mount."""
    access: MountAccess
    """What the caller may do with the mount."""
    temporary: bool
    """Whether the mount is a temporary directory removed with the component's last
    reference to it."""
    reveal_paths: bool
    """Whether `?stat` answers where an entry lives on the server, the same for every mount."""
    layout: str | None
    """Dated folders below the root, such as `{year}/{month}`, `None` for none."""
    zone: str
    """IANA name of the time zone the layout reads in."""
    names: dict[str, str]
    """Values of the name atoms the layout may use, `{host}` only where `reveal_paths` is on."""
    files: dict[str, str]
    """File name templates by kind that the component writes into the layout's folders."""


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
    reveal_paths: bool
    """Whether `?stat` answers where an entry lives on the server."""


def component_mount_id(address: Address, name: str) -> str:
    """Return the ID of the mount the component at `address` lists under `name`."""
    return f"{address}/{name}"


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


class _EngineMount(NamedTuple):
    path: Path
    access: MountAccess
    layout: str | None
    zone: str


def _engine_mounts(engine: Engine) -> dict[str, _EngineMount]:
    """Return each engine mount by name, with its absolute path and the effective access every
    signed-in caller shares. A mount whose access is `none` is left out."""
    project = engine.project
    base = project.directory.path if project is not None else Path.cwd()
    cap = _cap(engine)
    mounts: dict[str, _EngineMount] = {}
    for name, setting in engine.config.server.files.mounts.items():
        declared = setting["access"]
        access = min(MountAccess.EDIT if declared is None else MountAccess(declared), cap)
        if access != MountAccess.NONE:
            path = (base / setting["path"]).absolute()
            mounts[name] = _EngineMount(path, access, setting["layout"], setting["zone"] or "utc")

    return mounts


def _names(engine: Engine, names: Mapping[str, str]) -> dict[str, str]:
    """Return `names` with the `{project}` and `{host}` values every mount shares.

    The host name says where files live, so it goes out only where `reveal_paths` does.
    """
    shared: dict[str, str] = {}
    if engine.config.server.files.reveal_paths:
        shared["host"] = host_name()

    if engine.project is not None:
        shared["project"] = engine.project.directory.name

    return {**shared, **names}


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
                reveal_paths=engine.config.server.files.reveal_paths,
                layout=None if mount.layout is None else mount.layout.source,
                zone=zone_name(mount.zone),
                names=_names(engine, mount.names),
                files={kind: file.source for kind, file in mount.files.items()},
            )
        )

    return mounts


async def get_mounts(engine: Engine, actor: Actor) -> list[MountInfo]:
    """Return every mount the caller may view, the engine's before the components'."""
    mounts = [
        MountInfo(
            id=name,
            name=name,
            label=name,
            component=None,
            access=mount.access,
            temporary=False,
            reveal_paths=engine.config.server.files.reveal_paths,
            layout=mount.layout,
            zone=zone_name(mount.zone),
            names=_names(engine, {"mount": name}),
            files={},
        )
        for name, mount in _engine_mounts(engine).items()
    ]

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
    files = engine.config.server.files
    if not id.startswith("@"):
        mount = _engine_mounts(engine).get(id)
        if mount is None:
            raise NotFoundError()

        return ResolvedMount(
            path=str(mount.path),
            access=mount.access,
            exclude=list(files.exclude),
            max_upload=files.max_upload,
            reveal_paths=files.reveal_paths,
        )

    address, separator, name = id.partition("/")
    if not separator:
        raise NotFoundError()

    try:
        component = engine.get_component(address)
    except ValueError:
        raise NotFoundError() from None

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
        exclude=list(files.exclude),
        max_upload=files.max_upload,
        reveal_paths=files.reveal_paths,
    )
