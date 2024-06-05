from __future__ import annotations

import asyncio
from typing import Any, override

from ceres._internal.lazy import lazy_imports
from ceres.tasklet import Tasklet

with lazy_imports(__name__):
    from hypercorn.config import Config as HypercornConfig


class Server(Tasklet):
    def __init__(self, config: HypercornConfig, app: Any) -> None:
        self._config = config
        self._app = app

    @override
    async def __run__(self) -> None:
        from hypercorn.asyncio import serve

        await serve(self._app, self._config, shutdown_trigger=lambda: asyncio.Future())

    @override
    async def __stop__(self) -> None:
        pass
