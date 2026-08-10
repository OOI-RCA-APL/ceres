"""HTTP-level pins of the API's wire behavior.

Every test here goes through the full ASGI stack, middleware, routing, and dependency
resolution included because the rest of the app suite calls handler functions directly
and leaves the wire behavior unpinned. A server port must pass this file unchanged.
"""

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from ceres import Component, Engine, query
from ceres.address import Address
from ceres.component import FileOutput, StreamingOutput
from ceres.config import Config
from ceres.data import to_json, validate
from ceres.particle import Particle
from ceres.user import User

ADMIN_PASSWORD = "correct horse battery staple"
VIEWER_PASSWORD = "viewer password"


class _Probe(Component):
    """A component with a public query, for the anonymous procedure-call routes."""

    @query(permit="public")
    async def ping(self, text: str = "pong") -> str:
        return text


_media: dict[str, Any] = {}
"""What the media component serves, and which of its exit hooks have run."""


def _exit(name: str) -> Callable[[], Awaitable[None]]:
    """An exit hook recording that it ran, under its procedure's name."""

    async def hook() -> None:
        _media.setdefault("exited", []).append(name)

    return hook


class _Media(Component):
    """A component whose queries answer with media, for the described-response path."""

    @query(permit="public")
    async def download(self) -> FileOutput:
        return FileOutput(_media["path"], http_filename="export.csv", on_exit=_exit("download"))

    @query(permit="public", media="text/csv")
    async def rows(self) -> StreamingOutput:
        async def chunks() -> AsyncIterator[bytes]:
            yield b"a,b\n"
            for index in range(3):
                yield f"{index},{index * 2}\n".encode()

        return StreamingOutput(chunks, "text/csv", on_exit=_exit("rows"))

    @query(permit="public", media="application/octet-stream")
    async def endless(self) -> StreamingOutput:
        async def chunks() -> AsyncIterator[bytes]:
            import asyncio

            while True:
                yield b"x" * 4096
                await asyncio.sleep(0.01)

        return StreamingOutput(chunks, "application/octet-stream", on_exit=_exit("endless"))


async def _exited(name: str) -> bool:
    """Whether an exit hook has run, giving the release its moment to arrive."""
    import asyncio

    for _ in range(50):
        if name in _media.get("exited", []):
            return True

        await asyncio.sleep(0.02)

    return False


@asynccontextmanager
async def _serve(
    *,
    authentication: bool = True,
    allow_impersonate: bool = False,
    probe: bool = False,
    media: bool = False,
    cli_token: str | None = None,
    database_path: Path | None = None,
) -> AsyncIterator[tuple[Engine, httpx.AsyncClient]]:
    """Serve an engine natively on a loopback port and yield a client against it.

    Requests travel over real TCP through the native server so routing, middleware,
    authentication, and serialization are all exercised as deployed.
    """
    import asyncio

    # Operations register on import, the same way the engine's server loads them.
    import ceres.__internal__.app.operations  # noqa: F401
    from ceres.__internal__.app.host import Host
    from ceres.__internal__.core import NativeServer

    engine = Engine()

    server: dict[str, Any] = {}
    if authentication:
        server["authentication"] = {
            "secret": "an-adequately-long-test-signing-secret",
            "allow_impersonate": allow_impersonate,
        }

    server["port"] = 0
    configuration: dict[str, Any] = {"components": [], "server": server}
    if database_path is not None:
        # A file-backed database carries a native record store so its record routes and
        # authentication gate serve without Python.
        configuration["database"] = {"type": "sqlite", "path": str(database_path)}

    await engine.load(validate(Config, configuration), checks=())
    await engine.database.migrate()
    if probe:
        engine.attach(_Probe(__with_name__="probe"))

    if media:
        _media["exited"] = []
        engine.attach(_Media(__with_name__="media"))

    host = Host(engine)
    records = engine.database._reader()
    console = Path(__file__).parent.parent.parent.parent.parent / "ceres" / "static" / "console"
    if cli_token is None:
        native = NativeServer.web(
            host,
            engine.config.server,
            console,
            console / "favicon.ico",
            console / "favicon.png",
            console / "favicon.svg",
            records,
        )
    else:
        native = NativeServer.cli(host, engine.config.server, cli_token, records)

    serving = asyncio.ensure_future(native.serve())
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{native.port}") as client:
        try:
            yield engine, client
        finally:
            native.stop(0.2)
            try:
                await asyncio.wait_for(serving, 3)
            except Exception:  # noqa: BLE001
                pass

            await engine.database.dispose()


