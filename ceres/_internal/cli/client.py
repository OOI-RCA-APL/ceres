from __future__ import annotations

from typing import Any, Mapping, cast

from pydantic import BaseModel

from ceres._internal import util
from ceres._internal.cli.shared import CliClientError
from ceres._internal.lazy import lazy_imports
from ceres._internal.project import LoadedProject
from ceres.data import simplify

with lazy_imports(__name__):
    from aiohttp import ClientSession


class Client:
    def __init__(self, project: LoadedProject) -> None:
        self.project = project

    async def alive(self) -> bool:
        from aiohttp import ClientError

        try:
            async with self.__get_session() as session:
                info = self.project.get_cli_server_info()
                if info is None:
                    return False

                async with session.get("alive", allow_redirects=True) as response:
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

        if isinstance(params, BaseModel):
            params = {key: value for key, value in params.model_dump(exclude_defaults=True).items()}

        async with self.__get_session() as session:
            async with session.request(
                method,
                path.lstrip("/"),
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

                return util.get_type_adapter(result).validate_python(await response.json())  # type: ignore

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

    def __get_session(self) -> ClientSession:
        info = self.project.get_cli_server_info()
        if info is None:
            raise CliClientError(
                f"Server does not appear to be running. {str(self.project.cli_server_info_path)!r} doesn't exist or isn't readable."
            )

        return ClientSession(
            f"http://localhost:{info.port}/api/",
            headers={"Authorization": f"{info.token}"},
        )
