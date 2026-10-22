from pathlib import Path
from typing import Annotated

import pytest
from pydantic import Field

from ceres import Component, Engine, Files, LogEntry, Mount
from ceres.__internal__.app.handlers.components import get_component
from ceres.__internal__.app.handlers.files import get_file_roots, resolve_file_root
from ceres.__internal__.app.shared import Actor
from ceres.component import ComponentAccessLevel, ComponentConfig, get_file_root_bindings
from ceres.config import ServerFilesConfig
from ceres.error import NotFoundError, NotPermittedError
from ceres.permission import PermissionTargetType, UserPermission
from ceres.user import User

_UNRESTRICTED = Actor(user=None, unrestricted=True)


class Hoarder(Component):
    stash: Annotated[Mount, Files("Stash")]
    ledger: Annotated[Mount, Files("Ledger", writable=False)]
    spare: Annotated[Mount | None, Files()] = None
    scratch: Annotated[Mount, Files()] = Field(default_factory=Mount)
    plain: Mount | None = None


async def _engine(tmp_path: Path) -> tuple[Engine, Hoarder]:
    engine = Engine()
    await engine.database.migrate()
    hoarder = Hoarder(
        __with_name__="hoarder",
        __with_config__=ComponentConfig(name="hoarder", access=ComponentAccessLevel.DENY),
        stash=Mount(tmp_path),
        ledger=Mount(tmp_path),
    )
    engine.attach(hoarder)
    return engine, hoarder


async def _user(
    engine: Engine, level: ComponentAccessLevel | None, *, admin: bool = False
) -> Actor:
    user = await engine.database.users.create(
        User.Create(username="abc", email="abc@test.com", password="abcd", admin=admin)
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


def test_files_marks_directory_fields_as_roots() -> None:
    bindings = get_file_root_bindings(Hoarder)
    assert [(binding.field, binding.label) for binding in bindings.values()] == [
        ("stash", "Stash"),
        ("ledger", "Ledger"),
        ("spare", "spare"),
        ("scratch", "scratch"),
    ]


def test_files_on_a_field_that_is_not_a_directory_is_refused() -> None:
    class Miser(Component):
        coins: Annotated[int, Files()] = 0

    with pytest.raises(TypeError, match="coins"):
        get_file_root_bindings(Miser)


async def test_files_roots_lists_present_roots_the_caller_may_view(tmp_path: Path) -> None:
    engine, _ = await _engine(tmp_path)

    roots = await get_file_roots(engine, _UNRESTRICTED)
    assert [(root.id, root.label, root.level) for root in roots] == [
        ("project", "Project", ComponentAccessLevel.MANAGE),
        ("component:@hoarder:stash", "Stash", ComponentAccessLevel.MANAGE),
        ("component:@hoarder:ledger", "Ledger", ComponentAccessLevel.MANAGE),
    ]

    viewer = await _user(engine, ComponentAccessLevel.VIEW)
    roots = await get_file_roots(engine, viewer)
    assert [(root.id, root.level) for root in roots] == [
        ("component:@hoarder:stash", ComponentAccessLevel.VIEW),
        ("component:@hoarder:ledger", ComponentAccessLevel.VIEW),
    ]

    await engine.database.dispose()


@pytest.mark.parametrize(
    ("level", "stash", "ledger"),
    [
        (ComponentAccessLevel.VIEW, False, False),
        (ComponentAccessLevel.OPERATE, True, False),
        (ComponentAccessLevel.MANAGE, True, False),
    ],
)
async def test_files_roots_are_writable_from_operate_unless_marked_read_only(
    tmp_path: Path, level: ComponentAccessLevel, stash: bool, ledger: bool
) -> None:
    engine, _ = await _engine(tmp_path)
    actor = await _user(engine, level)

    roots = await get_file_roots(engine, actor)
    assert [root.writable for root in roots] == [stash, ledger]
    resolved = await resolve_file_root(engine, actor, "component:@hoarder:ledger")
    assert resolved.writable == ledger

    await engine.database.dispose()


async def test_files_project_root_is_writable_by_an_admin(tmp_path: Path) -> None:
    engine, _ = await _engine(tmp_path)
    admin = await _user(engine, None, admin=True)

    assert [root.writable for root in await get_file_roots(engine, admin)][0]
    assert (await resolve_file_root(engine, admin, "project")).writable

    await engine.database.dispose()


def test_files_max_upload_reads_a_byte_size() -> None:
    assert ServerFilesConfig(max_upload="2KiB").max_upload == 2048
    assert ServerFilesConfig().max_upload is None


async def test_files_roots_hides_every_root_from_a_caller_without_access(tmp_path: Path) -> None:
    engine, _ = await _engine(tmp_path)

    assert await get_file_roots(engine, await _user(engine, None)) == []

    await engine.database.dispose()


async def test_files_resolve_finds_a_root_the_caller_may_view(tmp_path: Path) -> None:
    engine, _ = await _engine(tmp_path)

    resolved = await resolve_file_root(engine, _UNRESTRICTED, "component:@hoarder:stash")
    assert (resolved.path, resolved.level) == (str(tmp_path), ComponentAccessLevel.MANAGE)

    project = await resolve_file_root(engine, _UNRESTRICTED, "project")
    assert (project.path, project.exclude) == (str(Path.cwd()), [])

    await engine.database.dispose()


@pytest.mark.parametrize(
    ("id", "error"),
    [
        ("project", NotPermittedError),
        ("component:@hoarder:stash", NotPermittedError),
        ("component:@hoarder:spare", NotFoundError),
        ("component:@hoarder:scratch", NotFoundError),
        ("component:@hoarder:plain", NotFoundError),
        ("component:@missing:stash", NotFoundError),
        ("stash", NotFoundError),
    ],
)
async def test_files_resolve_refuses_a_root_the_caller_may_not_reach(
    tmp_path: Path, id: str, error: type[Exception]
) -> None:
    engine, _ = await _engine(tmp_path)

    with pytest.raises(error):
        await resolve_file_root(engine, await _user(engine, None), id)

    await engine.database.dispose()


async def test_files_warns_about_a_root_holding_a_temporary_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, hoarder = await _engine(tmp_path)
    written: list[LogEntry] = []
    monkeypatch.setattr(type(hoarder.system.log), "write", lambda _, entry: written.append(entry))

    hoarder.system.warn_temporary_file_roots()
    assert [entry.content for entry in written] == [
        "File root 'scratch' holds a temporary directory, which the file browser does not serve."
    ]

    await engine.database.dispose()


async def test_files_on_a_component_lists_its_present_roots(tmp_path: Path) -> None:
    engine, hoarder = await _engine(tmp_path)

    info = await get_component(engine, _UNRESTRICTED, hoarder.system.address)
    assert [(files.field, files.label, files.root) for files in info.files] == [
        ("stash", "Stash", "component:@hoarder:stash"),
        ("ledger", "Ledger", "component:@hoarder:ledger"),
    ]

    await engine.database.dispose()