async def _create_user(engine: Engine, username: str, password: str, admin: bool = False) -> User:
    return await engine.database.users.create(
        User.Create(username=username, email=f"{username}@test.com", password=password, admin=admin)
    )


async def _login(client: httpx.AsyncClient, username: str, password: str) -> dict[str, Any]:
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200
    return response.json()


def _bearer(identity: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {identity['token']}"}


async def test_alive_responds_empty() -> None:
    async with _serve() as (_, client):
        response = await client.get("/api/alive")
        assert response.status_code == 200
        assert response.content == b""


async def test_the_api_root_redirects_to_the_openapi_document() -> None:
    async with _serve() as (_, client):
        response = await client.get("/api")
        assert response.status_code == 307
        assert response.headers["location"] == "/api/openapi.json"


async def test_unknown_api_paths_return_the_error_envelope() -> None:
    """`GET` hits the API catch-all, other methods fall through to the static mount."""
    async with _serve() as (_, client):
        response = await client.get("/api/does-not-exist")
        assert response.status_code == 404
        body = response.json()
        assert body["__error__"] is True
        assert body["type"] == "not-found-error"

        response = await client.post("/api/does-not-exist")
        assert response.status_code == 405
        body = response.json()
        assert body["__error__"] is True
        assert body["type"] == "http-error"


async def test_login_issues_an_identity_the_header_authenticates() -> None:
    async with _serve() as (engine, client):
        user = await _create_user(engine, "admin", ADMIN_PASSWORD, admin=True)
        identity = await _login(client, "admin", ADMIN_PASSWORD)
        assert identity["user"]["id"] == str(user.id)
        assert identity["token"]
        assert "password" not in identity["user"]

        response = await client.get("/api/auth/me", headers=_bearer(identity))
        assert response.status_code == 200
        assert response.json()["user"]["id"] == str(user.id)


async def test_bad_credentials_are_refused() -> None:
    async with _serve() as (engine, client):
        await _create_user(engine, "admin", ADMIN_PASSWORD, admin=True)
        response = await client.post(
            "/api/auth/login", json={"username": "admin", "password": "wrong"}
        )
        assert response.status_code == 401
        assert response.json()["type"] == "bad-credentials-error"


async def test_the_authorization_cookie_authenticates_and_logs_out() -> None:
    async with _serve() as (engine, client):
        user = await _create_user(engine, "admin", ADMIN_PASSWORD, admin=True)
        response = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": ADMIN_PASSWORD, "cookie": "insecure"},
        )
        assert response.status_code == 200
        assert "Authorization" in response.cookies

        response = await client.get("/api/auth/me")
        assert response.status_code == 200
        assert response.json()["user"]["id"] == str(user.id)

        response = await client.post("/api/auth/logout", json={})
        assert response.status_code == 200

        response = await client.get("/api/auth/me")
        assert response.status_code == 401


async def test_the_header_outranks_the_cookie() -> None:
    async with _serve() as (engine, client):
        await _create_user(engine, "admin", ADMIN_PASSWORD, admin=True)
        viewer = await _create_user(engine, "viewer", VIEWER_PASSWORD)

        response = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": ADMIN_PASSWORD, "cookie": "insecure"},
        )
        assert response.status_code == 200

        viewer_identity = await _login(client, "viewer", VIEWER_PASSWORD)
        response = await client.get("/api/auth/me", headers=_bearer(viewer_identity))
        assert response.status_code == 200
        assert response.json()["user"]["id"] == str(viewer.id)


