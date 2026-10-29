from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from ceres import Address, Bound, Component, Engine, Mount
from ceres.__internal__.app.handlers.exporters import (
    ExportRunRequest,
    get_component_exporters,
    get_exporter_runs,
    start_exporter_run,
)
from ceres.__internal__.app.shared import Actor
from ceres.component import ComponentAccessLevel, ComponentConfig
from ceres.data import validate
from ceres.error import NotFoundError, NotPermittedError, NotRunningError
from ceres.permission import PermissionTargetType, UserPermission
from ceres.user import User

if TYPE_CHECKING:
    from pathlib import Path

_UNRESTRICTED = Actor(user=None, unrestricted=True)
_AFTER = datetime(2026, 1, 1, tzinfo=UTC)


class _Archive(Component):
    output: Bound[Mount] = Mount.Field(...)


async def _build_engine(root: Path) -> Engine:
    """Build an engine holding `@archive`, viewable by default, with one hourly csv exporter."""
    engine = Engine()
    await engine.database.migrate()
    config = validate(
        ComponentConfig,
        {
            "name": "archive",
            "class": _Archive,
            "access": ComponentAccessLevel.VIEW,
            "arguments": {"output": "."},
            "exporters": [
                {
                    "name": "messages",
                    "exports": "message",
                    "format": "csv",
                    "period": "hour",
                }
            ],
        },
    )
    engine.attach(
        _Archive(output=Mount(root), __with_name__="archive", __with_config__=config)  # type: ignore[reportCallIssue]
    )
    return engine


async def _viewer(engine: Engine) -> Actor:
    user = await engine.database.users.create(
        User.Create(username="viewer", email="viewer@test.com", password="hashed", admin=False)
    )
    return Actor(user=user, unrestricted=False)


async def _operator(engine: Engine) -> Actor:
    actor = await _viewer(engine)
    assert actor.user is not None
    await engine.database.user_permissions.create(
        UserPermission.Create(
            user_id=actor.user.id,
            target_type=PermissionTargetType.COMPONENT,
            target="@archive",
            level=ComponentAccessLevel.OPERATE,
        )
    )
    return actor


async def test_get_component_exporters_describes_each_exporter(tmp_path: Path) -> None:
    """Each configured exporter is listed with its resolved settings to a viewer."""
    engine = await _build_engine(tmp_path)

    result = await get_component_exporters(
        engine=engine, actor=await _viewer(engine), address=Address("@archive")
    )

    now = datetime.now(UTC)
    assert [
        (info.name, info.format, info.merges, info.mount, info.path, info.file, info.live)
        for info in result
    ] == [
        (
            "messages",
            "csv",
            True,
            "output",
            "{exporter}_{yyyy}{MM}{dd}T{HH}",
            f"messages_{now:%Y%m%dT%H}.csv",
            True,
        )
    ]
    assert result[0].last_run is None


async def test_get_component_exporters_carries_the_newest_run(tmp_path: Path) -> None:
    """The listing carries each exporter's newest run, so one request shows its progress."""
    engine = await _build_engine(tmp_path)
    component = engine.get_component("@archive")
    assert component is not None
    exporters = component.system.exporters
    await exporters.run("messages", _AFTER, _AFTER + timedelta(hours=1))
    newest = await exporters.run("messages", _AFTER, _AFTER + timedelta(hours=2))

    (info,) = await get_component_exporters(
        engine=engine, actor=_UNRESTRICTED, address=Address("@archive")
    )

    assert info.last_run == newest.summary()


async def test_start_exporter_run_requires_operate(tmp_path: Path) -> None:
    """Viewing a component is not enough to start an export run."""
    engine = await _build_engine(tmp_path)

    with pytest.raises(NotPermittedError):
        await start_exporter_run(
            engine=engine,
            actor=await _viewer(engine),
            address=Address("@archive"),
            name="messages",
            request=ExportRunRequest(after=_AFTER),
        )


async def test_get_exporter_runs_starts_empty(tmp_path: Path) -> None:
    """A viewer sees no runs before the first one."""
    engine = await _build_engine(tmp_path)

    result = await get_exporter_runs(
        engine=engine, actor=await _viewer(engine), address=Address("@archive"), name="messages"
    )

    assert result == []


async def test_exporter_handlers_refuse_an_unknown_exporter(tmp_path: Path) -> None:
    """An exporter name the component lacks is a not-found."""
    engine = await _build_engine(tmp_path)

    with pytest.raises(NotFoundError):
        await get_exporter_runs(
            engine=engine, actor=_UNRESTRICTED, address=Address("@archive"), name="missing"
        )


async def test_start_exporter_run_refuses_a_stopped_component(tmp_path: Path) -> None:
    """A run needs the component running to own its task."""
    engine = await _build_engine(tmp_path)

    with pytest.raises(NotRunningError):
        await start_exporter_run(
            engine=engine,
            actor=await _operator(engine),
            address=Address("@archive"),
            name="messages",
            request=ExportRunRequest(after=_AFTER),
        )


def test_export_run_request_refuses_an_empty_range() -> None:
    """`after` must come before `before`."""
    with pytest.raises(ValueError, match="`after` must precede `before`"):
        validate(ExportRunRequest, {"after": _AFTER, "before": _AFTER})
