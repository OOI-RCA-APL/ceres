import asyncio
from typing import Any

from hypercorn import Config as HypercornConfig
from hypercorn.asyncio import serve
from typing_extensions import override

from ceres.internal.tasklet import Tasklet


class ServerInternalConfig(HypercornConfig):
    pass


class Server(Tasklet):
    def __init__(self, config: ServerInternalConfig, app: Any) -> None:
        self.config = config
        self.app = app

    @override
    async def __run__(self) -> None:
        await serve(self.app, self.config, shutdown_trigger=lambda: asyncio.Future())

    @override
    async def __stop__(self) -> None:
        pass