async def test_impersonation_survives_token_reparsing() -> None:
    """The impersonation marker must come back from the token itself, not only from the
    impersonate response so the console still knows after a reload.
    """
    async with _serve(allow_impersonate=True) as (engine, client):
        admin = await _create_user(engine, "admin", ADMIN_PASSWORD, admin=True)
        viewer = await _create_user(engine, "viewer", VIEWER_PASSWORD)
        identity = await _login(client, "admin", ADMIN_PASSWORD)

        response = await client.post(
            "/api/auth/impersonate",
            json={"user_id": str(viewer.id)},
            headers=_bearer(identity),
        )
        assert response.status_code == 200
        impersonated = response.json()
        assert impersonated["user"]["id"] == str(viewer.id)
        assert impersonated["impersonated_by"] == str(admin.id)

        response = await client.get("/api/auth/me", headers=_bearer(impersonated))
        assert response.status_code == 200
        assert response.json()["impersonated_by"] == str(admin.id)


async def test_single_component_statuses_are_reachable() -> None:
    async with _serve(probe=True) as (engine, client):
        await _create_user(engine, "admin", ADMIN_PASSWORD, admin=True)
        identity = await _login(client, "admin", ADMIN_PASSWORD)

        response = await client.get("/api/statuses/@probe", headers=_bearer(identity))
        assert response.status_code == 200
        assert response.json()["address"] == "@probe"

        response = await client.get("/api/statuses/@missing", headers=_bearer(identity))
        assert response.status_code == 404


async def test_statuses_and_statistics_require_authentication() -> None:
    async with _serve(probe=True) as (engine, client):
        assert (await client.get("/api/statuses")).status_code == 401
        assert (await client.get("/api/statistics")).status_code == 401

        await _create_user(engine, "admin", ADMIN_PASSWORD, admin=True)
        identity = await _login(client, "admin", ADMIN_PASSWORD)
        response = await client.get("/api/statuses", headers=_bearer(identity))
        assert response.status_code == 200
        assert [status["address"] for status in response.json()] == ["@probe"]

        assert (await client.get("/api/statistics", headers=_bearer(identity))).status_code == 200


async def test_procedure_listings_require_authentication() -> None:
    async with _serve(probe=True) as (engine, client):
        for namespace in ("procedures", "queries", "actions"):
            response = await client.get(f"/api/components/@probe/{namespace}")
            assert response.status_code == 401

        await _create_user(engine, "admin", ADMIN_PASSWORD, admin=True)
        identity = await _login(client, "admin", ADMIN_PASSWORD)
        response = await client.get("/api/components/@probe/queries", headers=_bearer(identity))
        assert response.status_code == 200
        assert "ping" in {binding["name"] for binding in response.json()}


async def test_component_particle_types_route_answers_a_list() -> None:
    async with _serve(probe=True) as (engine, client):
        await _create_user(engine, "admin", ADMIN_PASSWORD, admin=True)
        identity = await _login(client, "admin", ADMIN_PASSWORD)

        response = await client.get(
            "/api/components/@probe/particle-types", headers=_bearer(identity)
        )
        assert response.status_code == 200
        assert response.json() == []


async def test_public_procedures_call_anonymously() -> None:
    """A public procedure is callable without credentials, by POST body and by GET query
    parameters alike.
    """
    async with _serve(probe=True) as (_, client):
        response = await client.post(
            "/api/components/@probe/queries/ping/call", json={"text": "hello"}
        )
        assert response.status_code == 200
        assert response.json() == "hello"

        response = await client.get("/api/components/@probe/queries/ping/call?text=hi")
        assert response.status_code == 200
        assert response.json() == "hi"


