from typing import Any

import pytest
from starlette.requests import Request

from ceres import Component, Engine, action
from ceres.__internal__.app.api.routes.components import (
    SendMessageInput,
    _assert_procedure_access,
    _call,
    send_message,
)
from ceres.__internal__.app.shared import Actor
from ceres.address import Address
from ceres.component import ComponentAccessLevel
from ceres.error import NotFoundError, NotPermittedError, ProcedureNotPermittedError
from ceres.permission import PermissionTargetType, UserPermission
from ceres.user import User


class _Widget(Component):
    """A component with a non-public action, used to exercise permission enforcement."""

    @action
    async def turn(self) -> str:
        return "turned"


def _http_scope(path: str, method: str = "POST") -> Any:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "path": path,
        "query_string": b"",
        "root_path": "",
        "scheme": "http",
        "server": ("localhost", 8000),
        "client": ("127.0.0.1", 12345),
        "headers": [],
    }


async def _build_engine() -> tuple[Engine, Component]:
    engine = Engine()
    await engine.database.migrate()

    widget = _Widget(__with_name__="widget")
    engine.attach(widget)

    return engine, widget


async def test_call_action_unrestricted_actor_bypasses_permission_check() -> None:
    """CLI mode (an unrestricted actor) may call a non-public action without any grant."""
    engine, widget = await _build_engine()
    request = Request(_http_scope(f"/api/components/{widget.system.address}/actions/turn/call"))
    actor = Actor(user=None, unrestricted=True)

    result = await _call(
        request=request,
        engine=engine,
        user=None,
        actor=actor,
        address=Address(str(widget.system.address)),
        procedure="turn",
    )

    assert result == "turned"

    await engine.database.dispose()


async def test_procedure_access_denies_unauthenticated_actor() -> None:
    """An unauthenticated actor may not access a non-public procedure."""
    engine, widget = await _build_engine()
    binding = widget.system.get_procedure_bindings()["turn"]

    with pytest.raises(ProcedureNotPermittedError):
        await _assert_procedure_access(
            engine, Actor(user=None, unrestricted=False), widget, binding
        )

    await engine.database.dispose()


async def test_procedure_access_denies_user_below_required_level() -> None:
    """A user whose effective access is below the binding's minimum is denied."""
    engine, widget = await _build_engine()
    user = await engine.database.users.create(
        User.Create(username="viewer", email="viewer@test.com", password="hashed", admin=False)
    )

    # Actions require operate access and the user's effective access defaults to view.
    binding = widget.system.get_procedure_bindings()["turn"]

    with pytest.raises(ProcedureNotPermittedError):
        await _assert_procedure_access(
            engine, Actor(user=user, unrestricted=False), widget, binding
        )

    await engine.database.dispose()


async def test_procedure_access_allows_user_with_operate_grant() -> None:
    """A user granted operate access passes the check for a non-public action."""
    engine, widget = await _build_engine()
    user = await engine.database.users.create(
        User.Create(username="operator", email="operator@test.com", password="hashed", admin=False)
    )
    await engine.database.user_permissions.create(
        UserPermission.Create(
            user_id=user.id,
            target_type=PermissionTargetType.ALL,
            target="",
            level=ComponentAccessLevel.OPERATE,
        )
    )

    binding = widget.system.get_procedure_bindings()["turn"]

    await _assert_procedure_access(engine, Actor(user=user, unrestricted=False), widget, binding)

    await engine.database.dispose()


async def test_send_message_denies_user_without_operate_access() -> None:
    """An authenticated user with no grants cannot send over a component's connection."""
    engine, widget = await _build_engine()
    user = await engine.database.users.create(
        User.Create(username="viewer", email="viewer@test.com", password="hashed", admin=False)
    )

    with pytest.raises(NotPermittedError):
        await send_message(
            engine=engine,
            actor=Actor(user=user, unrestricted=False),
            address=Address(str(widget.system.address)),
            connection="serial",
            input=SendMessageInput(data=b""),
        )

    await engine.database.dispose()


async def test_send_message_allows_unrestricted_actor_past_the_permission_gate() -> None:
    """An unrestricted actor passes the permission gate and fails only on the missing connection."""
    engine, widget = await _build_engine()

    # The widget declares no connections, so passing the permission gate surfaces as a
    # not-found error on the connection rather than a permission error.
    with pytest.raises(NotFoundError):
        await send_message(
            engine=engine,
            actor=Actor(user=None, unrestricted=True),
            address=Address(str(widget.system.address)),
            connection="serial",
            input=SendMessageInput(data=b""),
        )

    await engine.database.dispose()
