from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ceres.__internal__.app.main import (
    CLIAuthMiddleware,
    ErrorMiddleware,
    ScopeModifyMiddleware,
)
from ceres.error import (
    DatabaseUnreachableError,
    NotAuthenticatedError,
    NotFoundError,
)


def _http_scope(
    path: str = "/test",
    method: str = "GET",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> dict[str, Any]:
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
        "headers": headers or [],
    }


def _ws_scope(path: str = "/ws") -> dict[str, Any]:
    return {
        "type": "websocket",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "path": path,
        "query_string": b"",
        "root_path": "",
        "scheme": "ws",
        "server": ("localhost", 8000),
        "client": ("127.0.0.1", 12345),
        "headers": [],
    }


def _lifespan_scope() -> dict[str, Any]:
    return {"type": "lifespan", "asgi": {"version": "3.0"}}


async def _noop_receive() -> dict[str, Any]:
    return {"type": "http.disconnect"}


async def _noop_send(event: dict[str, Any]) -> None:
    pass


def _make_app(side_effect: BaseException | None = None) -> AsyncMock:
    app = AsyncMock()
    if side_effect is not None:
        app.side_effect = side_effect
    return app


def _mock_engine() -> MagicMock:
    engine = MagicMock()
    engine.log = MagicMock()
    engine.log.error = MagicMock()
    engine.log.debug = MagicMock()
    return engine


class TestErrorMiddleware:
    @pytest.mark.asyncio
    async def test_passes_through_on_success(self):
        inner = _make_app()
        middleware = ErrorMiddleware(inner, _mock_engine())

        scope = _http_scope()
        await middleware(scope, _noop_receive, _noop_send)

        inner.assert_called_once_with(scope, _noop_receive, _noop_send)

    @pytest.mark.asyncio
    async def test_catches_error_and_sends_json_response(self):
        inner = _make_app(side_effect=NotFoundError())
        middleware = ErrorMiddleware(inner, _mock_engine())

        sent_events: list[dict[str, Any]] = []

        async def capture_send(event: dict[str, Any]) -> None:
            sent_events.append(event)

        await middleware(_http_scope(), _noop_receive, capture_send)

        assert len(sent_events) == 2
        response_start = sent_events[0]
        assert response_start["type"] == "http.response.start"
        assert response_start["status"] == 404

    @pytest.mark.asyncio
    async def test_error_response_body_is_serialized_error(self):
        inner = _make_app(side_effect=NotFoundError())
        middleware = ErrorMiddleware(inner, _mock_engine())

        sent_events: list[dict[str, Any]] = []

        async def capture_send(event: dict[str, Any]) -> None:
            sent_events.append(event)

        await middleware(_http_scope(), _noop_receive, capture_send)

        response_body = sent_events[1]
        assert response_body["type"] == "http.response.body"

        import json

        body = json.loads(response_body["body"])
        assert body["__error__"] is True
        assert body["type"] == "not-found-error"

    @pytest.mark.asyncio
    async def test_500_error_is_logged(self):
        inner = _make_app(
            side_effect=DatabaseUnreachableError(reason="connection refused"),
        )
        engine = _mock_engine()
        middleware = ErrorMiddleware(inner, engine)

        sent_events: list[dict[str, Any]] = []

        async def capture_send(event: dict[str, Any]) -> None:
            sent_events.append(event)

        await middleware(_http_scope(), _noop_receive, capture_send)

        engine.log.error.assert_called_once()
        assert sent_events[0]["status"] == 500

    @pytest.mark.asyncio
    async def test_4xx_error_is_not_logged(self):
        inner = _make_app(side_effect=NotFoundError())
        engine = _mock_engine()
        middleware = ErrorMiddleware(inner, engine)

        await middleware(_http_scope(), _noop_receive, _noop_send)

        engine.log.error.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_error_exception_is_reraised(self):
        inner = _make_app(side_effect=RuntimeError("unexpected"))
        engine = _mock_engine()
        middleware = ErrorMiddleware(inner, engine)

        with pytest.raises(RuntimeError, match="unexpected"):
            await middleware(_http_scope(), _noop_receive, _noop_send)

        engine.log.error.assert_called_once()

    @pytest.mark.asyncio
    async def test_error_with_fields_serialized_correctly(self):
        inner = _make_app(
            side_effect=DatabaseUnreachableError(reason="host down"),
        )
        middleware = ErrorMiddleware(inner, _mock_engine())

        sent_events: list[dict[str, Any]] = []

        async def capture_send(event: dict[str, Any]) -> None:
            sent_events.append(event)

        await middleware(_http_scope(), _noop_receive, capture_send)

        import json

        body = json.loads(sent_events[1]["body"])
        assert body["reason"] == "host down"
        assert body["type"] == "database-unreachable-error"

    @pytest.mark.asyncio
    async def test_error_subclass_uses_correct_status_code(self):
        inner = _make_app(side_effect=NotAuthenticatedError())
        middleware = ErrorMiddleware(inner, _mock_engine())

        sent_events: list[dict[str, Any]] = []

        async def capture_send(event: dict[str, Any]) -> None:
            sent_events.append(event)

        await middleware(_http_scope(), _noop_receive, capture_send)

        assert sent_events[0]["status"] == 401


