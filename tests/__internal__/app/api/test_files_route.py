from pathlib import Path

import pytest

from ceres import AsyncMount, Bound, Component, Engine, Mount
from ceres.__internal__.app.handlers.components import get_component
from ceres.__internal__.app.handlers.files import get_mounts, resolve_mount
from ceres.__internal__.app.shared import Actor
from ceres.component import ComponentAccessLevel, ComponentConfig, get_mount_bindings
from ceres.config import ServerConfig, ServerFilesConfig
from ceres.error import NotFoundError
from ceres.mount import MountAccess
from ceres.permission import PermissionTargetType, UserPermission
from ceres.user import User

_UNRESTRICTED = Actor(user=None, unrestricted=True)


class Hoarder(Component):
    stash: Bound[Mount] = Mount.Field(..., title="Stash")
    ledger: Bound[Mount] = Mount.Field(..., title="Ledger", writable=False)
    vault: Bound[AsyncMount] = Mount.Field(..., access="none")
    spare: Bound[Mount | None] = Mount.Field(default=None)
    scratch: Bound[Mount] = Mount.Field()
    plain: Mount | None = None


async def _engine(tmp_path: Path, access: MountAccess = MountAccess.EDIT) -> tuple[Engine, Hoarder]:
    engine = Engine()
    engine.config.server = ServerConfig(files={"access": access})
    await engine.database.migrate()
    hoarder = Hoarder(
        __with_name__="hoarder",
        __with_config__=ComponentConfig(name="hoarder", access=ComponentAccessLevel.DENY),
        stash=Mount(tmp_path),
        ledger=Mount(tmp_path),
        vault=AsyncMount(tmp_path),
    )
    engine.attach(hoarder)
    return engine, hoarder


async def _user(
    engine: Engine, level: ComponentAccessLevel | None, *, admin: bool = False, name: str = "abc"
) -> Actor:
    user = await engine.database.users.create(
        User.Create(username=name, email=f"{name}@test.com", password="abcd", admin=admin)
    )
    if level is not None:
        await engine.database.user_permissions.create(
            UserPermission.Create(
                user_id=user.id,
                target_type=PermissionTargetType.COMPONENT,
                target="@hoarder",
                level=level,
            )
        )

    return Actor(user=user, unrestricted=False)


def test_mount_fields_bind_in_field_order() -> None:
    bindings = get_mount_bindings(Hoarder)
    assert [(binding.name, binding.label, binding.writable) for binding in bindings.values()] == [
        ("stash", "Stash", True),
        ("ledger", "Ledger", False),
        ("vault", "vault", True),
        ("spare", "spare", True),
        ("scratch", "scratch", True),
    ]


def test_mount_field_applies_its_writable_and_access(tmp_path: Path) -> None:
    hoarder = Hoarder(stash=Mount(tmp_path), ledger=Mount(tmp_path), vault=AsyncMount(tmp_path))
    assert (hoarder.ledger.writable, hoarder.ledger.access) == (False, None)
    assert (type(hoarder.vault), hoarder.vault.access) == (AsyncMount, MountAccess.NONE)
    assert hoarder.scratch.temporary


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        (MountAccess.EDIT, MountAccess.VIEW),
        (MountAccess.VIEW, MountAccess.VIEW),
        (MountAccess.NONE, MountAccess.NONE),
    ],
)
def test_mount_field_access_is_never_widened_by_configuration(
    tmp_path: Path, configured: MountAccess, expected: MountAccess
) -> None:
    class Miser(Component):
        purse: Bound[Mount] = Mount.Field(..., access="view")

    assert Miser(purse=Mount(tmp_path, access=configured)).purse.access == expected


def test_mount_field_on_a_field_that_is_not_a_mount_is_refused() -> None:
    class Miser(Component):
        coins: Bound[int] = Mount.Field(...)  # pyright: ignore[reportAssignmentType]

    with pytest.raises(TypeError, match="coins"):
        get_mount_bindings(Miser)


def test_mount_fields_sharing_a_name_are_refused() -> None:
    class Miser(Component):
        coins: Bound[Mount] = Mount.Field(...)
        purse: Bound[Mount] = Mount.Field(..., name="coins")

    with pytest.raises(TypeError, match="'coins' and 'purse'"):
        get_mount_bindings(Miser)


async def test_mounts_lists_present_mounts_the_caller_may_view(tmp_path: Path) -> None:
    engine, _ = await _engine(tmp_path)

    mounts = await get_mounts(engine, _UNRESTRICTED)
    assert [(mount.id, mount.label, mount.access, mount.temporary) for mount in mounts] == [
        ("project", "Project", MountAccess.EDIT, False),
        ("@hoarder/stash", "Stash", MountAccess.EDIT, False),
        ("@hoarder/ledger", "Ledger", MountAccess.VIEW, False),
        ("@hoarder/scratch", "scratch", MountAccess.EDIT, True),
    ]

    await engine.database.dispose()


