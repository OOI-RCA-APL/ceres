import asyncio
import traceback
from abc import ABC, abstractmethod
from dataclasses import field
from datetime import timedelta
from enum import Enum
from typing import AsyncIterable

from pydantic import Field
from typing_extensions import override

from ceres.component import Component, action, query, routine
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
from ceres.message import Message, MessageDirection
from ceres.schedule import IntervalSchedule
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


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"


class Connection(Component, ABC):
    reconnect_settings: ReconnectSettings = field(default_factory=ReconnectSettings)

    @override
    def __setup__(self) -> None:
        super().__setup__()
        self.__state = ConnectionState.DISCONNECTED

    @override
    async def __stop__(self) -> None:
        await self.disconnect()
        await super().__stop__()

    @property
    @abstractmethod
    def target(self) -> str:
        ...

    @property
    def state(self) -> ConnectionState:
        return self.__state

    @property
    def connected(self) -> bool:
        return self.__state == ConnectionState.CONNECTED

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
        if self.__state == ConnectionState.CONNECTED:
            return True

        self.emit(ConnectingEvent)
        self.__state = ConnectionState.CONNECTING

        try:
            connected = await self._try_connect()
        except Exception as exception:
            connected = False
            if error := str(exception).strip():
                self.log.error(error)

        if connected:
            self.__state = ConnectionState.CONNECTED
            self.emit(ConnectedEvent)
        else:
            self.__state = ConnectionState.DISCONNECTED
            self.emit(ConnectFailedEvent)

        return self.connected

    @query
    async def get_connection_state(self) -> AsyncIterable[ConnectionState]:
        yield self.__state

        async for event in self.events:
            if isinstance(event, ConnectedEvent | DisconnectedEvent):
                yield self.__state

    @action
    async def send_message(self, data: bytes) -> Message:
        if not self.connected:
            raise ConnectionLostException("connection is lost")

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
        if self.__state == ConnectionState.DISCONNECTED:
            return

        self.emit(DisconnectingEvent)

        try:
            await self._try_disconnect()
        finally:
            self.__state = ConnectionState.DISCONNECTED
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
