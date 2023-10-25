import asyncio
import traceback
from abc import ABC, abstractmethod
from dataclasses import field
from datetime import timedelta
from typing import Annotated

from pydantic import Field
from typing_extensions import override

from ceres.component import Component, action, routine
from ceres.connectivity import Connectivity
from ceres.data import ImmutableDataObject
from ceres.events import (
    ConnectedEvent,
    ConnectFailedEvent,
    ConnectingEvent,
    ConnectionLostEvent,
    DisconnectedEvent,
    DisconnectingEvent,
    MessageReceivedEvent,
    MessageSentEvent,
)
from ceres.exceptions import ConnectionLostException
from ceres.message import Message, MessageContent, MessageDirection
from ceres.schedule import IntervalSchedule
from ceres.status import Status
from ceres.stream import Stream
from ceres.timing import utc


class ReconnectSettings(ImmutableDataObject):
    schedule: IntervalSchedule = Field(
        default_factory=lambda: IntervalSchedule(
            interval=timedelta(seconds=1),
            multiplier=2,
            max=timedelta(seconds=60),
        )
    )


class Connection(Component, ABC):
    separator: bytes = b"\r\n"
    reconnect_settings: ReconnectSettings = field(default_factory=ReconnectSettings)

    @override
    def __setup__(self) -> None:
        super().__setup__()
        self.__connectivity = Connectivity.DISCONNECTED

    @override
    async def __stop__(self) -> None:
        await self.disconnect()
        await super().__stop__()

    @property
    @abstractmethod
    def target(self) -> str:
        ...

    @property
    def connectivity(self) -> Connectivity:
        return self.__connectivity

    @property
    def connected(self) -> bool:
        return self.__connectivity == Connectivity.CONNECTED

    @property
    def messages(self) -> Stream[Message]:
        return self.events.of(MessageSentEvent | MessageReceivedEvent).map(
            lambda event: event.message
        )

    @property
    def sent(self) -> Stream[Message]:
        return self.events.of(MessageSentEvent).map(lambda event: event.message)

    @property
    def received(self) -> Stream[Message]:
        return self.events.of(MessageReceivedEvent).map(lambda event: event.message)

    @override
    async def get_status(self) -> Status:
        status = await super().get_status()
        status.connectivity = self.connectivity
        return status

    @abstractmethod
    async def _try_connect(self) -> bool:
        ...

    @abstractmethod
    async def _try_disconnect(self) -> None:
        ...

    @abstractmethod
    async def _send_data(self, data: bytes) -> bytes | None:
        ...

    @abstractmethod
    async def _poll_data(self) -> bytes | None:
        ...

    async def connect(self) -> bool:
        if self.__connectivity == Connectivity.CONNECTED:
            return True

        self.emit(ConnectingEvent)
        self.__connectivity = Connectivity.CONNECTING

        try:
            connected = await self._try_connect()
        except Exception as exception:
            connected = False
            if error := str(exception).strip():
                self.log.error(error)

        if connected:
            self.__connectivity = Connectivity.CONNECTED
            self.emit(ConnectedEvent)
        else:
            self.__connectivity = Connectivity.DISCONNECTED
            self.emit(ConnectFailedEvent)

        return self.connected

    @action
    async def send_message(
        self,
        data: Annotated[
            MessageContent,
            Field(
                description="""
                Bytes to send over the connection. 'The connection's "separator" value is appended
                automatically if not present.
                """
            ),
        ],
    ) -> Message:
        """
        Send raw data over the connection. Returns the sent message.

        There is no guarantee that the message was will be received host-side, only that if this
        action returns successfully, the data was sent.
        """
        if not self.connected:
            raise ConnectionLostException("connection is lost")

        if not data.endswith(self.separator):
            data += self.separator

        try:
            sent = await self._send_data(data)
        except Exception:
            sent = None

        if sent is None and self.connected:
            self.emit(ConnectionLostEvent)
            await self.disconnect()
            raise ConnectionLostException("connection was lost")

        message = Message(
            address=self.address,
            direction=MessageDirection.SEND,
            content=data,
        )

        self.emit(MessageSentEvent, message=message)
        return message

    async def __poll_message(self) -> Message | None:
        try:
            data = await self._poll_data()
        except Exception:
            self.log.error(traceback.format_exc())
            data = None
            raise

        if data is None:
            if self.connected:
                self.emit(ConnectionLostEvent)
                await self.disconnect()

            return None

        message = Message(
            address=self.address,
            direction=MessageDirection.RECEIVE,
            content=data,
        )

        self.emit(MessageReceivedEvent, message=message)
        return message

    async def disconnect(self) -> None:
        if self.__connectivity == Connectivity.DISCONNECTED:
            return

        self.emit(DisconnectingEvent)

        try:
            await self._try_disconnect()
        finally:
            self.__connectivity = Connectivity.DISCONNECTED
            self.emit(DisconnectedEvent)

    @routine
    async def routine__process_connection(self) -> None:
        while True:
            trigger = self.reconnect_settings.schedule.as_trigger()

            while not await self.connect():
                next = trigger.get_next_fire_time()
                if next is None:
                    break

                delay = (next - utc()).total_seconds()
                self.log.info(f"Reconnecting in {round(delay, 1):g} seconds...")
                await asyncio.sleep(delay)

            while self.connected:
                data = await self.__poll_message()
                if data is None:
                    break
