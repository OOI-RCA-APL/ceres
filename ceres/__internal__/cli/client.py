from collections.abc import Mapping
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Final, cast

from pydantic import BaseModel, ValidationError

from ceres.__internal__.cli.shared import CLIClientError
from ceres.data import adapt, simplify

if TYPE_CHECKING:
    from aiohttp import ClientSession

    from ceres.__internal__.project import LoadedProject
    from ceres.__internal__.server import CLIServerInfo


class Client:
    """HTTP and WebSocket client for communicating with a running Ceres CLI server."""

    def __init__(self, project: LoadedProject) -> None:
        """Initialize the client for the given loaded project.

        Args:
            project: The loaded project whose CLI server info will be used for connections.
        """
        self.project: Final = project
        self._server_info: CLIServerInfo | None = None

    async def alive(self) -> bool:
        """Check whether the CLI server is reachable and responding.

        Returns:
            True if the server responds successfully, False otherwise.
        """
        from aiohttp import ClientError
        from starlette.status import HTTP_502_BAD_GATEWAY

        try:
            async with self._get_session() as session:
                info = self._get_server_info()
                if info is None:
                    return False

                async with session.get(
                    self._get_http_root_url() + "alive",
                    allow_redirects=True,
                ) as response:
                    if response.status >= HTTP_502_BAD_GATEWAY:
                        return False
        except ClientError:
            return False

        return True

    async def request[T](
        self,
        method: str,
        path: str,
        *,
        data: object = None,
        params: BaseModel | Mapping[str, object] | None = None,
        result: type[T] | None = None,
    ) -> T:
        """Send an HTTP request to the CLI server and return the validated response.

        Args:
            method: The HTTP method (e.g. "GET", "POST").
            path: The API path relative to the server root.
            data: Optional request body, serialized as JSON.
            params: Optional query parameters as a Pydantic model or mapping.
            result: The expected response type for validation. Defaults to `Any`.

        Returns:
            The response body validated against the provided result type.

        Raises:
            CLIClientError: If the server returns a 4xx or 5xx status code.
        """
        if result is None:
            result = cast("type[T]", Any)

        params = simplify(params, exclude_defaults=True)
        adapter = adapt(result)

        async with self._get_session() as session:
            async with session.request(
                method,
                self._get_http_root_url() + path.lstrip("/"),
                json=simplify(data) if data is not None else None,
                params=simplify(params) if params is not None else None,
                allow_redirects=True,
            ) as response:
                if response.status >= 400:
                    try:
                        content = await response.json()
                    except Exception:
                        content = await response.text()

                    raise CLIClientError(content)

                return adapter.validate_python(await response.json())

    @asynccontextmanager
    async def stream[T](
        self,
        path: str,
        *,
        params: BaseModel | Mapping[str, object] | None = None,
        result: type[T] | None = None,
    ):
        """Open a WebSocket connection and yield an async iterator of validated messages.

        Args:
            path: The API path relative to the server root.
            params: Optional query parameters as a Pydantic model or mapping.
            result: The expected message type for validation. Defaults to `Any`.

        Yields:
            An async iterator producing validated messages of type `T`.

        Raises:
            CLIClientError: If the connection closes unexpectedly or receives invalid data.
        """
        from aiohttp import WSMsgType

        if result is None:
            result = cast("type[T]", Any)

        params = simplify(params, exclude_defaults=True)
        adapter = adapt(result)

        async with self._get_session() as session:
            async with session.ws_connect(
                self._get_ws_root_url() + path.lstrip("/"),
                params=simplify(params) if params is not None else None,
            ) as response:

                async def iterate():
                    while True:
                        message = await response.receive()
                        match message.type:
                            case WSMsgType.TEXT | WSMsgType.BINARY:
                                json = message.data
                            case WSMsgType.CLOSE:
                                raise CLIClientError("Connection closed.")
                            case WSMsgType.ERROR:
                                raise CLIClientError(f"Connection error: {message.data}")
                            case _:
                                continue

                        try:
                            yield adapter.validate_json(json)
                        except ValidationError:
                            raise CLIClientError(
                                f"Received invalid JSON data for {result}: {json!r}"
                            )

                yield iterate()

    async def get[T](
        self,
        path: str,
        *,
        params: BaseModel | Mapping[str, object] | None = None,
        result: type[T],
    ) -> T:
        """Send a GET request and return the validated response.

        Args:
            path: The API path relative to the server root.
            params: Optional query parameters as a Pydantic model or mapping.
            result: The expected response type for validation.

        Returns:
            The response body validated against the provided result type.
        """
        return await self.request("GET", path, params=params, result=result)

    async def post[T](
        self,
        path: str,
        data: object | None = None,
        *,
        params: BaseModel | Mapping[str, object] | None = None,
        result: type[T] | None = None,
    ) -> T:
        """Send a POST request with an optional body and return the validated response.

        Args:
            path: The API path relative to the server root.
            data: Optional request body, serialized as JSON.
            params: Optional query parameters as a Pydantic model or mapping.
            result: The expected response type for validation. Defaults to `Any`.

        Returns:
            The response body validated against the provided result type.
        """
        return await self.request("POST", path, data=data, params=params, result=result)

    def _get_server_info(self) -> CLIServerInfo:
        """Return cached server info, reading it from disk on first access.

        Returns:
            The CLI server connection info for this project.

        Raises:
            CLIClientError: If the server info file does not exist or is not readable.
        """
        if self._server_info is None:
            self._server_info = self.project.get_cli_server_info()
            if self._server_info is None:
                raise CLIClientError(
                    f"Server does not appear to be running. {str(self.project.cli_server_info_path)!r} doesn't exist or isn't readable."
                )

        return self._server_info

    def _get_http_root_url(self) -> str:
        """Build and return the base HTTP URL for API requests."""
        info = self._get_server_info()
        return f"http://localhost:{info.port}/api/"

    def _get_ws_root_url(self) -> str:
        """Build and return the base WebSocket URL for streaming connections."""
        info = self._get_server_info()
        return f"ws://localhost:{info.port}/api/"

    def _get_session(self) -> ClientSession:
        """Create and return a new `aiohttp.ClientSession` with the server's auth token."""
        info = self._get_server_info()

        from aiohttp import ClientSession

        return ClientSession(
            headers={"Authorization": f"{info.token}"},
        )
