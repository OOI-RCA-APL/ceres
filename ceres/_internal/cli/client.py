from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Mapping, cast

from pydantic import BaseModel, ValidationError

from ceres._internal import util
from ceres._internal.cli.shared import CliClientError
from ceres._internal.lazy import lazy_imports
from ceres._internal.project import LoadedProject
from ceres.data import simplify

with lazy_imports(__name__):
    from aiohttp import ClientSession

    from ceres._internal.server import CLIServerInfo


class Client:
    def __init__(self, project: LoadedProject) -> None:
        self.project = project
        self.__server_info: CLIServerInfo | None = None

    async def alive(self) -> bool:
        from aiohttp import ClientError

        try:
            async with self.__get_session() as session:
                info = self.__get_server_info()
                if info is None:
                    return False

                async with session.get(
                    self.__get_http_root_url() + "alive",
                    allow_redirects=True,
                ) as response:
                    if response.status >= 400:
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
        if result is None:
            result = cast(type[T], Any)

        params = simplify(params, exclude_defaults=True)
        adapter = util.get_type_adapter(result)

        async with self.__get_session() as session:
            async with session.request(
                method,
                self.__get_http_root_url() + path.lstrip("/"),
                json=simplify(data) if data is not None else None,
                params=simplify(params) if params is not None else None,
                allow_redirects=True,
            ) as response:
                if response.status >= 400:
                    try:
                        content = await response.json()
                    except Exception:
                        content = await response.text()

                    raise CliClientError(content)

                return adapter.validate_python(await response.json())  # type: ignore

    @asynccontextmanager
    async def follow[T](
        self,
        path: str,
        *,
        params: BaseModel | Mapping[str, object] | None = None,
        result: type[T] | None = None,
    ):
        from aiohttp import WSMsgType

        if result is None:
            result = cast(type[T], Any)

        params = simplify(params, exclude_defaults=True)
        adapter = util.get_type_adapter(result)

        async with self.__get_session() as session:
            async with session.ws_connect(
                self.__get_ws_root_url() + path.lstrip("/"),
                params=simplify(params) if params is not None else None,
            ) as response:

                async def iterate():
                    while True:
                        message = await response.receive()
                        match message.type:
                            case WSMsgType.TEXT | WSMsgType.BINARY:
                                json = message.data
                            case WSMsgType.CLOSE:
                                raise CliClientError("Connection closed.")
                            case WSMsgType.ERROR:
                                raise CliClientError(f"Connection error: {message.data}")
                            case _:
                                continue

                        try:
                            yield adapter.validate_json(json)
                        except ValidationError:
                            raise CliClientError(
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
        return await self.request("GET", path, params=params, result=result)

    async def post[T](
        self,
        path: str,
        data: object | None = None,
        *,
        params: BaseModel | Mapping[str, object] | None = None,
        result: type[T] | None = None,
    ) -> T:
        return await self.request("POST", path, data=data, params=params, result=result)

    def __get_server_info(self) -> CLIServerInfo:
        if self.__server_info is None:
            self.__server_info = self.project.get_cli_server_info()
            if self.__server_info is None:
                raise CliClientError(
                    f"Server does not appear to be running. {str(self.project.cli_server_info_path)!r} doesn't exist or isn't readable."
                )

        return self.__server_info

    def __get_http_root_url(self) -> str:
        info = self.__get_server_info()
        return f"http://localhost:{info.port}/api/"

    def __get_ws_root_url(self) -> str:
        info = self.__get_server_info()
        return f"ws://localhost:{info.port}/api/"

    def __get_session(self) -> ClientSession:
        info = self.__get_server_info()
        return ClientSession(
            headers={"Authorization": f"{info.token}"},
        )
