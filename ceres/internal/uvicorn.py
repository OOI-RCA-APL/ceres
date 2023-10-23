import asyncio
from asyncio import Task
from socket import socket as Socket
from typing import TYPE_CHECKING, Any

from typing_extensions import override
from uvicorn.config import Config
from uvicorn.server import Server as Base

from ceres.internal import logs
from ceres.internal.tasklet import Tasklet

if TYPE_CHECKING:
    from uvicorn.server import Protocols
else:
    Protocols = object


class UvicornConfig(Config):
    pass


class Uvicorn(Tasklet, Base):  # type: ignore
    @override
    async def __run__(self) -> None:
        await self.serve()

    @override
    async def __stop__(self) -> None:
        await self.shutdown()

    @override
    async def serve(self, sockets: Any = None) -> None:
        logs.setup()
        try:
            await super().serve(sockets)
        except SystemExit:
            # TODO: This occurs when the server's port couldn't be opened. We should probably try to
            # reconnect when this happens. For now, Uvicorn logs the error which should help
            # diagnose the problem.
            pass

    @override
    def install_signal_handlers(self) -> None:
        # Don't install anything, this will be handled externally.
        pass

    @override
    async def shutdown(self, sockets: list[Socket] | None = None) -> None:
        async def stop_connection(connection: Protocols) -> None:
            try:
                await connection.close()  # type: ignore
            except Exception:
                connection.shutdown()

        async def stop_task(task: Task[Any]) -> None:
            task.cancel()

        await asyncio.gather(
            *(stop_connection(connection) for connection in self.server_state.connections),
            *(stop_task(task) for task in self.server_state.tasks),
            return_exceptions=True,
        )

        if hasattr(self, "servers"):
            await super().shutdown(sockets)