@pytest.mark.parametrize(
    ("level", "stash", "ledger"),
    [
        (ComponentAccessLevel.VIEW, MountAccess.VIEW, MountAccess.VIEW),
        (ComponentAccessLevel.OPERATE, MountAccess.EDIT, MountAccess.VIEW),
        (ComponentAccessLevel.MANAGE, MountAccess.EDIT, MountAccess.VIEW),
    ],
)
async def test_mount_access_is_the_least_of_the_mount_and_the_caller(
    tmp_path: Path, level: ComponentAccessLevel, stash: MountAccess, ledger: MountAccess
) -> None:
    engine, _ = await _engine(tmp_path)
    actor = await _user(engine, level)

    mounts = await get_mounts(engine, actor)
    # The writable temporary `scratch` mount follows the caller the way `stash` does.
    assert [mount.access for mount in mounts] == [stash, ledger, stash]
    assert (await resolve_mount(engine, actor, "@hoarder/ledger")).access == ledger

    await engine.database.dispose()


@pytest.mark.parametrize(
    ("cap", "ids"),
    [
        (MountAccess.VIEW, ["project", "@hoarder/stash"]),
        (MountAccess.NONE, []),
    ],
)
async def test_mount_access_is_capped_by_the_server(
    tmp_path: Path, cap: MountAccess, ids: list[str]
) -> None:
    engine, _ = await _engine(tmp_path, cap)
    admin = await _user(engine, ComponentAccessLevel.MANAGE, admin=True)

    mounts = await get_mounts(engine, admin)
    assert [mount.id for mount in mounts][:2] == ids
    assert all(mount.access == cap for mount in mounts)

    await engine.database.dispose()


async def test_project_mount_is_listed_to_an_admin_only(tmp_path: Path) -> None:
    engine, _ = await _engine(tmp_path)

    admin = await _user(engine, None, admin=True)
    project = await resolve_mount(engine, admin, "project")
    assert (project.path, project.access, project.exclude) == (
        str(Path.cwd()),
        MountAccess.EDIT,
        [],
    )
    manager = await _user(engine, ComponentAccessLevel.MANAGE, name="abcd")
    assert "project" not in [mount.id for mount in await get_mounts(engine, manager)]

    await engine.database.dispose()


def test_files_max_upload_reads_a_byte_size() -> None:
    assert ServerFilesConfig(max_upload="2KiB").max_upload == 2048
    assert ServerFilesConfig().max_upload is None


async def test_mounts_hides_every_mount_from_a_caller_without_access(tmp_path: Path) -> None:
    engine, _ = await _engine(tmp_path)

    assert await get_mounts(engine, await _user(engine, None)) == []

    await engine.database.dispose()


async def test_resolve_finds_a_mount_the_caller_may_view(tmp_path: Path) -> None:
    engine, _ = await _engine(tmp_path)

    resolved = await resolve_mount(engine, _UNRESTRICTED, "@hoarder/stash")
    assert (resolved.path, resolved.access) == (str(tmp_path), MountAccess.EDIT)

    await engine.database.dispose()


@pytest.mark.parametrize(
    "id",
    [
        "project",
        "@hoarder/stash",
        "@hoarder/vault",
        "@hoarder/spare",
        "@hoarder/plain",
        "@missing/stash",
        "stash",
    ],
)
async def test_resolve_refuses_a_mount_the_caller_may_not_reach(tmp_path: Path, id: str) -> None:
    engine, _ = await _engine(tmp_path)

    with pytest.raises(NotFoundError):
        await resolve_mount(engine, await _user(engine, None), id)

    await engine.database.dispose()


@pytest.mark.parametrize(
    "id", ["@hoarder", "@hoarder/", "hoarder/stash", "@hoarder/stash/abc", "@/stash", "@a b/stash"]
)
async def test_resolve_refuses_a_malformed_id(tmp_path: Path, id: str) -> None:
    engine, _ = await _engine(tmp_path)

    with pytest.raises(NotFoundError):
        await resolve_mount(engine, _UNRESTRICTED, id)

    await engine.database.dispose()


async def test_component_lists_its_present_mounts(tmp_path: Path) -> None:
    engine, hoarder = await _engine(tmp_path)

    info = await get_component(engine, _UNRESTRICTED, hoarder.system.address)
    assert [(mount.name, mount.id) for mount in info.mounts] == [
        ("stash", "@hoarder/stash"),
        ("ledger", "@hoarder/ledger"),
        ("scratch", "@hoarder/scratch"),
    ]

    await engine.database.dispose()