async def test_a_call_by_query_reads_the_arguments_parameter() -> None:
    """The `arguments` parameter carries a JSON object, with plain parameters over it."""
    async with _serve(probe=True) as (_, client):
        response = await client.get(
            '/api/components/@probe/queries/ping/call?arguments={"text": "encoded"}'
        )
        assert response.status_code == 200
        assert response.json() == "encoded"

        # A plain parameter wins over the same name inside `arguments`.
        response = await client.get(
            '/api/components/@probe/queries/ping/call?arguments={"text": "encoded"}&text=plain'
        )
        assert response.status_code == 200
        assert response.json() == "plain"

        response = await client.get("/api/components/@probe/queries/ping/call?arguments=[1]")
        assert response.status_code == 400


async def test_disabling_authentication_admits_the_user_routes() -> None:
    """An unrestricted context has no user, which the routes taking one still admit."""
    async with _serve(authentication=False) as (_, client):
        assert (await client.get("/api/workspaces")).status_code == 200
        assert (await client.get("/api/users")).status_code == 200
        assert (await client.get("/api/statuses")).status_code == 200


async def test_updating_a_missing_user_is_not_found() -> None:
    async with _serve() as (engine, client):
        await _create_user(engine, "admin", ADMIN_PASSWORD, admin=True)
        identity = await _login(client, "admin", ADMIN_PASSWORD)

        response = await client.patch(
            f"/api/users/{uuid4()}", json={"email": "new@test.com"}, headers=_bearer(identity)
        )
        assert response.status_code == 404
        assert response.json()["type"] == "not-found-error"


async def test_group_membership_routes_require_the_group() -> None:
    """Listing or adding members refuses when no group carries the ID in the path."""
    async with _serve() as (engine, client):
        await _create_user(engine, "admin", ADMIN_PASSWORD, admin=True)
        identity = await _login(client, "admin", ADMIN_PASSWORD)
        missing = uuid4()

        response = await client.get(f"/api/groups/{missing}/members", headers=_bearer(identity))
        assert response.status_code == 404

        response = await client.post(
            f"/api/groups/{missing}/members",
            json={"user_id": str(uuid4()), "group_id": str(missing)},
            headers=_bearer(identity),
        )
        assert response.status_code == 404

        response = await client.post(
            f"/api/users/{uuid4()}/group-memberships/{missing}", headers=_bearer(identity)
        )
        assert response.status_code == 404


async def test_record_routes_serve_natively_with_wire_parity(tmp_path: Path) -> None:
    """On a native-store backend, record routes serve without Python and match it.

    The listing, count, and single-record routes answer through the native filter
    subset, their gate resolves the user natively, and every payload must equal what
    the Python query layer would have produced. A construct outside the subset still
    answers correctly through the delegated operation.
    """
    from ceres.particle import Particle

    async with _serve(database_path=tmp_path / "records.sqlite") as (engine, client):
        await _create_user(engine, "admin", ADMIN_PASSWORD, admin=True)
        identity = await _login(client, "admin", ADMIN_PASSWORD)

        for index in range(4):
            await engine.database.particles.create(
                Particle.Create(
                    address=Address("@sensor.temp" if index % 2 == 0 else "@motor"),
                    type="sample" if index % 2 == 0 else "sweep",
                    data={"index": index},
                )
            )

        # The gate itself runs natively, and anonymous callers still refuse.
        assert (await client.get("/api/particles")).status_code == 401

        listing = await client.get(
            "/api/particles?type=sample&order=timestamp:desc", headers=_bearer(identity)
        )
        assert listing.status_code == 200
        query = engine.__manager__(Particle).where(
            validate(Particle.Filter, {"type": "sample", "order": "timestamp:desc"})
        )
        expected = [json.loads(to_json(entity)) for entity in await query]
        assert listing.json() == expected
        assert len(expected) == 2

        count = await client.get("/api/particles/count?type=sweep", headers=_bearer(identity))
        assert count.status_code == 200
        assert count.json() == 2

        single = await client.get(f"/api/particles/{expected[0]['id']}", headers=_bearer(identity))
        assert single.status_code == 200
        assert single.json() == expected[0]

        from uuid import uuid4

        missing = await client.get(f"/api/particles/{uuid4()}", headers=_bearer(identity))
        assert missing.status_code == 404

        # A construct outside the compiler, subsampling, delegates and still answers
        # correctly, and a native operation filter answers identically to the query
        # layer.
        delegated = await client.get("/api/particles?subsample_every=1h", headers=_bearer(identity))
        assert delegated.status_code == 200
        operation = await client.get("/api/particles?type_prefix=sa", headers=_bearer(identity))
        assert operation.status_code == 200
        assert operation.json() == [
            json.loads(to_json(entity))
            for entity in await engine.__manager__(Particle).where(
                validate(Particle.Filter, {"type_prefix": "sa"})
            )
        ]

        # A limit beyond the route's cap is the operation's validation error.
        over = await client.get("/api/particles?limit=999999", headers=_bearer(identity))
        assert over.status_code == 422

        # An invalid filter value delegates so the canonical Pydantic envelope serves,
        # with its per-field problems.
        invalid = await client.get("/api/particles?type=1&limit=-2", headers=_bearer(identity))
        assert invalid.status_code == 422
        body = invalid.json()
        assert body["type"] == "validation-failed-error"
        assert any(problem["location"] == ["limit"] for problem in body["problems"])

        unknown = await client.get("/api/particles?nope=1", headers=_bearer(identity))
        assert unknown.status_code == 422
        assert unknown.json()["problems"][0]["type"] == "extra_forbidden"


