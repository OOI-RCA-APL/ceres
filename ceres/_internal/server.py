from __future__ import annotations

import asyncio
from typing import Final, override

from ceres._internal.lazy import lazy_imports
from ceres.tasklet import Tasklet

with lazy_imports(__name__):
    from hypercorn.asyncio import serve
    from hypercorn.config import Config as HypercornConfig

    from ceres._internal.app import App
    from ceres._internal.project import LoadedProject
    from ceres.config import ServerConfig, ServerSSLConfig
    from ceres.engine import Engine


class Server(Tasklet):
    def __init__(self, engine: Engine, project: LoadedProject, config: ServerConfig) -> None:
        hypercorn = HypercornConfig()
        hypercorn.loglevel = "CRITICAL"

        # SSL / HTTPS
        ssl = config.ssl or ServerSSLConfig()
        hypercorn.keyfile = str(ssl.key) if ssl.key is not None else None
        hypercorn.keyfile_password = ssl.key_password
        hypercorn.certfile = str(ssl.cert) if ssl.cert is not None else None
        hypercorn.ca_certs = str(ssl.ca_certs) if ssl.ca_certs is not None else None
        hypercorn.graceful_timeout = 0.1

        bind: list[str] = []
        insecure_bind: list[str] = []

        if config.port is not None:
            bind.append(f"{config.host}:{config.port}")

        if hypercorn.ssl_enabled:
            insecure_bind.append(f"unix:{project.socket_path}")
        else:
            bind.append(f"unix:{project.socket_path}")

        hypercorn.bind = bind
        hypercorn.insecure_bind = insecure_bind

        self._config: Final = config
        self._hypercorn: Final = hypercorn
        self._app: Final = App(engine)

    @property
    def config(self) -> ServerConfig:
        return self._config

    @property
    def binds(self) -> list[str]:
        return [*self.secure_binds, *self.insecure_binds]

    @property
    def secure_binds(self) -> list[str]:
        return self._hypercorn.bind

    @property
    def insecure_binds(self) -> list[str]:
        return self._hypercorn.insecure_bind

    @override
    async def __run__(self) -> None:
        await serve(
            self._app,  # type: ignore
            self._hypercorn,
            shutdown_trigger=lambda: asyncio.Future(),
        )

    @override
    async def __stop__(self) -> None:
        pass
