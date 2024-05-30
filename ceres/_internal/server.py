import asyncio
from typing import Any

from hypercorn.asyncio import serve
from hypercorn.config import Config as HypercornConfig
from typing_extensions import override

from ceres.tasklet import Tasklet


class ServerInternalConfig(HypercornConfig):
    pass


class Server(Tasklet):
    def __init__(self, config: ServerInternalConfig, app: Any) -> None:
        self._config = config
        self._app = app

    @override
    async def __run__(self) -> None:
        await serve(self._app, self._config, shutdown_trigger=lambda: asyncio.Future())

    @override
    async def __stop__(self) -> None:
        pass
