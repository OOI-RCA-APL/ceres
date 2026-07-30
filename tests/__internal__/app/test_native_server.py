"""End-to-end tests of the native server bridge.

The native server binds a real TCP port on the shared tokio runtime and reaches the
engine back through a host object's coroutines, so these tests cover the whole crossing,
Python to Rust to Python and back, including token parity between the two JWT
implementations.
"""

import asyncio
import json
from typing import TYPE_CHECKING, Any

import httpx
from ceres_core import NativeServer

from ceres import Engine
from ceres.config import Config
from ceres.data import to_json, validate
from ceres.user import User

if TYPE_CHECKING:
    from pathlib import Path
    from uuid import UUID

SECRET = "an-adequately-long-test-signing-secret"
PASSWORD = "pw12345"


class EngineHost:
    """The engine as the native server's host, answering with result envelopes."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def _record(self, user: User | None) -> str:
        if user is None:
            return json.dumps({"ok": None})

        payload = json.loads(to_json(user))
        payload.pop("password", None)
        return json.dumps(
            {
                "ok": {
                    "id": str(user.id),
                    "admin": user.admin,
                    "disabled": user.disabled,
                    "payload": payload,
                }
            }
        )

    async def user(self, id: UUID) -> str:
        return self._record(await self._engine.users.get(id))

    async def verify_login(self, username: str, password: str) -> str:
        user = await self._engine.users.where(username=username).first()
        if user is None or not await self._engine.verify_password(password, user.password):
            return json.dumps({"ok": None})

        return self._record(user)

    async def change_password(self, id: UUID, old_password: str, new_password: str) -> str:
        return json.dumps({"ok": None})


async def _build_engine() -> tuple[Engine, User]:
    engine = Engine()
    await engine.database.migrate()
    await engine.load(
        validate(
            Config,
            {
                "components": [],
                "server": {"port": 0, "authentication": {"secret": SECRET}},
            },
        ),
        checks=(),
    )
    user = await engine.database.users.create(
        User.Create(username="admin", email="a@test.com", password=PASSWORD, admin=True)
    )
    return engine, user


def _build_console(tmp_path: Path) -> Path:
    (tmp_path / "index.html").write_text("<html>native</html>")
    for suffix in ("ico", "png", "svg"):
        (tmp_path / f"favicon.{suffix}").write_bytes(b"icon")

    return tmp_path


async def test_the_native_server_serves_the_engine_over_tcp(tmp_path: Path) -> None:
    engine, user = await _build_engine()
    console = _build_console(tmp_path)

    server = NativeServer.web(
        EngineHost(engine),
        engine.config.server,
        console,
        console / "favicon.ico",
        console / "favicon.png",
        console / "favicon.svg",
    )
    serving: asyncio.Future[Any] = asyncio.ensure_future(server.serve())
    base = f"http://127.0.0.1:{server.port}"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{base}/api/alive")
            assert response.status_code == 200

            response = await client.post(
                f"{base}/api/auth/login", json={"username": "admin", "password": PASSWORD}
            )
            assert response.status_code == 200
            identity = response.json()
            assert identity["user"]["id"] == str(user.id)
            assert "password" not in identity["user"]

            response = await client.get(
                f"{base}/api/auth/me",
                headers={"Authorization": f"Bearer {identity['token']}"},
            )
            assert response.status_code == 200
            assert response.json()["user"]["username"] == "admin"

            # The single-page console serves with the index fallback.
            response = await client.get(f"{base}/console/route")
            assert response.status_code == 200
            assert response.text == "<html>native</html>"
    finally:
        server.stop(0.2)
        await serving
        await engine.database.dispose()


async def test_tokens_verify_across_both_implementations(tmp_path: Path) -> None:
    """Tokens must cross between the two JWT implementations in both directions.

    The reference implementation mints a token the server has to accept, and a token the
    server minted has to decode there, so the claim names and encoding stay compatible.
    """
    from datetime import UTC, datetime, timedelta

    import jwt as pyjwt

    engine, user = await _build_engine()
    console = _build_console(tmp_path)

    server = NativeServer.web(
        EngineHost(engine),
        engine.config.server,
        console,
        console / "favicon.ico",
        console / "favicon.png",
        console / "favicon.svg",
    )
    serving: asyncio.Future[Any] = asyncio.ensure_future(server.serve())
    base = f"http://127.0.0.1:{server.port}"

    try:
        async with httpx.AsyncClient() as client:
            reference = pyjwt.encode(
                {"sub": str(user.id), "exp": datetime.now(UTC) + timedelta(minutes=30)},
                SECRET,
                "HS256",
            )
            response = await client.get(
                f"{base}/api/auth/me",
                headers={"Authorization": f"Bearer {reference}"},
            )
            assert response.status_code == 200
            assert response.json()["user"]["id"] == str(user.id)

            response = await client.post(
                f"{base}/api/auth/login", json={"username": "admin", "password": PASSWORD}
            )
            claims = pyjwt.decode(response.json()["token"], SECRET, ["HS256"])
            assert claims["sub"] == str(user.id)
    finally:
        server.stop(0.2)
        await serving
        await engine.database.dispose()