async def test_a_file_output_serves_the_file_with_its_headers(tmp_path: Path) -> None:
    """A procedure answering with a file streams it, described rather than serialized."""
    _media["path"] = tmp_path / "report.csv"
    _media["path"].write_bytes(b"name,value\nalpha,1\n")

    async with _serve(media=True) as (_, client):
        response = await client.get("/api/components/@media/queries/download/call")

        assert response.status_code == 200
        assert response.content == b"name,value\nalpha,1\n"
        assert response.headers["content-type"] == "text/csv"
        assert response.headers["content-length"] == "19"
        assert response.headers["content-disposition"] == 'attachment; filename="export.csv"'
        assert await _exited("download")


async def test_a_missing_file_refuses_rather_than_truncating() -> None:
    """The file is stat'd before the response starts so its absence is a plain failure."""
    _media["path"] = Path("/nonexistent/report.csv")

    async with _serve(media=True) as (_, client):
        response = await client.get("/api/components/@media/queries/download/call")

        assert response.status_code == 500
        assert response.json()["__error__"] is True


async def test_a_streaming_output_serves_its_chunks() -> None:
    """A procedure answering with a stream has its chunks pulled across as raw bytes."""
    async with _serve(media=True) as (_, client):
        response = await client.get("/api/components/@media/queries/rows/call")

        assert response.status_code == 200
        assert response.content == b"a,b\n0,0\n1,2\n2,4\n"
        assert response.headers["content-type"] == "text/csv"
        assert "content-length" not in response.headers
        assert await _exited("rows")


async def test_a_client_leaving_mid_stream_still_runs_the_exit_hook() -> None:
    """Releasing the body runs the hook so a download abandoned partway runs it too."""
    async with _serve(media=True) as (_, client):
        async with client.stream("GET", "/api/components/@media/queries/endless/call") as response:
            assert response.status_code == 200
            chunks = response.aiter_bytes()
            assert len(await anext(chunks)) > 0

        assert await _exited("endless")


async def test_config_routes_gate_by_admin_and_scrub_credentials() -> None:
    async with _serve() as (engine, client):
        assert (await client.get("/api/config")).status_code == 401
        assert (await client.get("/api/config/console")).status_code == 200

        await _create_user(engine, "viewer", VIEWER_PASSWORD)
        viewer_identity = await _login(client, "viewer", VIEWER_PASSWORD)
        response = await client.get("/api/config", headers=_bearer(viewer_identity))
        assert response.status_code == 403
        assert response.json()["type"] == "not-permitted-error"

        await _create_user(engine, "admin", ADMIN_PASSWORD, admin=True)
        identity = await _login(client, "admin", ADMIN_PASSWORD)
        response = await client.get("/api/config", headers=_bearer(identity))
        assert response.status_code == 200
        assert "secret" not in response.text


