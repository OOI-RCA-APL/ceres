import asyncio
from abc import ABC, abstractmethod
from datetime import timedelta
from enum import Enum
from typing import AsyncIterable

from typing_extensions import override

from ceres.component import Component
from ceres.data import ImmutableDataObject, PositiveTimeDelta, jsonify
from ceres.events import (
    ConnectedEvent,
    ConnectFailedEvent,
    ConnectionLostEvent,
    DisconnectedEvent,
    MessageReceivedEvent,
    MessageSentEvent,
)
from ceres.exceptions import ConnectionLostException
from ceres.message import Message, MessageDirection
from ceres.procedure import action, query
from ceres.routine import routine


class ReconnectSettings(ImmutableDataObject):
    interval: PositiveTimeDelta = timedelta(seconds=1)
    backoff: float | None = 2
    max_interval: PositiveTimeDelta | None = timedelta(seconds=60)


class _ReconnectScheduler:
    def __init__(self, settings: ReconnectSettings) -> None:
        self.__initial_interval = settings.interval
        self.__current_interval = settings.interval
        self.__max_interval = settings.max_interval

        if settings.backoff is not None:
            self.__backoff: float = settings.backoff
        else:
            self.__backoff = 1

        self.__retries = 0

    def reset(self) -> None:
        self.__current_interval = self.__initial_interval
        self.__retries = 0

    def next(self) -> timedelta:
        interval = self.__current_interval * self.__backoff
        if self.__max_interval is not None and interval > self.__max_interval:
            interval = self.__max_interval
        self.__current_interval = interval
        self.__retries += 1

        return interval


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"


class Connection(Component, ABC):
    reconnect_settings: ReconnectSettings

    @override
    def __setup__(self) -> None:
        super().__setup__()
        self.__state = ConnectionState.DISCONNECTED
        self.__reconnect_scheduler = _ReconnectScheduler(self.reconnect_settings)

    @override
    async def __stop__(self) -> None:
        await self._try_disconnect()
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

    @abstractmethod
    async def _try_connect(self) -> bool:
        ...

    @abstractmethod
    async def _try_disconnect(self) -> None:
        ...

    @abstractmethod
    async def _send_data(self, data: bytes) -> None:
        ...

    @abstractmethod
    async def _receive_data(self) -> bytes:
        ...

    async def connect(self) -> bool:
        if self.__state == ConnectionState.CONNECTED:
            return True

        self.logger.info(f"Connecting to '{self.target}'...")
        self.__state = ConnectionState.CONNECTING

        try:
            connected = await self._try_connect()
        except Exception as exception:
            connected = False
            if error := str(exception).strip():
                self.logger.error(error)

        if connected:
            self.__state = ConnectionState.CONNECTED
            self.emit_event(ConnectedEvent())
            self.logger.info("Connected successfully.")
        else:
            self.__state = ConnectionState.DISCONNECTED
            self.emit_event(ConnectFailedEvent())
            self.logger.error("Failed to connect.")

        return self.connected

    async def send(self, data: bytes) -> Message:
        try:
            await self._send_data(data)
        except ConnectionLostException:
            self.emit_event(ConnectionLostEvent())
            await self.disconnect()
            raise

        message = Message(
            source=self.address,
            direction=MessageDirection.SEND,
            content=data,
        )

        self.logger.info(f"Sent: {jsonify(message.content)}")
        self.emit_event(MessageSentEvent(message=message))

        return message

    class SendMessageInput(ImmutableDataObject):
        data: bytes

    @action("send-message")
    async def send_message(self, input: SendMessageInput) -> Message:
        return await self.send(input.data)

    @query("get-connection-state")
    async def get_connection_state(self) -> AsyncIterable[ConnectionState]:
        yield self.__state

        async for event in self.events:
            if isinstance(event, ConnectedEvent | DisconnectedEvent):
                yield self.__state

    async def receive(self) -> Message:
        try:
            data = await self._receive_data()
        except ConnectionLostException:
            self.emit_event(ConnectionLostEvent())
            await self.disconnect()
            raise

        message = Message(
            source=self.address,
            direction=MessageDirection.RECEIVE,
            content=data,
        )

        self.logger.info(f"Received: {jsonify(message.content)}")
        self.emit_event(MessageReceivedEvent(message=message))

        return message

    async def disconnect(self) -> None:
        if self.__state == ConnectionState.DISCONNECTED:
            return

        self.logger.info("Disconnecting...")

        try:
            await self._try_disconnect()
        finally:
            self.__state = ConnectionState.DISCONNECTED
            self.emit_event(DisconnectedEvent())
            self.logger.info("Disconnected.")

    @routine
    async def __update(self) -> None:
        while True:
            self.__reconnect_scheduler.reset()

            while not await self.connect():
                seconds = self.__reconnect_scheduler.next().total_seconds()
                self.logger.info(f"Reconnecting in {seconds:g} seconds...")
                await asyncio.sleep(seconds)

            while self.connected:
                try:
                    await self.receive()
                except Exception as exception:
                    if error := str(exception).strip():
                        self.logger.error(error)
