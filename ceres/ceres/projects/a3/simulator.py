import asyncio
from asyncio import StreamReader, StreamWriter
from datetime import timedelta
from random import randint

import anyio
from pydantic import NonNegativeInt

from ceres import routine
from ceres.component import Component
from ceres.data import ImmutableDataObject, PositiveTimeDelta
from ceres.internal.utilities import sleep_forever
from ceres.timing import utc


class A3SimulatorConnectionSettings(ImmutableDataObject):
    port: int


class A3SimulatorHostSettings(A3SimulatorConnectionSettings):
    pass


class A3SimulatorDASSettings(A3SimulatorConnectionSettings):
    id: NonNegativeInt
    sampling_interval: PositiveTimeDelta = timedelta(minutes=1)
    sampling_variable_interval: PositiveTimeDelta = timedelta(seconds=8)


class A3Simulator(Component):
    host: A3SimulatorHostSettings | None = None
    das: A3SimulatorDASSettings | None = None

    @routine
    async def __send_messages(self) -> None:
        if self.host is not None:
            self.log.info(f"Creating host listener on port {self.host.port}...")
            host_listener = await asyncio.start_server(
                self.__handle_host,
                "0.0.0.0",
                self.host.port,
                reuse_port=True,
            )
        else:
            host_listener = None

        if self.das is not None:
            self.log.info(f"Creating DAS listener on port {self.das.port}...")
            das_listener = await asyncio.start_server(
                self.__handle_das,
                "0.0.0.0",
                self.das.port,
                reuse_port=True,
            )
        else:
            das_listener = None

        try:
            await asyncio.gather(
                host_listener.serve_forever() if host_listener else sleep_forever(),
                das_listener.serve_forever() if das_listener else sleep_forever(),
            )
        finally:
            if host_listener is not None:
                host_listener.close()
            if das_listener is not None:
                das_listener.close()

    async def __handle_host(self, reader: StreamReader, writer: StreamWriter) -> None:
        pass

    async def __handle_das(self, reader: StreamReader, writer: StreamWriter) -> None:
        if self.das is None:
            return

        while not writer.is_closing():
            now = utc()
            messages = [
                f"%{self.das.id},TIM,253,6,{now.year},{now.month:2},{now.day:2},18,42,40*25",
                f"%{self.das.id},TMP,1,11,4,{randint(257, 300)},2.4229*C3",
                f"%{self.das.id},INC,3,25,1,{randint(257, 300)},0.8844,2.2219*F8",
                f"%{self.das.id},DQZ,2,15,3,258,{randint(14000, 15000)}.{randint(0, 9999):2},2.8339*1D",  # noqa: E501
                f"%{self.das.id},PRS,2,15,5,514,{randint(14000, 15000)}.{randint(0, 9999):2},2.8339*1D",  # noqa: E501
            ]

            async with anyio.move_on_after(self.das.sampling_interval.total_seconds()):
                for message in messages:
                    writer.write(message.encode() + b"\r\n")
                    await writer.drain()
                    await asyncio.sleep(self.das.sampling_variable_interval.total_seconds())
