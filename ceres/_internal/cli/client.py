from typing import Any, Mapping, TypeVar

from pydantic import BaseModel

from ceres._internal.cli.plumbing import CLICommandFailed
from ceres._internal.project import Project
from ceres._internal.utilities import get_type_adapter
from ceres.data import simplify
from ceres.status import Status

_T = TypeVar("_T")


class Client:
    def __init__(self, project: Project) -> None:
        self.project = project

    async def online(self) -> bool:
        try:
            await self.get("/status", result=Status)
        except Exception:
            return False

        return True

    async def request(
        self,
        method: str,
        path: str,
        *,
        data: object = None,
        params: BaseModel | Mapping[str, object] | None = None,
        result: type[_T] | None = None,
    ) -> _T:
        if result is None:
            result = Any  # type: ignore

        path = "/api/" + path.lstrip("/")
        path = f"http+unix://{str(self.project.socket_path).replace('/', '%2F')}{path}"

        if isinstance(params, BaseModel):
            params = {
                key: str(value) for key, value in params.model_dump(exclude_defaults=True).items()
            }

        from aiohttp import ClientSession, UnixConnector

        async with ClientSession(connector=UnixConnector(str(self.project.socket_path))) as session:
            async with session.request(
                method,
                path,
                json=simplify(data),
                params=params,
            ) as response:
                if response.status >= 400:
                    try:
                        content = await response.json()
                    except Exception:
                        content = await response.text()

                    raise CLICommandFailed(content)

                return get_type_adapter(result).validate_python(await response.json())  # type: ignore

    async def get(
        self,
        path: str,
        *,
        params: BaseModel | Mapping[str, object] | None = None,
        result: type[_T],
    ) -> _T:
        return await self.request("GET", path, params=params, result=result)

    async def post(
        self,
        path: str,
        data: object | None = None,
        *,
        params: BaseModel | Mapping[str, object] | None = None,
        result: type[_T] | None = None,
    ) -> _T:
        return await self.request("POST", path, data=data, params=params, result=result)
