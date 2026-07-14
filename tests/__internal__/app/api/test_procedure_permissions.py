from typing import Any

from starlette.requests import Request

from ceres import Component, Engine, action
from ceres.__internal__.app.api.routes.components import _call
from ceres.__internal__.app.shared import Actor
from ceres.address import Address


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