async def test_record_listings_match_the_pydantic_wire_format() -> None:
    async with _serve() as (engine, client):
        await _create_user(engine, "admin", ADMIN_PASSWORD, admin=True)
        identity = await _login(client, "admin", ADMIN_PASSWORD)

        particle = await engine.database.particles.create(
            Particle.Create(address=Address("@sensor.temp"), type="sample", data={"a": 1})
        )

        response = await client.get("/api/particles", headers=_bearer(identity))
        assert response.status_code == 200
        assert response.json() == [json.loads(to_json(particle))]

        response = await client.get("/api/particles?limit=999999", headers=_bearer(identity))
        assert response.status_code == 422
        assert response.json()["type"] == "validation-failed-error"


async def test_validation_failures_use_the_problem_envelope() -> None:
    async with _serve() as (engine, client):
        await _create_user(engine, "admin", ADMIN_PASSWORD, admin=True)
        identity = await _login(client, "admin", ADMIN_PASSWORD)

        response = await client.get("/api/particles?limit=abc", headers=_bearer(identity))
        assert response.status_code == 422
        body = response.json()
        assert body["__error__"] is True
        assert body["type"] == "validation-failed-error"
        assert body["problems"]


async def test_the_cli_app_requires_its_token_and_bypasses_permissions() -> None:
    """The CLI control app takes its raw token, grants unrestricted access, and carries no
    console.
    """
    async with _serve(cli_token="cli-test-token") as (_, client):
        assert (await client.get("/api/config")).status_code == 401
        assert (
            await client.get("/api/config", headers={"Authorization": "wrong"})
        ).status_code == 401

        response = await client.get("/api/config", headers={"Authorization": "cli-test-token"})
        assert response.status_code == 200

        response = await client.get("/favicon.ico", headers={"Authorization": "cli-test-token"})
        assert response.status_code == 404


async def test_missing_users_under_unrestricted_yield_the_http_error_envelope() -> None:
    """Routes that require a concrete user answer with the bare HTTP envelope when the
    actor is unrestricted but anonymous, a second error shape ports must reproduce.
    """
    async with _serve(authentication=False) as (_, client):
        response = await client.post(
            "/api/auth/change-password",
            json={"old_password": "a", "new_password": "long enough password"},
        )
        assert response.status_code == 401
        body = response.json()
        assert body["__error__"] is True
        assert body["type"] == "http-error"


async def test_large_responses_compress() -> None:
    """A response over the minimum size negotiates one of the offered codecs."""
    async with _serve() as (engine, client):
        await _create_user(engine, "admin", ADMIN_PASSWORD, admin=True)
        identity = await _login(client, "admin", ADMIN_PASSWORD)

        address = Address("@sensor.temp")
        for index in range(50):
            await engine.database.particles.create(
                Particle.Create(address=address, type="sample", data={"index": index})
            )

        response = await client.get(
            "/api/particles",
            headers={**_bearer(identity), "Accept-Encoding": "gzip, br, zstd"},
        )
        assert response.status_code == 200
        assert response.headers.get("content-encoding") in {"gzip", "br", "zstd"}


async def test_favicons_serve_on_the_web_app() -> None:
    async with _serve() as (_, client):
        for suffix, media_type in (
            ("ico", "image/x-icon"),
            ("png", "image/png"),
            ("svg", "image/svg+xml"),
        ):
            response = await client.get(f"/favicon.{suffix}")
            assert response.status_code == 200
            assert response.headers["content-type"].startswith(media_type)


async def test_unknown_console_paths_fall_back_to_the_index() -> None:
    """The console mount serves `index.html` for any unmatched path, which lets
    the single-page app own its routes.
    """
    async with _serve() as (_, client):
        index = await client.get("/")
        assert index.status_code == 200

        fallback = await client.get("/some/console/route")
        assert fallback.status_code == 200
        assert fallback.content == index.content