class TestCLIAuthMiddleware:
    @pytest.mark.asyncio
    async def test_passes_through_with_correct_token(self):
        inner = _make_app()
        middleware = CLIAuthMiddleware(inner, "secret-token")

        scope = _http_scope(
            headers=[(b"authorization", b"secret-token")],
        )
        await middleware(scope, _noop_receive, _noop_send)

        inner.assert_called_once()

    @pytest.mark.asyncio
    async def test_rejects_missing_authorization(self):
        inner = _make_app()
        middleware = CLIAuthMiddleware(inner, "secret-token")

        with pytest.raises(NotAuthenticatedError):
            await middleware(_http_scope(), _noop_receive, _noop_send)

        inner.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_wrong_token(self):
        inner = _make_app()
        middleware = CLIAuthMiddleware(inner, "secret-token")

        scope = _http_scope(
            headers=[(b"authorization", b"wrong-token")],
        )

        with pytest.raises(NotAuthenticatedError):
            await middleware(scope, _noop_receive, _noop_send)

        inner.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_websocket_without_auth(self):
        inner = _make_app()
        middleware = CLIAuthMiddleware(inner, "secret-token")

        with pytest.raises(NotAuthenticatedError):
            await middleware(_ws_scope(), _noop_receive, _noop_send)

    @pytest.mark.asyncio
    async def test_passes_through_lifespan_without_auth(self):
        inner = _make_app()
        middleware = CLIAuthMiddleware(inner, "secret-token")

        await middleware(_lifespan_scope(), _noop_receive, _noop_send)

        inner.assert_called_once()


class TestScopeModifyMiddleware:
    @pytest.mark.asyncio
    async def test_removes_pathsend_extension(self):
        passed_scope: dict[str, Any] = {}

        async def capture_app(
            scope: dict[str, Any],
            receive: Any,
            send: Any,
        ) -> None:
            passed_scope.update(scope)

        middleware = ScopeModifyMiddleware(capture_app)

        scope = _http_scope()
        scope["extensions"] = {"http.response.pathsend": True, "other": True}

        await middleware(scope, _noop_receive, _noop_send)

        assert "http.response.pathsend" not in passed_scope["extensions"]
        assert passed_scope["extensions"]["other"] is True

    @pytest.mark.asyncio
    async def test_passes_through_without_extensions(self):
        inner = _make_app()
        middleware = ScopeModifyMiddleware(inner)

        await middleware(_http_scope(), _noop_receive, _noop_send)

        inner.assert_called_once()

    @pytest.mark.asyncio
    async def test_passes_through_lifespan_unchanged(self):
        inner = _make_app()
        middleware = ScopeModifyMiddleware(inner)

        scope = _lifespan_scope()
        await middleware(scope, _noop_receive, _noop_send)

        inner.assert_called_once_with(scope, _noop_receive, _noop_send)

    @pytest.mark.asyncio
    async def test_handles_websocket_scope(self):
        passed_scope: dict[str, Any] = {}

        async def capture_app(
            scope: dict[str, Any],
            receive: Any,
            send: Any,
        ) -> None:
            passed_scope.update(scope)

        middleware = ScopeModifyMiddleware(capture_app)

        scope = _ws_scope()
        scope["extensions"] = {"http.response.pathsend": True}

        await middleware(scope, _noop_receive, _noop_send)

        assert "http.response.pathsend" not in passed_scope["extensions"]


class TestErrorMiddlewareIntegrationWithCLIAuth:
    @pytest.mark.asyncio
    async def test_cli_auth_error_caught_by_error_middleware(self):
        async def reject_app(scope: Any, receive: Any, send: Any) -> None:
            raise NotAuthenticatedError()

        engine = _mock_engine()
        middleware = ErrorMiddleware(reject_app, engine)

        sent_events: list[dict[str, Any]] = []

        async def capture_send(event: dict[str, Any]) -> None:
            sent_events.append(event)

        await middleware(_http_scope(), _noop_receive, capture_send)

        assert sent_events[0]["status"] == 401

        import json

        body = json.loads(sent_events[1]["body"])
        assert body["type"] == "not-authenticated-error"
