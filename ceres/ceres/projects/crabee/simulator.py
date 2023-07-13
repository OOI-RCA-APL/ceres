import asyncio
from asyncio import StreamReader, StreamWriter
from datetime import timedelta
from random import randrange

from pydantic import Field

from ceres import Component, routine
from ceres.data import PositiveTimeDelta


class CrabeeSimulator(Component):
    port: int = Field(ge=0)
    interval: PositiveTimeDelta = timedelta(seconds=1)

    @routine
    async def __send_messages(self) -> None:
        while True:
            self.log.info(f"Creating listener on port {self.port}...")
            server = await asyncio.start_server(
                self.__handle,
                "0.0.0.0",
                self.port,
                reuse_port=True,
            )

            try:
                async with server:
                    await server.serve_forever()
            except Exception as exception:
                self.log.error(str(exception).strip())
                await asyncio.sleep(1)
            finally:
                server.close()
                await server.wait_closed()

    async def __handle(self, reader: StreamReader, writer: StreamWriter) -> None:
        while not writer.is_closing():
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

            writer.write(data)
            await writer.drain()
            await asyncio.sleep(self.interval.total_seconds())
