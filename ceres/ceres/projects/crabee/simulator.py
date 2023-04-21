import asyncio
from datetime import timedelta
from random import randrange

import anyio
from anyio.abc import SocketStream
from pydantic import Field

from ceres import Component, routine
from ceres.data import PositiveTimeDelta


class CrabeeSimulator(Component):
    port: int = Field(ge=0)
    interval: PositiveTimeDelta = timedelta(seconds=1)

    @routine
    async def __send_messages(self) -> None:
        self.logger.info(f"Creating listener on port {self.port}...")
        listener = await anyio.create_tcp_listener(
            local_host="0.0.0.0",
            local_port=self.port,
            reuse_port=True,
        )

        await listener.serve(self.__handle)

    async def __handle(self, stream: SocketStream) -> None:
        while True:
            data = (
                " ".join(
                    [
                        f"Temp1={randrange(0, 50)}.00",
                        f"Temp2={randrange(0, 50)}.00",
                        f"Temp3={randrange(0, 50)}.00",
                        f"Pres={1000 + randrange(0, 50)}.00",
                        f"Hum={randrange(0, 50)}.00",
                        f"Pitch={randrange(-50, 50)}.00",
                        f"Roll={randrange(-50, 50)}.00",
                        "Leak1=0",
                        "Leak2=0",
                    ]
                ).encode()
                + b"\n"
            )

            await stream.send(data)
            await asyncio.sleep(self.interval.total_seconds())
