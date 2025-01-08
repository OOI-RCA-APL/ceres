from __future__ import annotations

from typing import Any, Mapping, cast

from pydantic import BaseModel

from ceres._internal.cli.shared import CliCommandFailed
from ceres._internal.lazy import lazy_imports

with lazy_imports(__name__):
    from ceres._internal import util
    from ceres._internal.project import LoadedProject
    from ceres.data import simplify
    from ceres.status import Status


class Client:
    def __init__(self, project: LoadedProject) -> None:
        self.project = project

    async def online(self) -> bool:
        try:
            await self.get("/status", result=Status)
        except Exception:
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

        url = f"http://ceres.local/api/{path.lstrip('/')}"

        if isinstance(params, BaseModel):
            params = {key: value for key, value in params.model_dump(exclude_defaults=True).items()}

        from aiohttp import ClientSession, UnixConnector

        async with ClientSession(connector=UnixConnector(str(self.project.socket_path))) as session:
            async with session.request(
                method,
                url,
                json=simplify(data),
                params=simplify(params),
            ) as response:
                if response.status >= 400:
                    try:
                        content = await response.json()
                    except Exception:
                        content = await response.text()

                    raise CliCommandFailed(content)

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
